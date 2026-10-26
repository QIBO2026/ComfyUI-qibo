import requests
import json
import time
import torch
import numpy as np
from PIL import Image
from io import BytesIO
import os
import base64
import tempfile
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from .qibo_auth import (
    load_config, save_config,
    load_api_tokens, save_api_tokens,
    parse_api_tokens, get_api_endpoint, save_tokens_on_success
)
from .qibo_pic_gallery_node import _save_image_and_meta, _load_index_map
from .qibo_repo_uploader import (
    tensor_to_repo_url, upload_images_to_repo, upload_pil_image,
    pil_to_repo_url_or_base64
)

try:
    from server import PromptServer
    from aiohttp import web
    _SERVER_OK = True
except Exception:
    _SERVER_OK = False
    PromptServer = None
    web = None

_BATCH_CANCEL = {"cancelled": False}

_PROMPT_MAX_LEN = 4000

def _truncate_prompt(prompt: str, limit: int = _PROMPT_MAX_LEN) -> str:
    if len(prompt) <= limit:
        return prompt
    truncated = prompt[:limit - 3] + "..."
    print(f"⚠️ prompt 长度 {len(prompt)} 超过模型上限 {limit}，已截断至 {len(truncated)} 字符")
    return truncated

_BATCH_RECOVER = {"running": False, "cancel": False}

_CN_NUM = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
           '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
_NUM_TO_CN = {v: k for k, v in _CN_NUM.items()}
_NUM_PAT = r'(?:[1-9]|10|一|二|三|四|五|六|七|八|九|十)'
_PREFIX_PAT = r'(?:图|pic|img|image|picture|photo|p)'
_SEP_PAT = r'[\s_-]*'


def _to_num(g):
    return _CN_NUM.get(g, int(g) if g.isdigit() else 0)


def _remap_prompt_refs(prompt_text, old_to_new):
    """按 {原图号: 新图号} 重写 prompt 中的所有图号引用。
    未被映射的图号保持原样。old_to_new 为空或恒等时原样返回。"""
    if not prompt_text or not old_to_new:
        return prompt_text
    ref_re = re.compile(
        r'(' + _PREFIX_PAT + _SEP_PAT + r')(' + _NUM_PAT + r')',
        re.IGNORECASE
    )

    def _sub(m):
        g = m.group(2)
        old = _to_num(g)
        if old not in old_to_new:
            return m.group(0)
        new = old_to_new[old]
        if g in _CN_NUM:
            return m.group(1) + _NUM_TO_CN.get(new, str(new))
        return m.group(1) + str(new)

    return ref_re.sub(_sub, prompt_text)


def _resolve_image_refs(prompt_text, image_urls, port_nums=None):
    """扫描 prompt 中引用的图片端口号，筛选 image_urls 只保留被引用的，
    并把 prompt 中的图号重映射为筛选后的连续序号（图1起）。

    Args:
        prompt_text: 提示词文本
        image_urls: 图片 URL 列表，顺序与 port_nums 一一对应
        port_nums: 每张图片对应的输入端口号，None 时默认 [1, 2, 3, ...]

    Returns:
        (new_prompt, filtered_urls, referenced_ports)
    """
    if port_nums is None:
        port_nums = list(range(1, len(image_urls) + 1))

    referenced = set()
    p_text = prompt_text or ""

    range_re = re.compile(
        _PREFIX_PAT + _SEP_PAT + r'(' + _NUM_PAT + r')'
        + r'\s*(?:到|to|through|until|-|~|–|—)\s*'
        + _PREFIX_PAT + _SEP_PAT + r'(' + _NUM_PAT + r')',
        re.IGNORECASE
    )
    for m in range_re.finditer(p_text):
        a, b = _to_num(m.group(1)), _to_num(m.group(2))
        if a > 0 and b > 0:
            for n in range(min(a, b), max(a, b) + 1):
                referenced.add(n)

    single_re = re.compile(
        r'(' + _PREFIX_PAT + _SEP_PAT + r')(' + _NUM_PAT + r')',
        re.IGNORECASE
    )
    for m in single_re.finditer(p_text):
        num = _to_num(m.group(2))
        if num > 0:
            referenced.add(num)

    if not referenced:
        return prompt_text, image_urls, set()

    port_to_idx = {p: i for i, p in enumerate(port_nums) if i < len(image_urls)}
    valid_refs = sorted(r for r in referenced if r in port_to_idx)

    if not valid_refs:
        return prompt_text, image_urls, set()

    filtered = [image_urls[port_to_idx[r]] for r in valid_refs]
    num_map = {old: new for new, old in enumerate(valid_refs, 1)}
    new_prompt = _remap_prompt_refs(prompt_text, num_map)
    return new_prompt, filtered, set(valid_refs)


def _resolve_batch_tasks_json_path():
    """批量任务记录 JSON 路径。"""
    from .qibo_pic_gallery_node import _resolve_gallery_dir
    directory = _resolve_gallery_dir("output")
    return os.path.join(directory, "qibo_batch_tasks.json")


def _load_batch_tasks():
    """读取批量任务记录。"""
    path = _resolve_batch_tasks_json_path()
    if not os.path.isfile(path):
        return {"tasks": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "tasks" not in data:
            return {"tasks": []}
        return data
    except Exception:
        return {"tasks": []}


def _save_batch_tasks(data):
    """写入批量任务记录。"""
    path = _resolve_batch_tasks_json_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _record_batch_task(task_id, shot_id="", title="", filename="",
                       prompt="", negative_prompt="", model="",
                       image_urls=None, seed=None, status="pending",
                       result_url=None):
    """记录或更新一条批量任务（按 task_id 去重，最新在前）。"""
    data = _load_batch_tasks()
    tasks = data["tasks"]
    existing = None
    for t in tasks:
        if t.get("task_id") == task_id:
            existing = t
            break
    if existing is None:
        stored_urls = []
        for u in (image_urls or []):
            if isinstance(u, str) and u.startswith("data:image"):
                stored_urls.append(f"<base64 {len(u)//1024}KB>")
            else:
                stored_urls.append(u)
        existing = {
            "task_id": task_id,
            "shot_id": shot_id,
            "title": title,
            "filename": filename,
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "model": model,
            "image_urls": stored_urls,
            "seed": seed,
            "submitted_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        tasks.insert(0, existing)
    existing["status"] = status
    if result_url:
        existing["result_url"] = result_url
    if status == "done":
        existing["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save_batch_tasks(data)


def _update_batch_task_status(task_id, status, result_url=None):
    """仅更新某条任务的状态。"""
    data = _load_batch_tasks()
    for t in data["tasks"]:
        if t.get("task_id") == task_id:
            t["status"] = status
            if result_url:
                t["result_url"] = result_url
            if status == "done":
                t["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            break
    _save_batch_tasks(data)


def _poll_task_and_download(task_id, token, max_wait_seconds=720):
    """用 task_id 轮询并下载结果图片，返回 PIL Image 或 None。"""
    common_headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }
    poll_headers = {**common_headers, 'X-ModelScope-Task-Type': 'image_generation'}
    poll_start = time.time()
    poll_interval = 2
    while True:
        if _BATCH_RECOVER["cancel"]:
            return None
        try:
            resp = requests.get(
                get_api_endpoint('image_edit', 'task_query_url').replace('{task_id}', task_id),
                headers=poll_headers, timeout=30
            )
            if resp.status_code != 200:
                print(f"⚠️ [恢复] task_id={task_id} 查询失败: {resp.status_code}", flush=True)
                return None
            task_data = resp.json()
        except Exception as e:
            print(f"⚠️ [恢复] task_id={task_id} 查询异常: {e}", flush=True)
            return None
        status = task_data.get('task_status', '')
        elapsed = int(time.time() - poll_start)
        if status == 'SUCCEED':
            output_images = task_data.get('output_images') or []
            if not output_images:
                return None
            result_url = output_images[0]
            _update_batch_task_status(task_id, "succeed", result_url=result_url)
            try:
                img_resp = requests.get(result_url, timeout=30)
                if img_resp.status_code != 200:
                    return None
                pil_image = Image.open(BytesIO(img_resp.content))
                if pil_image.mode != 'RGB':
                    pil_image = pil_image.convert('RGB')
                return pil_image
            except Exception as e:
                print(f"⚠️ [恢复] task_id={task_id} 下载失败: {e}", flush=True)
                return None
        if status == 'FAILED':
            _update_batch_task_status(task_id, "failed")
            return None
        if elapsed > max_wait_seconds:
            print(f"⚠️ [恢复] task_id={task_id} 轮询超时 ({max_wait_seconds}s)", flush=True)
            return None
        time.sleep(poll_interval)


def _recover_batch_tasks(tokens, config):
    """后台线程：恢复未完成的批量任务。"""
    _BATCH_RECOVER["running"] = True
    _BATCH_RECOVER["cancel"] = False
    try:
        data = _load_batch_tasks()
        pending = [t for t in data["tasks"] if t.get("status") in ("pending", "succeed")]
        total = len(pending)
        if total == 0:
            _send_batch_progress("", "无待恢复任务", 0, 0, "finished")
            return
        print(f"🔄 [恢复] 共 {total} 个待恢复任务", flush=True)
        _send_batch_progress("恢复", f"共{total}个任务", 0, total, "generating")
        done_count = 0
        for idx, task in enumerate(pending):
            if _BATCH_RECOVER["cancel"]:
                print(f"⏹️ [恢复] 用户取消", flush=True)
                _send_batch_progress("恢复", "已取消", done_count, total, "cancelled")
                return
            task_id = task.get("task_id", "")
            shot_id = task.get("shot_id", "")
            title = task.get("title", "")
            filename = task.get("filename", "")
            prompt = task.get("prompt", "")
            model = task.get("model", "")
            status = task.get("status", "")
            _send_batch_progress(shot_id, title, idx + 1, total, "generating")
            print(f"🔄 [恢复] ({idx+1}/{total}) task_id={task_id} status={status}", flush=True)
            token = tokens[idx % len(tokens)]
            if status == "succeed" and task.get("result_url"):
                try:
                    img_resp = requests.get(task["result_url"], timeout=30)
                    if img_resp.status_code == 200:
                        pil_image = Image.open(BytesIO(img_resp.content))
                        if pil_image.mode != 'RGB':
                            pil_image = pil_image.convert('RGB')
                    else:
                        pil_image = None
                except Exception:
                    pil_image = None
            else:
                pil_image = _poll_task_and_download(task_id, token, max_wait_seconds=config.get('timeout', 720))
            if pil_image is not None:
                img_np = np.array(pil_image).astype(np.float32) / 255.0
                img_tensor = torch.from_numpy(img_np)[None,]
                _save_image_and_meta("output", img_tensor, prompt, model, None, filename_override=filename)
                _update_batch_task_status(task_id, "done")
                done_count += 1
                print(f"✅ [恢复] ({idx+1}/{total}) {filename} 已保存", flush=True)
                _send_batch_progress(shot_id, title, idx + 1, total, "done")
            else:
                _send_batch_progress(shot_id, title, idx + 1, total, "error")
                print(f"❌ [恢复] ({idx+1}/{total}) task_id={task_id} 恢复失败", flush=True)
        _send_batch_progress("恢复", f"完成{done_count}/{total}", done_count, total, "finished")
        print(f"🔄 [恢复] 完成: {done_count}/{total}", flush=True)
    except Exception as e:
        print(f"❌ [恢复] 异常: {e}", flush=True)
        import traceback
        traceback.print_exc()
    finally:
        _BATCH_RECOVER["running"] = False


if _SERVER_OK:
    _batch_routes = PromptServer.instance.routes

    @_batch_routes.post("/qibo/batch_edit/cancel")
    async def _qibo_batch_edit_cancel(request):
        _BATCH_CANCEL["cancelled"] = True
        return web.json_response({"ok": True})

    @_batch_routes.get("/qibo/batch_edit/tasks")
    async def _qibo_batch_edit_tasks(request):
        data = _load_batch_tasks()
        pending = sum(1 for t in data["tasks"] if t.get("status") in ("pending", "succeed"))
        return web.json_response({"tasks": data["tasks"], "pending": pending})

    @_batch_routes.post("/qibo/batch_edit/recover")
    async def _qibo_batch_edit_recover(request):
        if _BATCH_RECOVER["running"]:
            return web.json_response({"ok": False, "error": "恢复任务正在运行中"})
        try:
            data = await request.json()
        except Exception:
            data = {}
        api_tokens_str = data.get("api_tokens", "")
        config = load_config()
        tokens = parse_api_tokens(api_tokens_str)
        if not tokens:
            return web.json_response({"ok": False, "error": "请提供至少一个有效的API Token"})
        thread = threading.Thread(target=_recover_batch_tasks, args=(tokens, config), daemon=True)
        thread.start()
        return web.json_response({"ok": True})

    @_batch_routes.post("/qibo/batch_edit/recover_cancel")
    async def _qibo_batch_edit_recover_cancel(request):
        _BATCH_RECOVER["cancel"] = True
        return web.json_response({"ok": True})

    @_batch_routes.post("/qibo/batch_edit/clear_tasks")
    async def _qibo_batch_edit_clear_tasks(request):
        _save_batch_tasks({"tasks": []})
        return web.json_response({"ok": True})


def _send_batch_progress(shot_id, title, current, total, status="generating"):
    if _SERVER_OK:
        try:
            PromptServer.instance.send_sync("qibo_batch_progress", {
                "shot_id": shot_id, "title": title,
                "current": current, "total": total, "status": status,
            })
        except Exception:
            pass


def _pils_to_batch(pils):
    """将 PIL 图片列表转为 4D tensor batch，统一到所有图中最大宽×最大高尺寸。"""
    if not pils:
        return torch.zeros((0, 64, 64, 3), dtype=torch.float32)
    max_w = max(p.size[0] for p in pils)
    max_h = max(p.size[1] for p in pils)
    tensors = []
    for p in pils:
        if p.size != (max_w, max_h):
            p = p.resize((max_w, max_h), Image.LANCZOS)
        tensors.append(torch.from_numpy(np.array(p).astype(np.float32) / 255.0))
    return torch.stack(tensors)


def tensor_to_base64_url(image_tensor):
    try:
        if len(image_tensor.shape) == 4:
            image_tensor = image_tensor.squeeze(0)

        if image_tensor.max() <= 1.0:
            image_np = (image_tensor.cpu().numpy() * 255).astype(np.uint8)
        else:
            image_np = image_tensor.cpu().numpy().astype(np.uint8)

        pil_image = Image.fromarray(image_np)
        buffer = BytesIO()
        pil_image.save(buffer, format='JPEG', quality=85)
        img_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

        return f"data:image/jpeg;base64,{img_base64}"
    except Exception as e:
        raise Exception(f"图像格式转换失败: {str(e)}")


# -------------------------- LoRA 预设管理节点 --------------------------
class ModelScopeLoraPresetNode:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(cls):
        config = load_config()
        lora_presets = config.get("lora_presets", [])
        preset_names = [preset.get("name", "无LoRA") for preset in lora_presets]

        return {
            "required": {
                "action": (["查看预设", "添加预设", "删除预设", "保存预设"], {"default": "查看预设"}),
            },
            "optional": {
                "preset_name": ("STRING", {"default": "自定义LoRA", "label": "预设名称"}),
                "lora_model_id": ("STRING", {"default": "", "label": "LoRA模型ID"}),
                "default_weight": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 2.0, "step": 0.1, "label": "默认权重"}),
                "target_preset": (preset_names, {"default": preset_names[0] if preset_names else "无LoRA", "label": "目标预设"}),
            }
        }

    RETURN_TYPES = ("STRING", "FLOAT", "STRING")
    RETURN_NAMES = ("lora_model_id", "lora_weight", "preset_info")
    FUNCTION = "manage_lora_presets"
    CATEGORY = "QIBO_API/LoRA"

    def manage_lora_presets(self, action, preset_name="", lora_model_id="", default_weight=0.8, target_preset=""):
        config = load_config()
        lora_presets = config.get("lora_presets", [])
        preset_info = f"当前共有 {len(lora_presets)} 个LoRA预设"

        if action == "查看预设":
            info_lines = ["=== LoRA预设列表 ==="]
            for i, preset in enumerate(lora_presets):
                info_lines.append(f"{i+1}. {preset.get('name')} | ID: {preset.get('model_id')} | 权重: {preset.get('weight')}")
            preset_info = "\n".join(info_lines)
            selected_preset = next((p for p in lora_presets if p.get("name") == target_preset), {"model_id": "", "weight": 0.8})
            return (selected_preset.get("model_id"), selected_preset.get("weight"), preset_info)

        elif action == "添加预设":
            if not preset_name or preset_name.strip() == "":
                raise Exception("预设名称不能为空")
            if any(p.get("name") == preset_name for p in lora_presets):
                raise Exception(f"已存在名为 {preset_name} 的预设")
            new_preset = {"name": preset_name.strip(), "model_id": lora_model_id.strip(), "weight": float(default_weight)}
            lora_presets.append(new_preset)
            config["lora_presets"] = lora_presets
            save_config(config)
            preset_info = f"成功添加预设: {preset_name} | ID: {lora_model_id}"
            return (lora_model_id, default_weight, preset_info)

        elif action == "删除预设":
            if target_preset == "无LoRA":
                raise Exception("不能删除默认的无LoRA预设")
            original_count = len(lora_presets)
            lora_presets = [p for p in lora_presets if p.get("name") != target_preset]
            if len(lora_presets) == original_count:
                raise Exception(f"未找到预设: {target_preset}")
            config["lora_presets"] = lora_presets
            save_config(config)
            preset_info = f"成功删除预设: {target_preset}"
            return ("", 0.8, preset_info)

        elif action == "保存预设":
            updated = False
            for i, preset in enumerate(lora_presets):
                if preset.get("name") == target_preset:
                    lora_presets[i]["model_id"] = lora_model_id.strip()
                    lora_presets[i]["weight"] = float(default_weight)
                    updated = True
                    break
            if not updated:
                raise Exception(f"未找到预设: {target_preset}")
            config["lora_presets"] = lora_presets
            save_config(config)
            preset_info = f"成功更新预设: {target_preset} | 新ID: {lora_model_id} | 新权重: {default_weight}"
            return (lora_model_id, default_weight, preset_info)

        return ("", 0.8, preset_info)


class ModelScopeSingleLoraLoaderNode:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(cls):
        config = load_config()
        lora_presets = config.get("lora_presets", [])
        preset_options = [preset.get("name", "无LoRA") for preset in lora_presets]

        return {
            "required": {
                "lora_preset": (preset_options, {"default": preset_options[0], "label": "LoRA预设"}),
            },
            "optional": {
                "lora_weight": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 2.0, "step": 0.1, "label": "自定义权重"}),
                "use_custom_weight": ("BOOLEAN", {"default": False, "label_on": "使用自定义权重", "label_off": "使用预设权重"}),
            }
        }

    RETURN_TYPES = ("STRING", "FLOAT")
    RETURN_NAMES = ("lora_id", "lora_weight")
    FUNCTION = "load_single_lora"
    CATEGORY = "QIBO_API/LoRA"

    def load_single_lora(self, lora_preset, lora_weight=0.8, use_custom_weight=False):
        config = load_config()
        lora_presets = config.get("lora_presets", [])
        selected_preset = next((p for p in lora_presets if p.get("name") == lora_preset), {"model_id": "", "weight": 0.8})
        lora_id = selected_preset.get("model_id", "")
        final_weight = lora_weight if use_custom_weight else selected_preset.get("weight", 0.8)
        return (lora_id, final_weight)


class ModelScopeMultiLoraLoaderNode:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(cls):
        config = load_config()
        lora_presets = config.get("lora_presets", [])
        preset_options = [preset.get("name", "无LoRA") for preset in lora_presets]

        return {
            "required": {
                "lora1_preset": (preset_options, {"default": preset_options[0], "label": "LoRA 1 预设"}),
                "lora2_preset": (preset_options, {"default": preset_options[0], "label": "LoRA 2 预设"}),
                "lora3_preset": (preset_options, {"default": preset_options[0], "label": "LoRA 3 预设"}),
            },
            "optional": {
                "lora1_weight": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 2.0, "step": 0.1, "label": "LoRA 1 权重"}),
                "lora2_weight": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 2.0, "step": 0.1, "label": "LoRA 2 权重"}),
                "lora3_weight": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 2.0, "step": 0.1, "label": "LoRA 3 权重"}),
                "lora1_use_custom": ("BOOLEAN", {"default": False, "label_on": "LoRA1用自定义权重", "label_off": "用预设权重"}),
                "lora2_use_custom": ("BOOLEAN", {"default": False, "label_on": "LoRA2用自定义权重", "label_off": "用预设权重"}),
                "lora3_use_custom": ("BOOLEAN", {"default": False, "label_on": "LoRA3用自定义权重", "label_off": "用预设权重"}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "FLOAT", "FLOAT", "FLOAT")
    RETURN_NAMES = ("lora1_id", "lora2_id", "lora3_id", "lora1_w", "lora2_w", "lora3_w")
    FUNCTION = "load_multi_lora"
    CATEGORY = "QIBO_API/LoRA"

    def load_multi_lora(self, lora1_preset, lora2_preset, lora3_preset,
                        lora1_weight=0.8, lora2_weight=0.8, lora3_weight=0.8,
                        lora1_use_custom=False, lora2_use_custom=False, lora3_use_custom=False):
        config = load_config()
        lora_presets = config.get("lora_presets", [])

        def get_lora_info(preset_name, custom_weight, use_custom):
            preset = next((p for p in lora_presets if p.get("name") == preset_name), {"model_id": "", "weight": 0.8})
            model_id = preset.get("model_id", "")
            final_weight = custom_weight if use_custom else preset.get("weight", 0.8)
            return model_id, final_weight

        lora1_id, lora1_w = get_lora_info(lora1_preset, lora1_weight, lora1_use_custom)
        lora2_id, lora2_w = get_lora_info(lora2_preset, lora2_weight, lora2_use_custom)
        lora3_id, lora3_w = get_lora_info(lora3_preset, lora3_weight, lora3_use_custom)
        return (lora1_id, lora2_id, lora3_id, lora1_w, lora2_w, lora3_w)


# -------------------------- 生图节点 --------------------------
class ModelScopeImageNode:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(cls):
        config = load_config()
        saved_tokens = load_api_tokens()

        return {
            "required": {
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": config.get("default_prompt", "A beautiful landscape")
                }),
                "api_tokens": ("STRING", {
                    "default": "***已保存{}个Token***".format(len(saved_tokens)) if saved_tokens else "",
                    "placeholder": "请输入API Token（支持多个，用逗号/换行分隔）" if not saved_tokens else "留空使用已保存的Token",
                    "multiline": True
                }),
            },
            "optional": {
                "model": (config.get("image_models", ["Qwen/Qwen-Image"]), {
                    "default": config.get("default_model", "Qwen/Qwen-Image")
                }),
                "negative_prompt": ("STRING", {
                    "multiline": True,
                    "default": config.get("default_negative_prompt", "")
                }),
                "width": ("INT", {"default": config.get("default_width", 512), "min": 64, "max": 2752, "step": 64}),
                "height": ("INT", {"default": config.get("default_height", 512), "min": 64, "max": 2752, "step": 64}),
                "seed": ("INT", {"default": config.get("default_seed", -1), "min": -1, "max": 2147483647}),
                "steps": ("INT", {"default": config.get("default_steps", 30), "min": 1, "max": 100}),
                "guidance": ("FLOAT", {"default": config.get("default_guidance", 7.5), "min": 1.5, "max": 20.0, "step": 0.1}),
                "lora1_id": ("STRING", {"default": "", "label": "LoRA1 模型ID"}),
                "lora1_w": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 2.0, "step": 0.1, "label": "LoRA1 权重"}),
                "lora2_id": ("STRING", {"default": "", "label": "LoRA2 模型ID"}),
                "lora2_w": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 2.0, "step": 0.1, "label": "LoRA2 权重"}),
                "lora3_id": ("STRING", {"default": "", "label": "LoRA3 模型ID"}),
                "lora3_w": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 2.0, "step": 0.1, "label": "LoRA3 权重"}),
                "simplified_params": ("BOOLEAN", {"default": False, "label_on": "简化参数(LoRA/社区模型)", "label_off": "完整参数"}),
            }
        }

    RETURN_TYPES = ("IMAGE", "QIBODATA")
    RETURN_NAMES = ("image", "qibodata")
    FUNCTION = "generate_image"
    CATEGORY = "QIBO_API"

    def generate_image(self, prompt, api_tokens, model="Qwen/Qwen-Image", negative_prompt="", width=512, height=512, seed=-1, steps=30, guidance=7.5,
                       lora1_id="", lora1_w=0.8, lora2_id="", lora2_w=0.8, lora3_id="", lora3_w=0.8, simplified_params=False):
        config = load_config()
        tokens = parse_api_tokens(api_tokens)

        if not tokens:
            raise Exception("请提供至少一个有效的API Token\n提示: 使用 ModelScope登录获取Token 节点自动获取Token")


        print(f"🔍 开始生成图像... 模型: {model} 尺寸: {width}x{height} 步数: {steps} 引导: {guidance}")
        prompt = _truncate_prompt(prompt)

        lora_dict = {}
        if lora1_id and lora1_id.strip(): lora_dict[lora1_id.strip()] = float(lora1_w)
        if lora2_id and lora2_id.strip(): lora_dict[lora2_id.strip()] = float(lora2_w)
        if lora3_id and lora3_id.strip(): lora_dict[lora3_id.strip()] = float(lora3_w)

        last_exception = None
        for i, token in enumerate(tokens):
            try:
                print(f"🔄 尝试使用第 {i+1}/{len(tokens)} 个Token...")

                url = get_api_endpoint('image_generation', 'submit_url')
                payload = {'model': model, 'prompt': prompt}
                if not simplified_params:
                    payload['size'] = f"{width}x{height}"
                    payload['steps'] = steps
                    payload['guidance'] = guidance

                if lora_dict:
                    payload['loras'] = lora_dict
                    first_lora_id = next(iter(lora_dict.keys()))
                    first_lora_w = next(iter(lora_dict.values()))
                    payload['lora'] = first_lora_id
                    payload['lora_weight'] = first_lora_w

                if negative_prompt.strip():
                    payload['negative_prompt'] = negative_prompt
                if seed != -1:
                    payload['seed'] = seed
                else:
                    import random
                    payload['seed'] = random.randint(0, 2147483647)

                headers = {
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json',
                    'X-ModelScope-Async-Mode': 'true',
                    'X-ModelScope-Task-Type': 'text-to-image-generation',
                    'X-ModelScope-Request-Params': json.dumps({'loras': lora_dict} if lora_dict else {})
                }

                submission_response = requests.post(url, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'), headers=headers, timeout=config.get("timeout", 60))

                if submission_response.status_code in (400, 422):
                    print(f"⚠️ 标准请求参数失败({submission_response.status_code})，尝试简化参数...")
                    minimal_payload = {'model': model, 'prompt': prompt}
                    if lora_dict:
                        minimal_payload['loras'] = lora_dict
                        minimal_payload['lora'] = first_lora_id
                        minimal_payload['lora_weight'] = first_lora_w
                    submission_response = requests.post(url, data=json.dumps(minimal_payload, ensure_ascii=False).encode('utf-8'), headers=headers, timeout=config.get("timeout", 60))

                if submission_response.status_code != 200:
                    raise Exception(f"API请求失败: {submission_response.status_code}, {submission_response.text}")

                submission_json = submission_response.json()
                image_url = None

                if 'task_id' in submission_json:
                    task_id = submission_json['task_id']
                    print(f"📌 获取任务ID: {task_id}, 开始轮询结果...")
                    poll_start = time.time()
                    max_wait_seconds = max(60, config.get('timeout', 720))
                    while True:
                        task_resp = requests.get(
                            get_api_endpoint('image_generation', 'task_query_url').replace('{task_id}', task_id),
                            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json', 'X-ModelScope-Task-Type': 'image_generation'},
                            timeout=config.get("image_download_timeout", 120)
                        )
                        if task_resp.status_code != 200:
                            raise Exception(f"任务查询失败: {task_resp.status_code}, {task_resp.text}")
                        task_data = task_resp.json()
                        status = task_data.get('task_status')
                        print(f"⌛ 任务状态: {status} (已等待 {int(time.time() - poll_start)} 秒)")
                        if status == 'SUCCEED':
                            output_images = task_data.get('output_images') or []
                            if not output_images:
                                raise Exception("任务成功但未返回图片URL")
                            image_url = output_images[0]
                            break
                        if status == 'FAILED':
                            raise Exception(f"任务失败: {task_data}")
                        if time.time() - poll_start > max_wait_seconds:
                            raise Exception(f"任务轮询超时 ({max_wait_seconds}秒)")
                        time.sleep(5)
                elif 'images' in submission_json and len(submission_json['images']) > 0:
                    image_url = submission_json['images'][0]['url']
                else:
                    raise Exception(f"未识别的API返回格式: {submission_json}")

                print(f"📥 下载图片...")
                img_response = requests.get(image_url, timeout=config.get("image_download_timeout", 30))
                if img_response.status_code != 200:
                    raise Exception(f"图片下载失败: {img_response.status_code}")

                pil_image = Image.open(BytesIO(img_response.content))
                if pil_image.mode == 'RGBA':
                    pass
                elif pil_image.mode == 'LA':
                    pil_image = pil_image.convert('RGBA')
                elif pil_image.mode == 'P' and 'transparency' in pil_image.info:
                    pil_image = pil_image.convert('RGBA')
                elif pil_image.mode != 'RGB':
                    pil_image = pil_image.convert('RGB')
                image_np = np.array(pil_image).astype(np.float32) / 255.0
                image_tensor = torch.from_numpy(image_np)[None,]

                print(f"✅ 第 {i+1} 个Token调用成功，图像生成完成!")
                save_tokens_on_success(api_tokens)
                qibodata = {"image": image_tensor, "prompt": prompt, "model": model, "ref_images": None}
                return (image_tensor, qibodata)

            except Exception as e:
                last_exception = e
                print(f"❌ 第 {i+1} 个Token调用失败: {str(e)}")
                if i < len(tokens) - 1:
                    continue
                else:
                    break

        raise Exception(f"所有 {len(tokens)} 个API Token都失败了。最后的错误: {str(last_exception)}")


# -------------------------- 图像编辑节点 --------------------------
class ModelScopeImageEditNode:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(cls):
        config = load_config()
        saved_tokens = load_api_tokens()
        edit_models = config.get("image_edit_models", ["Qwen/Qwen-Image-Edit"])
        gen_models = config.get("image_models", ["Qwen/Qwen-Image"])

        return {
            "required": {
                "image": ("IMAGE",),
                "prompt": ("STRING", {"multiline": True, "default": "修改图片中的内容"}),
                "api_tokens": ("STRING", {
                    "default": "***已保存{}个Token***".format(len(saved_tokens)) if saved_tokens else "",
                    "placeholder": "请输入API Token（支持多个，用逗号/换行分隔）" if not saved_tokens else "留空使用已保存的Token",
                    "multiline": True
                }),
                "image_gen_mode": ("BOOLEAN", {"default": False, "label_on": "图生图模式", "label_off": "图像编辑模式"}),
            },
            "optional": {

                "image2": ("IMAGE",),
                "image3": ("IMAGE",),
                "image4": ("IMAGE",),
                "image_5": ("IMAGE",),
                "image_6": ("IMAGE",),
                "image_7": ("IMAGE",),
                "image_8": ("IMAGE",),
                "image_9": ("IMAGE",),
                "image_10": ("IMAGE",),
                "gen_model": (gen_models, {"default": gen_models[0] if gen_models else "Qwen/Qwen-Image"}),
                "edit_model": (edit_models, {"default": edit_models[0] if edit_models else "Qwen/Qwen-Image-Edit"}),
                "negative_prompt": ("STRING", {"multiline": True, "default": ""}),
                "width": ("INT", {"default": 512, "min": 64, "max": 2752, "step": 8}),
                "height": ("INT", {"default": 512, "min": 64, "max": 2752, "step": 8}),
                "steps": ("INT", {"default": 30, "min": 1, "max": 100, "step": 1}),
                "guidance": ("FLOAT", {"default": 3.5, "min": 1.5, "max": 20.0, "step": 0.1}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 2147483647}),
                "lora1_id": ("STRING", {"default": "", "label": "LoRA1 模型ID"}),
                "lora1_w": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 2.0, "step": 0.1, "label": "LoRA1 权重"}),
                "lora2_id": ("STRING", {"default": "", "label": "LoRA2 模型ID"}),
                "lora2_w": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 2.0, "step": 0.1, "label": "LoRA2 权重"}),
                "lora3_id": ("STRING", {"default": "", "label": "LoRA3 模型ID"}),
                "lora3_w": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 2.0, "step": 0.1, "label": "LoRA3 权重"}),
            }
        }

    RETURN_TYPES = ("IMAGE", "QIBODATA")
    RETURN_NAMES = ("image", "qibodata")
    FUNCTION = "edit_image"
    CATEGORY = "QIBO_API"

    def edit_image(self, image, prompt, api_tokens, image_gen_mode=False, gen_model="Qwen/Qwen-Image",
                   edit_model="Qwen/Qwen-Image-Edit", negative_prompt="",
                   width=512, height=512, steps=30, guidance=3.5, seed=-1,
                   lora1_id="", lora1_w=0.8, lora2_id="", lora2_w=0.8, lora3_id="", lora3_w=0.8,
                   image2=None, image3=None, image4=None,
                   image_5=None, image_6=None, image_7=None, image_8=None, image_9=None, image_10=None):
        config = load_config()
        tokens = parse_api_tokens(api_tokens)

        if not tokens:
            raise Exception("请提供至少一个有效的API Token\n提示: 使用 ModelScope登录获取Token 节点自动获取Token")
        prompt = _truncate_prompt(prompt)


        model = gen_model if image_gen_mode else edit_model
        mode = "图生图模式" if image_gen_mode else "图像编辑模式"
        print(f"🔍 开始图像编辑... 模型: {model} ({mode})")

        lora_dict = {}
        if lora1_id and lora1_id.strip(): lora_dict[lora1_id.strip()] = float(lora1_w)
        if lora2_id and lora2_id.strip(): lora_dict[lora2_id.strip()] = float(lora2_w)
        if lora3_id and lora3_id.strip(): lora_dict[lora3_id.strip()] = float(lora3_w)

        all_ports = [(1, image), (2, image2), (3, image3), (4, image4),
                     (5, image_5), (6, image_6), (7, image_7),
                     (8, image_8), (9, image_9), (10, image_10)]
        images_list = []
        port_nums = []
        for port_num, img in all_ports:
            if img is not None:
                images_list.append(img)
                port_nums.append(port_num)

        last_exception = None
        for i, token in enumerate(tokens):
            try:
                print(f"🔄 尝试使用第 {i+1}/{len(tokens)} 个Token...")

                temp_img_paths = []
                compressed_pils = []
                print(f"🖼️ 共输入 {len(images_list)} 张图片")

                image_urls = []

                for idx, img_tensor in enumerate(images_list):
                    try:
                        if len(img_tensor.shape) == 4:
                            img = img_tensor[0]
                        else:
                            img = img_tensor
                        img_np = 255. * img.cpu().numpy()
                        img_pil = Image.fromarray(np.clip(img_np, 0, 255).astype(np.uint8))

                        repo_url, prepared_pil = upload_pil_image(img_pil, token)
                        if repo_url:
                            image_urls.append(repo_url)
                            w, h = prepared_pil.size
                            print(f"📤 第 {idx+1} 张图像已上传仓库 ({w}x{h})")
                        else:
                            buffer = BytesIO()
                            prepared_pil.save(buffer, format='JPEG', quality=85)
                            b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
                            image_urls.append(f"data:image/jpeg;base64,{b64}")
                            print(f"↩️ 第 {idx+1} 张仓库上传失败，回退 base64 ({len(b64)//1024}KB)")
                        compressed_pils.append(prepared_pil)
                    except Exception as e:
                        print(f"⚠️ 第 {idx+1} 张图像转换失败: {str(e)}")

                if image_urls:
                    prompt, image_urls, ref_ports = _resolve_image_refs(prompt, image_urls, port_nums)
                    if ref_ports:
                        print(f"📎 prompt 引用端口 {sorted(ref_ports)}→重映射为图1至图{len(image_urls)}，仅传 {len(image_urls)} 张", flush=True)
                        print(f"   重映射后 prompt: {prompt[:120]}", flush=True)

                    if len(image_urls) == 1:
                        payload = {'model': model, 'prompt': prompt, 'image_url': image_urls}
                    else:
                        payload = {'model': model, 'prompt': prompt, 'image_url': image_urls}
                        print(f"📦 多图编辑模式，已传入 {len(image_urls)} 张图片(仓库URL)")
                else:
                    if len(images_list) == 1:
                        image_data = tensor_to_repo_url(images_list[0], token)
                        payload = {'model': model, 'prompt': prompt, 'image_url': [image_data]}
                    else:
                        image_data_list = [tensor_to_repo_url(img, token) for img in images_list]
                        payload = {'model': model, 'prompt': prompt, 'image_url': image_data_list}
                        print(f"📦 多图编辑模式(仓库URL)，已传入 {len(image_data_list)} 张图片")

                if lora_dict:
                    payload['loras'] = lora_dict
                    first_lora_id = next(iter(lora_dict.keys()))
                    first_lora_w = next(iter(lora_dict.values()))
                    payload['lora'] = first_lora_id
                    payload['lora_weight'] = first_lora_w

                if negative_prompt.strip():
                    payload['negative_prompt'] = negative_prompt
                if width != 512 or height != 512:
                    payload['size'] = f"{width}x{height}"
                if steps != 30:
                    payload['steps'] = steps
                if guidance != 3.5:
                    payload['guidance'] = guidance
                if seed != -1:
                    payload['seed'] = seed
                else:
                    import random
                    payload['seed'] = random.randint(0, 2147483647)

                headers = {
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json',
                    'X-ModelScope-Async-Mode': 'true',
                    'X-ModelScope-Task-Type': 'image-to-image-generation',
                    'X-ModelScope-Request-Params': json.dumps({'loras': lora_dict} if lora_dict else {})
                }

                url = get_api_endpoint('image_edit', 'submit_url')
                submission_response = requests.post(url, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'), headers=headers, timeout=config.get("timeout", 60))

                if submission_response.status_code != 200:
                    raise Exception(f"API请求失败: {submission_response.status_code}, {submission_response.text}")

                submission_json = submission_response.json()
                result_image_url = None

                if 'task_id' in submission_json:
                    task_id = submission_json['task_id']
                    print(f"📌 获取任务ID: {task_id}, 开始轮询结果...")
                    poll_start = time.time()
                    max_wait_seconds = max(60, config.get('timeout', 720))

                    while True:
                        task_resp = requests.get(
                            get_api_endpoint('image_edit', 'task_query_url').replace('{task_id}', task_id),
                            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json', 'X-ModelScope-Task-Type': 'image_generation'},
                            timeout=config.get("image_download_timeout", 120)
                        )
                        if task_resp.status_code != 200:
                            raise Exception(f"任务查询失败: {task_resp.status_code}, {task_resp.text}")
                        task_data = task_resp.json()
                        status = task_data.get('task_status')
                        print(f"⌛ 任务状态: {status} (已等待 {int(time.time() - poll_start)} 秒)")
                        if status == 'SUCCEED':
                            output_images = task_data.get('output_images') or []
                            if not output_images:
                                raise Exception("任务成功但未返回图片URL")
                            result_image_url = output_images[0]
                            break
                        if status == 'FAILED':
                            error_message = task_data.get('errors', {}).get('message', '未知错误')
                            raise Exception(f"任务失败: {error_message}")
                        if time.time() - poll_start > max_wait_seconds:
                            raise Exception(f"任务轮询超时 ({max_wait_seconds}秒)")
                        time.sleep(5)
                else:
                    raise Exception(f"未识别的API返回格式: {submission_json}")

                print(f"📥 下载编辑后的图片...")
                img_response = requests.get(result_image_url, timeout=config.get("image_download_timeout", 30))
                if img_response.status_code != 200:
                    raise Exception(f"图片下载失败: {img_response.status_code}")

                pil_image = Image.open(BytesIO(img_response.content))
                if pil_image.mode == 'RGBA':
                    pass
                elif pil_image.mode == 'LA':
                    pil_image = pil_image.convert('RGBA')
                elif pil_image.mode == 'P' and 'transparency' in pil_image.info:
                    pil_image = pil_image.convert('RGBA')
                elif pil_image.mode != 'RGB':
                    pil_image = pil_image.convert('RGB')
                image_np = np.array(pil_image).astype(np.float32) / 255.0
                image_tensor = torch.from_numpy(image_np)[None,]

                for tmp_path in temp_img_paths:
                    if os.path.exists(tmp_path):
                        try: os.remove(tmp_path)
                        except: pass

                print(f"✅ 第 {i+1} 个Token调用成功，图像编辑完成!")
                save_tokens_on_success(api_tokens)
                ref_tensor = _pils_to_batch(compressed_pils)
                qibodata = {"image": image_tensor, "prompt": prompt, "model": model, "ref_images": ref_tensor}
                return (image_tensor, qibodata)

            except Exception as e:
                last_exception = e
                print(f"❌ 第 {i+1} 个Token调用失败: {str(e)}")
                for tmp_path in temp_img_paths:
                    if os.path.exists(tmp_path):
                        try: os.remove(tmp_path)
                        except: pass
                if i < len(tokens) - 1:
                    continue
                else:
                    break

        raise Exception(f"所有 {len(tokens)} 个API Token都失败了。最后的错误: {str(last_exception)}")


_BATCH_ASPECT_RATIOS = {
    "1:1":  (2048, 2048),
    "4:3":  (2400, 1792),
    "3:4":  (1792, 2400),
    "3:2":  (2528, 1696),
    "2:3":  (1696, 2528),
    "16:9": (2752, 1536),
    "9:16": (1536, 2752),
}

_BATCH_RATIO_PAIRS = {
    "1:1":  (1, 1),
    "4:3":  (4, 3),
    "3:4":  (3, 4),
    "3:2":  (3, 2),
    "2:3":  (2, 3),
    "16:9": (16, 9),
    "9:16": (9, 16),
}


def _align8(v):
    return max(8, round(v / 8) * 8)


def _resolve_aspect_size(aspect_ratio, base_size):
    if base_size and base_size > 0:
        rw, rh = _BATCH_RATIO_PAIRS.get(aspect_ratio, (1, 1))
        if rw >= rh:
            w = base_size
            h = _align8(base_size * rh / rw)
        else:
            h = base_size
            w = _align8(base_size * rw / rh)
        return w, h
    return _BATCH_ASPECT_RATIOS.get(aspect_ratio, (2048, 2048))


class QIBOBatchImageEditNode:
    """批量图像编辑节点：接收 IMAGE batch 作为多参考图，prompt 按图1/图2引用，输出批量结果。
    prompt 输入检测到 JSON 分镜结构时循环 shots 逐条生成，否则按单条 prompt 生成。"""

    @classmethod
    def INPUT_TYPES(cls):
        config = load_config()
        saved_tokens = load_api_tokens()
        edit_models = config.get("image_edit_models", ["Qwen/Qwen-Image-Edit"])
        ratio_keys = list(_BATCH_ASPECT_RATIOS.keys())
        return {
            "required": {
                "images": ("IMAGE",),
                "prompt": ("STRING", {"default": "", "multiline": True,
                                       "tooltip": "普通提示词直接生成；粘贴 JSON 分镜文本或 .json 文件路径（含 shots 数组）时循环逐条生成"}),
                "api_tokens": ("STRING", {
                    "default": "***已保存{}个Token***".format(len(saved_tokens)) if saved_tokens else "",
                    "placeholder": "请输入API Token（支持多个，用逗号/换行分隔）" if not saved_tokens else "留空使用已保存的Token",
                    "multiline": True
                }),
            },
            "optional": {
                "negative_prompt": ("STRING", {"default": "", "multiline": True}),
                "edit_model": (edit_models, {"default": edit_models[0] if edit_models else "Qwen/Qwen-Image-Edit"}),
                "aspect_ratio": (ratio_keys, {"default": ratio_keys[0]}),
                "base_size": ("INT", {"default": 1024, "min": 0, "max": 4096, "step": 8,
                                       "tooltip": "0=使用预设最佳分辨率；>0=以该值为长边按比例计算"}),
                "steps": ("INT", {"default": 30, "min": 1, "max": 100}),
                "guidance": ("FLOAT", {"default": 3.5, "min": 0.1, "max": 20.0, "step": 0.1}),
                "seed": ("INT", {"default": -1}),
            }
        }

    RETURN_TYPES = ("IMAGE", "QIBODATA")
    RETURN_NAMES = ("images", "qibodata")
    FUNCTION = "batch_edit"
    CATEGORY = "QIBO_API"

    @staticmethod
    def _parse_prompt_as_json(prompt):
        """尝试把 prompt 解析为 JSON 分镜结构，失败则返回 None。"""
        if not prompt or not prompt.strip():
            return None
        text = prompt.strip()
        if os.path.isfile(text) and text.lower().endswith(".json"):
            with open(text, "r", encoding="utf-8") as f:
                spec = json.load(f)
        else:
            try:
                spec = json.loads(text)
            except Exception:
                return None
        if isinstance(spec, dict) and "shots" in spec:
            return spec
        return None

    def _upload_images(self, images_list, token=None):
        """将图片列表上传到 ModelScope 仓库获取公开 URL，返回 (image_urls, compressed_pils, temp_img_paths)。
        失败的项回退 base64，全失败用 None 占位。"""
        if not token:
            tokens = load_api_tokens()
            token = tokens[0] if tokens else ""
        return upload_images_to_repo(images_list, token)

    def _submit_task(self, prompt_text, negative_text,
                     edit_model, width, height, steps, guidance, seed,
                     token, cached_upload, task_meta=None):
        """提交单张生图任务到 ModelScope API，记录 task_id 落盘，不轮询。
        返回 (task_id, image_urls, seed_used) 或 None。

        约定：cached_upload = (image_urls, pils) 中的 url 与 pil 必须一一对应且均非空，
        由调用方（_batch_from_json / _generate_one）保证。
        """
        if not cached_upload or not cached_upload[0]:
            print(f"❌ [{task_meta.get('shot_id','') if task_meta else ''}] cached_upload 为空，无法提交", flush=True)
            return None

        image_urls = list(cached_upload[0] or [])
        pils = list(cached_upload[1] or []) if len(cached_upload) > 1 else []

        # 防御性断言：url 与 pil 必须数量一致，否则图号会错位
        if not image_urls or len(image_urls) != len(pils):
            sid = task_meta.get('shot_id', '') if task_meta else ''
            print(f"❌ [{sid}] 参考图 url/pil 数量不一致 ({len(image_urls)} vs {len(pils)})，跳过提交", flush=True)
            return None

        sid = task_meta.get('shot_id', '') if task_meta else ''

        if len(image_urls) > 4:
            valid_pils = pils  # 已保证一一对应
            orig_count = len(image_urls)
            # 仅使用 2x3 或 3x3 网格：5-6 张→2x3，7-9 张→3x3，>9 张截断到前 9 张按 3x3
            if orig_count <= 6:
                grid_rows, grid_cols = 2, 3
            else:
                grid_rows, grid_cols = 3, 3
            max_cells = grid_rows * grid_cols
            if orig_count > max_cells:
                valid_pils = valid_pils[:max_cells]
                orig_count = max_cells
                print(f"  ✂️ 参考图超过 {max_cells} 张，截断到前 {max_cells} 张按 {grid_rows}x{grid_cols} 拼接", flush=True)
            cell_w = min(p.size[0] for p in valid_pils)
            cell_h = min(p.size[1] for p in valid_pils)
            grid_imgs = [p.resize((cell_w, cell_h), Image.LANCZOS) for p in valid_pils]
            gap = max(cell_w, cell_h) // 20
            grid_total_w = grid_cols * cell_w + (grid_cols + 1) * gap
            grid_total_h = grid_rows * cell_h + (grid_rows + 1) * gap
            concat_img = Image.new('RGB', (grid_total_w, grid_total_h), (255, 255, 255))
            for idx, p in enumerate(grid_imgs):
                r = idx // grid_cols
                c = idx % grid_cols
                concat_img.paste(p, (gap + c * (cell_w + gap), gap + r * (cell_h + gap)))
            cw, ch = concat_img.size
            if max(cw, ch) > 2048:
                ratio = 2048 / max(cw, ch)
                concat_img = concat_img.resize((int(cw * ratio), int(ch * ratio)), Image.LANCZOS)
                print(f"  📐 网格图 {cw}x{ch} 超限，缩放至 {concat_img.size[0]}x{concat_img.size[1]}", flush=True)
            concat_ok = False
            try:
                concat_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "qibo_concat")
                os.makedirs(concat_dir, exist_ok=True)
                concat_local_name = f"concat_{int(time.time()*1000)}_{grid_rows}x{grid_cols}_{orig_count}.jpg"
                concat_local_path = os.path.join(concat_dir, concat_local_name)
                concat_img.save(concat_local_path, format="JPEG", quality=90)
                print(f"  💾 拼接图已保存本地: {concat_local_path}", flush=True)
                concat_url, is_repo = pil_to_repo_url_or_base64(concat_img, token)
                pos_descs = []
                for i in range(orig_count):
                    r = i // grid_cols + 1
                    c = i % grid_cols + 1
                    pos_descs.append(f"第{r}行第{c}列为第{i+1}格")
                concat_note = f"参考图1是角色参考合成图（{grid_rows}行{grid_cols}列网格，{'，'.join(pos_descs)}，第N格即角色N）。请提取描述中提到的角色的外貌、服饰、表情特征，生成一张所有被提到角色在同一场景中自然互动的完整连贯画面，不要保留网格边框和白色间隔。"
                new_prompt = prompt_text
                for orig_idx in range(orig_count, 0, -1):
                    new_prompt = new_prompt.replace(f"图{orig_idx}", f"角色{orig_idx}")
                prompt_text = concat_note + new_prompt
                image_urls = [concat_url]
                concat_ok = True
                src_label = "仓库URL" if is_repo else "base64"
                print(f"🔗 [{sid}] 参考图 {orig_count} 张超上限，已以{grid_rows}x{grid_cols}网格拼接为1张 {src_label}，API提交 1 张", flush=True)
            except Exception as e:
                print(f"⚠️ 网格图拼接异常: {e}，回退截取前4张", flush=True)
            if not concat_ok:
                image_urls = image_urls[:4]
        else:
            if len(image_urls) > 1:
                prompt_text = f"以下图1至图{len(image_urls)}为角色参考图，请提取各角色的外貌、服饰、表情特征用于生成新画面，不要直接复制参考图。{prompt_text}"

        payload = {'model': edit_model, 'prompt': _truncate_prompt(prompt_text)}
        payload['image_url'] = image_urls
        if negative_text.strip():
            payload['negative_prompt'] = negative_text
        if width != 512 or height != 512:
            payload['size'] = f"{width}x{height}"
        if steps != 30:
            payload['steps'] = steps
        if guidance != 3.5:
            payload['guidance'] = guidance
        if seed != -1:
            payload['seed'] = seed
        else:
            import random
            payload['seed'] = random.randint(0, 2147483647)
        seed_used = payload['seed']

        common_headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        }
        headers = {
            **common_headers,
            'X-ModelScope-Async-Mode': 'true',
            'X-ModelScope-Task-Type': 'image-to-image-generation',
        }
        url = get_api_endpoint('image_edit', 'submit_url')
        n_imgs = len(image_urls)
        print(f"📡 提交API: {n_imgs} 张参考图, prompt={prompt_text}", flush=True)
        print(f"📦 发送给大模型的完整数据:\n{json.dumps(payload, ensure_ascii=False, indent=2)}", flush=True)
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=60)
            if resp.status_code != 200:
                print(f"❌ API提交失败: status={resp.status_code}, resp={resp.text[:500]}", flush=True)
                return None
            resp_json = resp.json()
            print(f"📋 API返回: {json.dumps(resp_json, ensure_ascii=False)[:300]}", flush=True)
            if 'task_id' not in resp_json:
                print(f"❌ 未识别的API返回(无task_id): {resp_json}", flush=True)
                return None
            task_id = resp_json['task_id']
            print(f"📨 task_id={task_id} 已提交并落盘", flush=True)
            if task_meta:
                _record_batch_task(
                    task_id,
                    shot_id=task_meta.get("shot_id", ""),
                    title=task_meta.get("title", ""),
                    filename=task_meta.get("filename", ""),
                    prompt=prompt_text,
                    negative_prompt=negative_text,
                    model=edit_model,
                    image_urls=image_urls,
                    seed=seed_used,
                    status="pending",
                )
            return (task_id, image_urls, seed_used)
        except Exception as e:
            print(f"❌ 提交异常: {e}", flush=True)
            return None

    def _poll_and_download(self, task_id, token, config, progress_ctx=None, task_meta=None):
        """轮询 task_id 并下载结果图片，返回 PIL Image 或 None。"""
        common_headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        }
        poll_headers = {**common_headers, 'X-ModelScope-Task-Type': 'image_generation'}
        poll_start = time.time()
        max_wait_seconds = max(60, (config or {}).get('timeout', 720))
        poll_interval = 2
        poll_count = 0
        consecutive_errors = 0
        while True:
            if _BATCH_CANCEL["cancelled"]:
                return None, "cancelled"
            try:
                task_resp = requests.get(
                    get_api_endpoint('image_edit', 'task_query_url').replace('{task_id}', task_id),
                    headers=poll_headers, timeout=30
                )
                if task_resp.status_code != 200:
                    consecutive_errors += 1
                    print(f"⚠️ task_id={task_id} 查询失败: {task_resp.status_code} (连续{consecutive_errors}次)", flush=True)
                    if consecutive_errors >= 5:
                        print(f"❌ task_id={task_id} 连续5次查询失败，放弃", flush=True)
                        return None, "poll_error"
                    time.sleep(poll_interval)
                    continue
                task_data = task_resp.json()
                consecutive_errors = 0
            except Exception as e:
                consecutive_errors += 1
                print(f"⚠️ task_id={task_id} 轮询异常: {e} (连续{consecutive_errors}次)", flush=True)
                if consecutive_errors >= 5:
                    print(f"❌ task_id={task_id} 连续5次异常，放弃", flush=True)
                    return None, "poll_error"
                time.sleep(poll_interval)
                continue
            status = task_data.get('task_status', '')
            elapsed = int(time.time() - poll_start)
            poll_count += 1
            if status == 'SUCCEED':
                output_images = task_data.get('output_images') or []
                if not output_images:
                    print(f"❌ task_id={task_id} 成功但无图片URL", flush=True)
                    return None, "no_image"
                result_image_url = output_images[0]
                if task_meta:
                    _update_batch_task_status(task_id, "succeed", result_url=result_image_url)
                print(f"✅ task_id={task_id} 完成, 耗时 {elapsed}s", flush=True)
                try:
                    img_resp = requests.get(result_image_url, timeout=30)
                    if img_resp.status_code != 200:
                        return None, "download_fail"
                    pil_image = Image.open(BytesIO(img_resp.content))
                    if pil_image.mode != 'RGB':
                        pil_image = pil_image.convert('RGB')
                    return pil_image, "ok"
                except Exception as e:
                    print(f"❌ task_id={task_id} 下载失败: {e}", flush=True)
                    return None, "download_fail"
            if status == 'FAILED':
                err_msg = (task_data.get('errors') or {}).get('message', '') or task_data.get('message', '')
                reason = "task_not_found" if "task not found" in str(err_msg).lower() else "failed"
                if task_meta:
                    _update_batch_task_status(task_id, "failed")
                print(f"❌ task_id={task_id} 任务失败({reason}), 完整返回: {json.dumps(task_data, ensure_ascii=False)[:500]}", flush=True)
                return None, reason
            if elapsed > max_wait_seconds:
                print(f"❌ task_id={task_id} 轮询超时 ({max_wait_seconds}s)", flush=True)
                return None, "timeout"
            if progress_ctx:
                _send_batch_progress(
                    progress_ctx.get("shot_id", ""),
                    f"轮询({status},{elapsed}s)",
                    progress_ctx.get("current", 1),
                    progress_ctx.get("total", 1),
                    "generating"
                )
            if poll_count % 3 == 1:
                print(f"⏳ task_id={task_id} 第{poll_count}次 状态={status} {elapsed}s/{max_wait_seconds}s", flush=True)
            time.sleep(poll_interval)

    def _generate_one(self, images_list, prompt_text, negative_text,
                      edit_model, width, height, steps, guidance, seed,
                      tokens, config, cached_upload=None, progress_ctx=None, task_meta=None,
                      port_nums=None):
        last_exception = None
        for i, token in enumerate(tokens):
            try:
                temp_img_paths = []
                if cached_upload is not None:
                    # url/pil 成对保留，避免索引错位
                    pairs = [(u, p) for u, p in zip(cached_upload[0], cached_upload[1])
                             if u and p is not None]
                    image_urls = [u for u, _ in pairs]
                    compressed_pils = [p for _, p in pairs]
                else:
                    raw_urls, raw_pils, temp_img_paths = self._upload_images(images_list, token)
                    # 上传失败项直接丢弃，同步记录其原始端口号，保证 _resolve_image_refs 对齐
                    upload_port_nums = port_nums if port_nums else list(range(1, len(images_list) + 1))
                    triples = [(pn, u, p) for pn, u, p in zip(upload_port_nums, raw_urls, raw_pils)
                               if u and p is not None]
                    filtered_ports = [pn for pn, _, _ in triples]
                    image_urls = [u for _, u, _ in triples]
                    compressed_pils = [p for _, _, p in triples]

                    if not image_urls:
                        raise Exception("所有图片上传失败")

                    # 用过滤后的端口号重新解析，避免图号错位
                    prompt_text, image_urls, ref_ports = _resolve_image_refs(
                        prompt_text, image_urls, filtered_ports)
                    if ref_ports:
                        print(f"📎 prompt 引用端口 {sorted(ref_ports)}→重映射为图1至图{len(image_urls)}，仅传 {len(image_urls)} 张", flush=True)

                    # _resolve_image_refs 可能进一步筛选，pils 需要同步裁剪
                    if len(image_urls) != len(compressed_pils):
                        # 以 url 为参照重建 pils（filtered_ports 顺序与 image_urls 一致）
                        keep_idx = []
                        used = set()
                        url_to_pos = {}
                        for pos, u in enumerate([u for _, u, _ in triples]):
                            url_to_pos.setdefault(u, []).append(pos)
                        for u in image_urls:
                            for pos in url_to_pos.get(u, []):
                                if pos not in used:
                                    used.add(pos)
                                    keep_idx.append(pos)
                                    break
                        if len(keep_idx) == len(image_urls):
                            compressed_pils = [[p for _, _, p in triples][k] for k in keep_idx]

                if not image_urls:
                    raise Exception("所有图片上传失败")

                prompt_text = _truncate_prompt(prompt_text)
                payload = {'model': edit_model, 'prompt': prompt_text}
                payload['image_url'] = image_urls

                n_imgs = len(image_urls) if isinstance(image_urls, list) else 1
                print(f"📦 提交API: {n_imgs} 张参考图, prompt={prompt_text[:80]}...", flush=True)

                if negative_text.strip():
                    payload['negative_prompt'] = negative_text
                if width != 512 or height != 512:
                    payload['size'] = f"{width}x{height}"
                if steps != 30:
                    payload['steps'] = steps
                if guidance != 3.5:
                    payload['guidance'] = guidance
                if seed != -1:
                    payload['seed'] = seed
                else:
                    import random
                    payload['seed'] = random.randint(0, 2147483647)

                common_headers = {
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json',
                }
                headers = {
                    **common_headers,
                    'X-ModelScope-Async-Mode': 'true',
                    'X-ModelScope-Task-Type': 'image-to-image-generation',
                }
                url = get_api_endpoint('image_edit', 'submit_url')
                print(f"📡 正在提交API请求 (异步模式)...", flush=True)
                submission_response = requests.post(url, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'), headers=headers, timeout=60)
                if submission_response.status_code != 200:
                    raise Exception(f"API请求失败: {submission_response.status_code}, {submission_response.text}")

                submission_json = submission_response.json()
                print(f"📋 API返回: {json.dumps(submission_json, ensure_ascii=False)[:300]}", flush=True)
                if 'task_id' not in submission_json:
                    raise Exception(f"未识别的API返回格式: {submission_json}")

                task_id = submission_json['task_id']
                print(f"📨 任务已提交 task_id={task_id}, 开始轮询...", flush=True)
                if task_meta:
                    _record_batch_task(
                        task_id,
                        shot_id=task_meta.get("shot_id", ""),
                        title=task_meta.get("title", ""),
                        filename=task_meta.get("filename", ""),
                        prompt=prompt_text,
                        negative_prompt=negative_text,
                        model=edit_model,
                        image_urls=image_urls if isinstance(image_urls, list) else [image_urls],
                        seed=payload.get("seed"),
                        status="pending",
                    )
                poll_start = time.time()
                max_wait_seconds = max(60, config.get('timeout', 720))
                poll_interval = 2
                result_image_url = None
                poll_count = 0
                poll_headers = {**common_headers, 'X-ModelScope-Task-Type': 'image_generation'}
                while True:
                    if _BATCH_CANCEL["cancelled"]:
                        raise Exception("用户取消")
                    task_resp = requests.get(
                        get_api_endpoint('image_edit', 'task_query_url').replace('{task_id}', task_id),
                        headers=poll_headers,
                        timeout=30
                    )
                    if task_resp.status_code != 200:
                        raise Exception(f"任务查询失败: {task_resp.status_code}, {task_resp.text}")
                    task_data = task_resp.json()
                    status = task_data.get('task_status', '')
                    elapsed = int(time.time() - poll_start)
                    poll_count += 1
                    if status == 'SUCCEED':
                        output_images = task_data.get('output_images') or []
                        if not output_images:
                            raise Exception(f"任务成功但未返回图片URL, 完整返回: {task_data}")
                        result_image_url = output_images[0]
                        if task_meta:
                            _update_batch_task_status(task_id, "succeed", result_url=result_image_url)
                        print(f"✅ 任务完成, 耗时 {elapsed}s", flush=True)
                        break
                    if status == 'FAILED':
                        raise Exception(f"任务失败: {task_data.get('errors', {}).get('message', '未知错误')}, 完整返回: {task_data}")
                    if elapsed > max_wait_seconds:
                        raise Exception(f"任务轮询超时 ({max_wait_seconds}秒), 最后状态: {status}")
                    if progress_ctx:
                        _send_batch_progress(
                            progress_ctx.get("shot_id", ""),
                            f"API轮询中({status},{elapsed}s/{max_wait_seconds}s)",
                            progress_ctx.get("current", 1),
                            progress_ctx.get("total", 1),
                            "generating"
                        )
                    if poll_count % 3 == 1:
                        print(f"⏳ 轮询第{poll_count}次 状态={status} 已等待{elapsed}s/{max_wait_seconds}s", flush=True)
                    time.sleep(poll_interval)

                print(f"📥 正在下载结果图片...", flush=True)
                img_response = requests.get(result_image_url, timeout=30)
                if img_response.status_code != 200:
                    raise Exception(f"图片下载失败: {img_response.status_code}")
                pil_image = Image.open(BytesIO(img_response.content))
                if pil_image.mode == 'RGBA':
                    pass
                elif pil_image.mode == 'LA':
                    pil_image = pil_image.convert('RGBA')
                elif pil_image.mode == 'P' and 'transparency' in pil_image.info:
                    pil_image = pil_image.convert('RGBA')
                elif pil_image.mode != 'RGB':
                    pil_image = pil_image.convert('RGB')
                image_np = np.array(pil_image).astype(np.float32) / 255.0
                image_tensor = torch.from_numpy(image_np)[None,]

                for tmp_path in temp_img_paths:
                    if os.path.exists(tmp_path):
                        try:
                            os.remove(tmp_path)
                        except:
                            pass

                return (image_tensor, compressed_pils, task_id)

            except Exception as e:
                last_exception = e
                print(f"❌ Token {i+1} 失败: {str(e)}")
                if i < len(tokens) - 1:
                    continue
                else:
                    break

        raise Exception(f"所有Token都失败了: {str(last_exception)}")

    def batch_edit(self, images, prompt, api_tokens,
                   negative_prompt="", edit_model="Qwen/Qwen-Image-Edit",
                   aspect_ratio="1:1", base_size=1024, steps=30, guidance=3.5, seed=-1):
        _BATCH_CANCEL["cancelled"] = False
        width, height = _resolve_aspect_size(aspect_ratio, base_size)
        config = load_config()
        tokens = parse_api_tokens(api_tokens)
        if not tokens:
            raise Exception("请提供至少一个有效的API Token")

        batch = images if len(images.shape) == 4 else images.unsqueeze(0)
        images_list = [batch[i] for i in range(batch.shape[0])]
        print(f"🔍 批量图像编辑: 输入 {len(images_list)} 张参考图, 模型: {edit_model}", flush=True)

        spec = self._parse_prompt_as_json(prompt)

        if spec is not None:
            shots = spec.get("shots", [])
            index_map = _load_index_map()
            seq_nums = sorted(int(n) for n in index_map.keys())
            if len(seq_nums) != len(images_list):
                seq_nums = list(range(1, len(images_list) + 1))
            print(f"📋 检测到 JSON 分镜: {len(shots)} 个 shot, 图号映射: {seq_nums}", flush=True)
            _send_batch_progress("预上传", f"上传{len(images_list)}张参考图", 0, len(shots), "generating")
            all_urls, all_pils, _ = self._upload_images(images_list, tokens[0] if tokens else None)
            valid_urls = sum(1 for u in all_urls if u)
            print(f"📦 预上传完成: {valid_urls}/{len(all_urls)} 张成功, 开始批量生成...", flush=True)
            if valid_urls == 0:
                print(f"❌ 所有参考图转换失败！请检查输入图片是否有效。", flush=True)
                _send_batch_progress("错误", "参考图全部上传失败", 0, len(shots), "error")
                empty = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
                return (empty, {"image": empty, "prompt": "", "model": edit_model, "ref_images": torch.zeros((0, 64, 64, 3), dtype=torch.float32)})
            cached_upload = (all_urls, all_pils)
            print(f"📦 预上传完成, 开始批量生成...", flush=True)
            save_tokens_on_success(api_tokens)
            return self._batch_from_json(spec, images_list, prompt, negative_prompt,
                                         edit_model, width, height, steps, guidance, seed,
                                         tokens, config, cached_upload=cached_upload, seq_nums=seq_nums)

        batch_port_nums = list(range(1, len(images_list) + 1))
        image_tensor, ref_pils, _ = self._generate_one(
            images_list, prompt, negative_prompt,
            edit_model, width, height, steps, guidance, seed, tokens, config,
            port_nums=batch_port_nums)
        ref_tensor = _pils_to_batch(ref_pils)
        qibodata = {"image": image_tensor, "prompt": prompt, "model": edit_model, "ref_images": ref_tensor}
        save_tokens_on_success(api_tokens)
        return (image_tensor, qibodata)

    def _batch_from_json(self, spec, images_list, prompt, negative_prompt,
                         edit_model, width, height, steps, guidance, seed,
                         tokens, config, cached_upload=None, seq_nums=None):
        shots = spec.get("shots", [])
        global_style = spec.get("global_style", "")
        global_negative = spec.get("global_negative_prompt", "")
        total = len(shots)
        all_urls, all_pils = cached_upload if cached_upload else (None, None)

        if seq_nums is None or len(seq_nums) != len(images_list):
            seq_nums = list(range(1, len(images_list) + 1))
        num_to_list_idx = {n: i for i, n in enumerate(seq_nums)}
        print(f"🔗 图号→索引映射: {num_to_list_idx}", flush=True)

        cn_num_map = _CN_NUM
        ref_key_re = re.compile(_PREFIX_PAT + _SEP_PAT + r'(' + _NUM_PAT + r')', re.IGNORECASE)

        results = []
        submitted_tasks = []

        for idx, shot in enumerate(shots):
            if _BATCH_CANCEL["cancelled"]:
                print(f"⏹️ 提交阶段用户取消，已提交 {len(submitted_tasks)}/{total}", flush=True)
                break

            shot_id = shot.get("shot_id", f"shot_{idx+1:02d}")
            title = shot.get("title", "")
            shot_prompt = shot.get("prompt", "")
            shot_negative = shot.get("negative_prompt", "")
            ref_keys = shot.get("reference_images", [])

            full_prompt = f"{global_style}\n{shot_prompt}" if global_style else shot_prompt
            full_negative = f"{global_negative}\n{shot_negative}" if global_negative else shot_negative

            # ---------- 1. 解析 reference_images → 原始图号（保留顺序，去重）----------
            orig_nums = []
            seen_nums = set()
            for key in ref_keys:
                m = ref_key_re.search(key)
                if not m:
                    continue
                g = m.group(1)
                num = cn_num_map.get(g, int(g) if g.isdigit() else 0)
                if num in num_to_list_idx and num not in seen_nums:
                    orig_nums.append(num)
                    seen_nums.add(num)
            # 未指定 reference_images 时默认引用全部
            if not orig_nums:
                orig_nums = list(seq_nums)

            # ---------- 2. 过滤上传失败的图（url 为空或 pil 缺失），三者成对保留 ----------
            valid_items = []  # [(原图号, url, pil), ...]
            for num in orig_nums:
                j = num_to_list_idx.get(num)
                if j is None or all_urls is None or j >= len(all_urls):
                    continue
                url = all_urls[j]
                pil = all_pils[j] if all_pils and j < len(all_pils) else None
                if not url or pil is None:
                    print(f"  ⚠️ shot={shot_id} 图{num} 上传失败或缺失，跳过", flush=True)
                    continue
                valid_items.append((num, url, pil))

            if not valid_items:
                print(f"  ❌ shot={shot_id} 无任何有效参考图，跳过该 shot", flush=True)
                _send_batch_progress(shot_id, "参考图全部无效", idx + 1, total, "error")
                continue

            # ---------- 3. 图号重映射：原图号 → 发送数组中的新图号（从 1 起）----------
            valid_nums = [it[0] for it in valid_items]
            remap = {orig: new for new, orig in enumerate(valid_nums, 1)}
            if remap != {n: n for n in valid_nums}:
                full_prompt = _remap_prompt_refs(full_prompt, remap)
                print(f"  📎 shot={shot_id} 图号 {valid_nums} → 图1..图{len(valid_nums)}", flush=True)
                print(f"     重写后: {full_prompt[:120]}", flush=True)
            else:
                print(f"  📝 shot={shot_id} 图号 {valid_nums} 已是连续序号，无需重映射", flush=True)

            shot_urls = [it[1] for it in valid_items]
            shot_pils = [it[2] for it in valid_items]
            shot_cached = (shot_urls, shot_pils)

            shot_token = tokens[idx % len(tokens)]
            safe_id = re.sub(r'[\\/:*?"<>|\s]+', '_', shot_id).strip('_') or f"shot_{idx+1:02d}"
            safe_title = re.sub(r'[\\/:*?"<>|]+', '_', title).strip().strip('.')
            fname = f"{safe_id}_{safe_title}.png" if safe_title else f"{safe_id}.png"
            task_meta = {"shot_id": shot_id, "title": title, "filename": fname}

            print(f"📨 [{idx+1}/{total}] 提交 {shot_id}: {title} | 原图号={valid_nums} | 有效URL数={len(shot_urls)} | token={'有' if shot_token else '无'}", flush=True)
            _send_batch_progress(shot_id, f"提交中", idx + 1, total, "generating")
            submit_result = self._submit_task(
                full_prompt, full_negative,
                edit_model, width, height, steps, guidance, seed,
                shot_token, shot_cached, task_meta=task_meta)
            if submit_result:
                task_id, image_urls, seed_used = submit_result
                submitted_tasks.append({
                    "task_id": task_id,
                    "shot_id": shot_id,
                    "title": title,
                    "filename": fname,
                    "prompt": full_prompt,
                    "negative": full_negative,
                    "model": edit_model,
                    "width": width,
                    "height": height,
                    "steps": steps,
                    "guidance": guidance,
                    "seed_used": seed_used,
                    "cached": shot_cached,
                    "token": shot_token,
                    "task_meta": task_meta,
                })
                _send_batch_progress(shot_id, f"已提交({len(submitted_tasks)}/{total})", idx + 1, total, "generating")
            else:
                _send_batch_progress(shot_id, title, idx + 1, total, "error")

        print(f"📦 提交阶段完成: {len(submitted_tasks)}/{total} 个任务已提交，开始轮询获取结果...", flush=True)

        if not submitted_tasks:
            print(f"❌ 没有任务被成功提交，无法进入轮询阶段！请检查 API Token 和网络连接。", flush=True)
            _send_batch_progress("错误", "无任务被提交", 0, total, "error")
            empty = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
            return (empty, {"image": empty, "prompt": "", "model": edit_model, "ref_images": torch.zeros((0, 64, 64, 3), dtype=torch.float32)})

        _send_batch_progress("轮询阶段", f"{len(submitted_tasks)}个任务开始获取结果", 0, len(submitted_tasks), "generating")

        poll_total = len(submitted_tasks)
        for idx, task_info in enumerate(submitted_tasks):
            if _BATCH_CANCEL["cancelled"]:
                print(f"⏹️ 轮询阶段用户取消，已完成 {len(results)}/{poll_total}", flush=True)
                break

            task_id = task_info["task_id"]
            shot_id = task_info["shot_id"]
            title = task_info["title"]
            fname = task_info["filename"]
            full_prompt = task_info["prompt"]
            shot_token = task_info["token"]
            task_meta = task_info["task_meta"]

            progress_ctx = {"shot_id": shot_id, "title": title, "current": idx + 1, "total": poll_total}
            _send_batch_progress(shot_id, f"轮询中", idx + 1, poll_total, "generating")
            print(f"⏳ [{idx+1}/{poll_total}] 轮询 {shot_id} task_id={task_id}", flush=True)

            pil_image = None
            cur_task_id = task_id
            for resubmit_attempt in range(3):
                pil_image, reason = self._poll_and_download(
                    cur_task_id, shot_token, config, progress_ctx=progress_ctx, task_meta=task_meta)
                if pil_image is not None or reason != "task_not_found":
                    break
                if _BATCH_CANCEL["cancelled"]:
                    break
                print(f"🔄 [{idx+1}/{poll_total}] {shot_id} task not found，重新提交({resubmit_attempt+1}/2)...", flush=True)
                reres = self._submit_task(
                    task_info["prompt"], task_info["negative"],
                    task_info["model"], task_info["width"], task_info["height"],
                    task_info["steps"], task_info["guidance"], task_info["seed_used"],
                    shot_token, task_info["cached"], task_meta=task_meta)
                if not reres:
                    break
                cur_task_id = reres[0]
                print(f"📨 [{idx+1}/{poll_total}] {shot_id} 重新提交成功 task_id={cur_task_id}", flush=True)
            if pil_image is not None:
                img_np = np.array(pil_image).astype(np.float32) / 255.0
                img_tensor = torch.from_numpy(img_np)[None,]
                _save_image_and_meta("output", img_tensor, full_prompt, edit_model, None, filename_override=fname)
                _update_batch_task_status(cur_task_id, "done")
                results.append(img_tensor)
                print(f"💾 [{idx+1}/{poll_total}] 已保存: {fname}", flush=True)
                _send_batch_progress(shot_id, title, idx + 1, poll_total, "done")
            else:
                _send_batch_progress(shot_id, title, idx + 1, poll_total, "error")
                if _BATCH_CANCEL["cancelled"]:
                    break

        if not results:
            empty = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
            return (empty, {"image": empty, "prompt": "", "model": edit_model, "ref_images": torch.zeros((0, 64, 64, 3), dtype=torch.float32)})

        all_images = torch.cat(results, dim=0)
        qibodata = {"image": all_images, "prompt": "", "model": edit_model, "ref_images": _pils_to_batch([])}
        _send_batch_progress("", "", len(results), total, "finished")
        return (all_images, qibodata)


NODE_CLASS_MAPPINGS = {
    "QIBOImageNode": ModelScopeImageNode,
    "QIBOImageEditNode": ModelScopeImageEditNode,
    "QIBOBatchImageEditNode": QIBOBatchImageEditNode,
    "QIBOLORAPresetNode": ModelScopeLoraPresetNode,
    "QIBOSingleLoraLoaderNode": ModelScopeSingleLoraLoaderNode,
    "QIBOMultiLoraLoaderNode": ModelScopeMultiLoraLoaderNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBOImageNode": "QIBO-Image 生图节点",
    "QIBOImageEditNode": "QIBO-Image 图像编辑节点",
    "QIBOBatchImageEditNode": "QIBO-Image 批量图像编辑",
    "QIBOLORAPresetNode": "QIBO-LoRA 预设管理",
    "QIBOSingleLoraLoaderNode": "QIBO-LoRA 单LoRA加载",
    "QIBOMultiLoraLoaderNode": "QIBO-LoRA 多LoRA加载",
}