import os
import json
import torch
import numpy as np

from .qibo_auth import load_api_tokens, parse_api_tokens, load_config

try:
    from server import PromptServer
    from aiohttp import web
    _SERVER_OK = True
except Exception:
    _SERVER_OK = False
    PromptServer = None
    web = None


def _get_segment_desc(prompt: str, segment_index: int) -> str:
    """取第 segment_index 段的描述。

    - prompt 为 JSON 数组：取 segment_index 对应块；超出范围则复用最后一块并警告。
    - prompt 为 JSON 对象含 kept/segments 数组：从该数组取对应块。
    - prompt 为普通文本：直接返回整段文本。
    """
    text = prompt.strip()
    if text.startswith("[") or text.startswith("{"):
        try:
            data = json.loads(text)
            if isinstance(data, list) and len(data) > 0:
                arr = _sort_by_id(data)
                descs = [_extract_desc_from_obj(x) if isinstance(x, dict) else str(x).strip() for x in arr]
                return _pick(descs, segment_index)
            if isinstance(data, dict):
                for key in ("kept", "segments", "items", "list"):
                    arr = data.get(key)
                    if isinstance(arr, list) and len(arr) > 0:
                        arr = _sort_by_id(arr)
                        descs = [_extract_desc_from_obj(x) if isinstance(x, dict) else str(x).strip() for x in arr]
                        return _pick(descs, segment_index)
            print(f"⚠️ JSON 解析成功但未找到 kept/segments/items/list 数组，prompt 将作为普通文本使用。")
        except (json.JSONDecodeError, ValueError) as e:
            print(f"⚠️ JSON 解析失败: {e}。prompt 将作为普通文本使用（每段会用同一段文本）。")
    return prompt


def _sort_by_id(arr: list) -> list:
    """按对象 id 字段从小到大排序；无 id 字段则保持原序。"""
    if all(isinstance(x, dict) and "id" in x for x in arr):
        return sorted(arr, key=lambda x: x["id"])
    return arr


def _count_json_segments(prompt: str) -> int:
    """返回 JSON 中段数；非 JSON 或解析失败返回 0。"""
    text = prompt.strip()
    if not (text.startswith("[") or text.startswith("{")):
        return 0
    try:
        data = json.loads(text)
        if isinstance(data, list) and len(data) > 0:
            return len(data)
        if isinstance(data, dict):
            for key in ("kept", "segments", "items", "list"):
                arr = data.get(key)
                if isinstance(arr, list) and len(arr) > 0:
                    return len(arr)
    except (json.JSONDecodeError, ValueError):
        pass
    return 0


def _get_segment_title(prompt: str, segment_index: int) -> str:
    """取第 segment_index 段的 title；无 title 返回空串。"""
    text = prompt.strip()
    if not (text.startswith("[") or text.startswith("{")):
        return ""
    try:
        data = json.loads(text)
        if isinstance(data, list) and len(data) > 0:
            arr = _sort_by_id(data)
            if segment_index < len(arr) and isinstance(arr[segment_index], dict):
                return str(arr[segment_index].get("title", "")).strip()
        if isinstance(data, dict):
            for key in ("kept", "segments", "items", "list"):
                arr = data.get(key)
                if isinstance(arr, list) and len(arr) > 0:
                    arr = _sort_by_id(arr)
                    if segment_index < len(arr) and isinstance(arr[segment_index], dict):
                        return str(arr[segment_index].get("title", "")).strip()
    except (json.JSONDecodeError, ValueError):
        pass
    return ""


def _pick(descs: list, idx: int) -> str:
    if idx < len(descs):
        return descs[idx]
    print(f"⚠️ segment_index={idx} 超出 JSON 块数 {len(descs)}，复用最后一块。")
    return descs[-1]


def _extract_desc_from_obj(obj: dict) -> str:
    """从 JSON 对象提取描述：用 slots 里各段落拼接，不用 prompt 字段。无 slots 时回退 content > title。"""
    slots = obj.get("slots")
    if isinstance(slots, dict):
        parts = []
        for key in ("structure", "body", "color"):
            slot_val = slots.get(key)
            if isinstance(slot_val, list):
                parts.extend(str(s).strip() for s in slot_val if str(s).strip())
            elif isinstance(slot_val, str) and slot_val.strip():
                parts.append(slot_val.strip())
        if parts:
            return "\n\n".join(parts)
    for key in ("content", "prompt"):
        val = str(obj.get(key, "")).strip()
        if val:
            return val
    return str(obj.get("title", "")).strip()


def _match_color(src: torch.Tensor, ref: torch.Tensor) -> torch.Tensor:
    """Per-channel mean/std color transfer from src to match ref."""
    src_mean = src.mean(dim=(0, 1), keepdim=True)
    src_std = src.std(dim=(0, 1), keepdim=True).clamp(min=1e-6)
    ref_mean = ref.mean(dim=(0, 1), keepdim=True)
    ref_std = ref.std(dim=(0, 1), keepdim=True).clamp(min=1e-6)
    return ((src - src_mean) * (ref_std / src_std) + ref_mean).clamp(0.0, 1.0)


def _match_color_from_overlap(src: torch.Tensor, src_overlap: torch.Tensor,
                               ref_overlap: torch.Tensor) -> torch.Tensor:
    """Color transfer using overlap region statistics for precise edge matching."""
    src_mean = src_overlap.mean(dim=(0, 1), keepdim=True)
    src_std = src_overlap.std(dim=(0, 1), keepdim=True).clamp(min=1e-6)
    ref_mean = ref_overlap.mean(dim=(0, 1), keepdim=True)
    ref_std = ref_overlap.std(dim=(0, 1), keepdim=True).clamp(min=1e-6)
    return ((src - src_mean) * (ref_std / src_std) + ref_mean).clamp(0.0, 1.0)


def _global_color_unify(panorama: torch.Tensor, ref: torch.Tensor) -> torch.Tensor:
    """Global color transfer: unify the entire panorama to match ref's color stats."""
    return _match_color(panorama, ref)


def _stitch_horizontal(segments: list[torch.Tensor], overlap: int, color_match: bool) -> torch.Tensor:
    """Stitch segments horizontally with feathered overlap blending."""
    result = segments[0].clone()
    for seg in segments[1:]:
        curr = seg.clone()
        if color_match:
            ref_edge = result[:, -overlap:, :]
            curr_edge = curr[:, :overlap, :]
            curr = _match_color_from_overlap(curr, curr_edge, ref_edge)
        ow = min(overlap, result.shape[1], curr.shape[1])
        if ow <= 0:
            result = torch.cat([result, curr], dim=1)
            continue
        alpha = torch.linspace(1.0, 0.0, ow, device=result.device).view(1, -1, 1)
        blended = alpha * result[:, -ow:, :] + (1.0 - alpha) * curr[:, :ow, :]
        result = torch.cat([result[:, :-ow, :], blended, curr[:, ow:, :]], dim=1)
    return result


def _stitch_vertical(segments: list[torch.Tensor], overlap: int, color_match: bool) -> torch.Tensor:
    """Stitch segments vertically with feathered overlap blending."""
    result = segments[0].clone()
    for seg in segments[1:]:
        curr = seg.clone()
        if color_match:
            ref_edge = result[-overlap:, :, :]
            curr_edge = curr[:overlap, :, :]
            curr = _match_color_from_overlap(curr, curr_edge, ref_edge)
        oh = min(overlap, result.shape[0], curr.shape[0])
        if oh <= 0:
            result = torch.cat([result, curr], dim=0)
            continue
        alpha = torch.linspace(1.0, 0.0, oh, device=result.device).view(-1, 1, 1)
        blended = alpha * result[-oh:, :, :] + (1.0 - alpha) * curr[:oh, :, :]
        result = torch.cat([result[:-oh, :, :], blended, curr[oh:, :, :]], dim=0)
    return result


class QIBOImageStitchNode:
    """分段图片拼接节点：重叠渐变融合 + 颜色校正，生成自然超长图。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "overlap": ("INT", {"default": 64, "min": 0, "max": 512,
                                    "tooltip": "重叠像素数，越大拼接越自然但有效画面越少。"}),
                "direction": (["horizontal", "vertical"], {"default": "horizontal"}),
                "color_match": ("BOOLEAN", {"default": True,
                                            "tooltip": "以第一段为基准校正后续段的颜色均值和方差。"}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "stitch"
    OUTPUT_NODE = True
    CATEGORY = "QIBO_API"

    def stitch(self, images, overlap=64, direction="horizontal", color_match=True):
        if images is None or images.shape[0] == 0:
            raise ValueError("没有输入图片")
        segments = [images[i] for i in range(images.shape[0])]
        if len(segments) == 1:
            return (segments[0].unsqueeze(0),)
        if direction == "horizontal":
            panorama = _stitch_horizontal(segments, overlap, color_match)
        else:
            panorama = _stitch_vertical(segments, overlap, color_match)
        import time
        from PIL import Image
        changtu_dir = _resolve_changtu_dir()
        os.makedirs(changtu_dir, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())
        out_name = f"pj_长图拼接_{ts}.png"
        out_path = os.path.join(changtu_dir, out_name)
        arr = (panorama.cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
        Image.fromarray(arr).save(out_path)
        try:
            meta = _load_changtu_meta()
            meta[out_name] = {
                "seg_prompt": f"拼接长图（{len(segments)} 段，{direction}，overlap={overlap}）",
                "edit_model": "QIBOImageStitchNode",
                "seg_desc": f"由 {len(segments)} 张图片{'垂直' if direction == 'vertical' else '水平'}拼接而成的超长图",
                "segment_index": -1,
            }
            _save_changtu_meta(meta)
        except Exception as e:
            print(f"⚠️ 写入 meta JSON 失败: {e}")
        print(f"💾 拼接长图已保存到画廊: {out_path} ({panorama.shape[1]}x{panorama.shape[0]}, {len(segments)} 段, direction={direction})")
        if _SERVER_OK:
            try:
                PromptServer.instance.send_sync("qibo_panorama_gallery_update", {"saved": 1})
            except Exception:
                pass
        return (panorama.unsqueeze(0),)


class QIBOPanoramaGenNode:
    """超长图逐段生成：每次以输入图（上一段）为参考，生成向下自然延伸的下一段（1 张图）。
    拼接交给下游 QIBOImageStitchNode 完成，本节点不拼接。"""

    @classmethod
    def INPUT_TYPES(cls):
        saved_tokens = load_api_tokens()
        config = load_config()
        edit_models = config.get("image_edit_models", ["Qwen/Qwen-Image-Edit"])
        default_edit = edit_models[0] if edit_models else "Qwen/Qwen-Image-Edit"
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": "向下延伸的连续画面",
                                       "tooltip": "本段描述。若填了 prompt_file 则忽略此框。\n三种模式：\n1) JSON 对象数组：[{\"id\":1,\"title\":\"...\",\"prompt\":\"...\"}, ...]，配合 segment_index 取对应块（优先 prompt > content > slots拼接 > title）。\n2) JSON 字符串数组：[\"天空与云\",...]，配合 segment_index 取对应块。\n3) 普通文本：整段即本段描述。"}),
                "segment_index": ("INT", {"default": 0, "min": 0, "max": 999,
                                          "tooltip": "起始段索引。prompt 为 JSON 数组时，取第 segment_index 块作为本段描述（0-based）。\ntotal_segments>1 时，从 segment_index 开始连续生成多段。"}),
                "total_segments": ("INT", {"default": 1, "min": 1, "max": 20,
                                           "tooltip": "一次生成几段。如 JSON 有 4 段描述，设 total_segments=4 一次全部生成。每段自动接续上一段。"}),
                "cache_id": ("STRING", {"default": "default",
                                        "tooltip": "缓存 ID。不同任务用不同 ID 隔离各自的底部边缘缓存。同一 ID 反复运行会自动接续上一段。"}),
                "clear_cache": ("BOOLEAN", {"default": False,
                                            "tooltip": "清缓存。True=删除该 cache_id 的所有缓存，从 start_image 重新开始。"}),

                "api_tokens": ("STRING", {
                    "default": f"***已保存{len(saved_tokens)}个Token***" if saved_tokens else "",
                    "multiline": True,
                }),
                "width": ("INT", {"default": 1024, "min": 256, "max": 2752, "step": 64,
                                  "tooltip": "图片固定宽度。"}),
                "segment_height": ("INT", {"default": 1024, "min": 256, "max": 2048, "step": 64,
                                           "tooltip": "本段生成高度。API 限制 ≤ 2048。"}),
                "outpaint_overlap": ("INT", {"default": 64, "min": 32, "max": 512,
                                             "tooltip": "边缘条高度（从上一段底部取的像素数）。值越小 API 融合范围越小，建议 64。合并节点 crop_top 需与此值一致。"}),
                "edit_model": (edit_models, {"default": default_edit,
                                             "tooltip": "图片编辑模型，从 qibo_config.json 的 image_edit_models 读取。"}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 2147483647,
                                 "control_after_generate": True}),
            },
            "optional": {
                "start_image": ("IMAGE", {"tooltip": "起始参考图。仅当无缓存或 clear_cache=True 时使用（取其底部 ref_crop_pixels 作为参考）。有缓存时自动忽略。"}),
                "prompt_file": ("STRING", {"default": "",
                                            "tooltip": "JSON 文件路径（如 图像描述_重排.json）。填了则从此文件读取 JSON，覆盖 prompt 文本框。"}),
                "negative_prompt": ("STRING", {"multiline": True, "default": ""}),
                "regen_info": ("STRING", {"multiline": True, "default": "",
                                           "tooltip": "连接画廊节点的 selected_info 输出。填了则重新生成选中段（用记录中的参考图和提示词），忽略正常生成流程。"}),
            }
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "info")
    FUNCTION = "generate_segment"
    CATEGORY = "QIBO_API"

    def generate_segment(self, prompt, segment_index, total_segments, cache_id, clear_cache, api_tokens,
                         width, segment_height, outpaint_overlap, edit_model, seed,
                         start_image=None, prompt_file="", negative_prompt="", regen_info=""):
        import os
        from PIL import Image
        from .qibo_image_node import ModelScopeImageEditNode

        if regen_info and regen_info.strip():
            return self._regenerate_segment(regen_info, api_tokens, cache_id, outpaint_overlap)

        if prompt_file and prompt_file.strip():
            p = prompt_file.strip()
            if p.startswith("{") or p.startswith("["):
                prompt = p
                print(f"📄 prompt_file 是 JSON 内容，直接使用（非文件路径）")
            else:
                if not os.path.isabs(p):
                    p = os.path.join(os.path.dirname(__file__), p)
                with open(p, 'r', encoding='utf-8') as f:
                    prompt = f.read()
                print(f"📄 已从文件读取描述: {p}")

        if seed == -1:
            seed = int(np.random.randint(0, 2147483647))
        else:
            seed = max(0, min(int(seed), 2147483647))

        json_segs = _count_json_segments(prompt)
        if json_segs > 0 and json_segs < total_segments:
            print(f"📋 JSON 仅含 {json_segs} 段描述，total_segments 从 {total_segments} 自动调整为 {json_segs}")
            total_segments = json_segs

        cache_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "output", "qibo_panorama_cache"))
        os.makedirs(cache_dir, exist_ok=True)
        first_cache = os.path.join(cache_dir, f"first_image_{cache_id}.png")
        edge_cache = os.path.join(cache_dir, f"bottom_edge_{cache_id}.png")
        last_cache = os.path.join(cache_dir, f"last_generated_{cache_id}.png")

        if clear_cache:
            for f in (first_cache, edge_cache, last_cache):
                if os.path.exists(f):
                    os.remove(f)
            print(f"🗑️ 已清除缓存 (cache_id={cache_id})")

        # segment_index=0 且有 start_image 输入时，自动清除 edge/last 缓存（刷新页面后自动重置为第一段）
        if segment_index == 0 and start_image is not None:
            for f in (edge_cache, last_cache):
                if os.path.exists(f):
                    os.remove(f)
            print(f"🔄 segment_index=0，自动重置为第一段（清除 edge/last 缓存）")

        def _save_tensor(t, path):
            arr = (t.cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
            Image.fromarray(arr).save(path)

        def _load_tensor(path):
            img = Image.open(path)
            if img.mode != "RGB":
                img = img.convert("RGB")
            arr = np.array(img).astype(np.float32) / 255.0
            return torch.from_numpy(arr).unsqueeze(0)

        if start_image is not None:
            _save_tensor(start_image[0], first_cache)
            print(f"💾 已保存第一张整图到缓存: {first_cache} ({start_image.shape[1]}x{start_image.shape[2]})")

        if not os.path.exists(first_cache):
            raise ValueError("无第一张整图缓存且未提供 start_image。请先连 start_image + clear_cache=True。")

        editor = ModelScopeImageEditNode()
        all_segs = []
        all_infos = []

        for i in range(total_segments):
            cur_idx = segment_index + i
            cur_seed = (seed + i) % 2147483647
            seg_desc = _get_segment_desc(prompt, cur_idx)

            # 加载边缘参考
            if os.path.exists(edge_cache):
                edge_ref = _load_tensor(edge_cache)
            elif start_image is not None:
                ref_h = start_image.shape[1]
                crop_h = min(outpaint_overlap, ref_h)
                edge_ref = start_image[:, -crop_h:, :, :]
                _save_tensor(edge_ref[0], edge_cache)
                print(f"📷 首次：从 start_image 底部取 {crop_h}px 作为边缘参考")
            else:
                raise ValueError("无衔接边缘缓存且未提供 start_image。请先连 start_image + clear_cache=True。")

            top_h = edge_ref.shape[1]
            print(f"🖼️ 扩图生成: 段索引={cur_idx}/{segment_index + total_segments - 1}, cache_id={cache_id}, 边缘条={width}x{top_h}, 目标生成={width}x{segment_height}, 编辑模型={edit_model}")
            print(f"   📝 段{cur_idx}描述(前120字): {seg_desc[:120]}")

            seg_prompt = (
                f"以输入图片底部为起点向下延伸，按以下描述生成连续的新内容：{seg_desc}"
            )

            try:
                result = editor.edit_image(
                    edge_ref, seg_prompt, api_tokens,
                    edit_model=edit_model,
                    negative_prompt=negative_prompt,
                    width=width, height=segment_height, seed=cur_seed,
                )
            except Exception as e:
                if "download image error" in str(e) or "statuscode: 404" in str(e):
                    print(f"⚠️ API 下载图片失败(404)，清除上传缓存后重试一次...")
                    from .qibo_repo_uploader import _cache, _save_cache
                    _cache.clear()
                    _save_cache()
                    result = editor.edit_image(
                        edge_ref, seg_prompt, api_tokens,
                        edit_model=edit_model,
                        negative_prompt=negative_prompt,
                        width=width, height=segment_height, seed=cur_seed,
                    )
                else:
                    raise
            seg = result[0][0]

            # alpha 渐变混合：保留上一段底部的光线和背景到新图顶部，供下一段参考
            overlap_h = min(outpaint_overlap, seg.shape[0], top_h)
            if overlap_h > 0 and edge_ref.shape[2] == seg.shape[1]:
                alpha = torch.linspace(0, 1, overlap_h, dtype=seg.dtype).view(-1, 1, 1)
                edge_strip = edge_ref[0, :overlap_h, :, :]
                seg[:overlap_h, :, :] = alpha * seg[:overlap_h, :, :] + (1 - alpha) * edge_strip
                print(f"🔀 段 {cur_idx}: alpha 渐变混合顶部 {overlap_h}px（保留上一段光线/背景）")

            seg_bottom = seg[-min(outpaint_overlap, seg.shape[0]):, :, :]
            _save_tensor(seg_bottom, edge_cache)
            _save_tensor(seg, last_cache)
            print(f"✅ 段 {cur_idx} 完成: {seg.shape[1]}x{seg.shape[0]}，已更新 edge/last 缓存")

            ref_path = os.path.join(cache_dir, f"ref_seg{cur_idx}_{cache_id}.png")
            gen_path = os.path.join(cache_dir, f"gen_seg{cur_idx}_{cache_id}.png")
            _save_tensor(edge_ref[0], ref_path)
            _save_tensor(seg, gen_path)

            seg_title = _get_segment_title(prompt, cur_idx)


            records_path = os.path.join(cache_dir, f"gen_records_{cache_id}.json")
            records = {"cache_id": cache_id, "segments": []}
            if os.path.exists(records_path):
                try:
                    with open(records_path, 'r', encoding='utf-8') as rf:
                        records = json.load(rf)
                except (json.JSONDecodeError, ValueError):
                    pass
            segs_list = records.get("segments", [])
            import time as _t
            segs_list = [s for s in segs_list if s.get("segment_index") != cur_idx]
            segs_list.append({
                "segment_index": cur_idx,
                "title": seg_title,
                "seed": cur_seed,
                "edit_model": edit_model,
                "width": width,
                "height": segment_height,
                "outpaint_overlap": outpaint_overlap,
                "seg_desc": seg_desc,
                "seg_prompt": seg_prompt,
                "negative_prompt": negative_prompt,
                "ref_image": ref_path,
                "generated_image": gen_path,
                "timestamp": _t.strftime("%Y-%m-%dT%H:%M:%S"),
            })
            segs_list.sort(key=lambda s: s["segment_index"])
            records["segments"] = segs_list
            with open(records_path, 'w', encoding='utf-8') as wf:
                json.dump(records, wf, ensure_ascii=False, indent=2)
            print(f"📝 段 {cur_idx} 记录已保存: {records_path}")

            all_segs.append(seg)
            all_infos.append({
                "segment_index": cur_idx,
                "title": seg_title,
                "seed": cur_seed,
                "edit_model": edit_model,
                "width": width,
                "height": segment_height,
                "seg_desc": seg_desc,
                "seg_prompt": seg_prompt,
                "negative_prompt": negative_prompt,
                "ref_image": ref_path,
                "generated_image": gen_path,
                "timestamp": _t.strftime("%Y-%m-%dT%H:%M:%S"),
            })

        batch = torch.stack(all_segs)
        info = json.dumps(all_infos, ensure_ascii=False, indent=2)
        print(f"🎯 共生成 {total_segments} 段，输出 batch shape={batch.shape}")
        return (batch, info)

    def _regenerate_segment(self, regen_info, api_tokens, cache_id, outpaint_overlap):
        """根据画廊选中的段信息重新生成该段。"""
        import os
        from PIL import Image
        from .qibo_image_node import ModelScopeImageEditNode

        try:
            seg = json.loads(regen_info.strip())
        except (json.JSONDecodeError, ValueError) as e:
            raise ValueError(f"regen_info JSON 解析失败: {e}")

        seg_idx = seg.get("segment_index", 0)
        ref_path = seg.get("ref_image", "")
        gen_path = seg.get("generated_image", "")
        edit_model = seg.get("edit_model", "Qwen/Qwen-Image-Edit")
        width = seg.get("width", 1024)
        height = seg.get("height", 1024)
        seg_prompt = seg.get("seg_prompt", "")
        negative_prompt = seg.get("negative_prompt", "")
        seed = max(0, min(int(seg.get("seed", 0)), 2147483647))

        if not ref_path or not os.path.isfile(ref_path):
            raise ValueError(f"参考图不存在: {ref_path}")

        ref_img = Image.open(ref_path)
        if ref_img.mode != "RGB":
            ref_img = ref_img.convert("RGB")
        ref_arr = np.array(ref_img).astype(np.float32) / 255.0
        edge_ref = torch.from_numpy(ref_arr).unsqueeze(0)

        print(f"🔁 重新生成段 {seg_idx}: seed={seed}, model={edit_model}, {width}x{height}")
        print(f"   📝 提示词(前120字): {seg_prompt[:120]}")

        editor = ModelScopeImageEditNode()
        try:
            result = editor.edit_image(
                edge_ref, seg_prompt, api_tokens,
                edit_model=edit_model,
                negative_prompt=negative_prompt,
                width=width, height=height, seed=seed,
            )
        except Exception as e:
            if "download image error" in str(e) or "statuscode: 404" in str(e):
                from .qibo_repo_uploader import _cache, _save_cache
                _cache.clear()
                _save_cache()
                result = editor.edit_image(
                    edge_ref, seg_prompt, api_tokens,
                    edit_model=edit_model,
                    negative_prompt=negative_prompt,
                    width=width, height=height, seed=seed,
                )
            else:
                raise

        new_seg = result[0][0]

        overlap_h = min(outpaint_overlap, new_seg.shape[0], edge_ref.shape[1])
        if overlap_h > 0 and edge_ref.shape[2] == new_seg.shape[1]:
            alpha = torch.linspace(0, 1, overlap_h, dtype=new_seg.dtype).view(-1, 1, 1)
            edge_strip = edge_ref[0, :overlap_h, :, :]
            new_seg[:overlap_h, :, :] = alpha * new_seg[:overlap_h, :, :] + (1 - alpha) * edge_strip

        cache_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "output", "qibo_panorama_cache"))
        if not gen_path:
            gen_path = os.path.join(cache_dir, f"gen_seg{seg_idx}_{cache_id}.png")
        arr = (new_seg.cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
        Image.fromarray(arr).save(gen_path)

        edge_cache = os.path.join(cache_dir, f"bottom_edge_{cache_id}.png")
        last_cache = os.path.join(cache_dir, f"last_generated_{cache_id}.png")
        seg_bottom = new_seg[-min(outpaint_overlap, new_seg.shape[0]):, :, :]
        bottom_arr = (seg_bottom.cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
        Image.fromarray(bottom_arr).save(edge_cache)
        Image.fromarray(arr).save(last_cache)

        import time as _t
        seg["generated_image"] = gen_path
        seg["timestamp"] = _t.strftime("%Y-%m-%dT%H:%M:%S")
        print(f"✅ 段 {seg_idx} 重新生成完成: {new_seg.shape[1]}x{new_seg.shape[0]}")

        batch = new_seg.unsqueeze(0)
        info = json.dumps([seg], ensure_ascii=False, indent=2)
        return (batch, info)


class QIBOPanoramaMergeNode:
    """超长图合并：把首张参考图 + 生成的 batch 自动合并成一张长图。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "生成节点输出的 batch 多张图。连接 QIBOPanoramaGenNode 的 image 输出。"}),
                "cache_id": ("STRING", {"default": "default",
                                        "tooltip": "缓存 ID。自动读取 first_image_{cache_id}.png 作为首张参考图。"}),
                "crop_top": ("INT", {"default": 64, "min": 0, "max": 512,
                                     "tooltip": "裁掉每张生成图顶部的融合区域像素数。应与生成节点的 outpaint_overlap 一致。首张参考图不裁。"}),

            },
            "optional": {
                "first_image": ("IMAGE", {"tooltip": "手动指定首张参考图。优先于缓存。"}),
            }
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "info")
    FUNCTION = "merge"
    OUTPUT_NODE = True
    CATEGORY = "QIBO_API"

    def merge(self, images, cache_id, crop_top=200, first_image=None):
        import os
        from PIL import Image

        if images is None or images.shape[0] == 0:
            raise ValueError("没有输入图片。请把 QIBOPanoramaGenNode 的 image 输出连接到本节点的 images 输入。")

        # 确定首张图：first_image 优先，否则从缓存读取
        if first_image is not None:
            head = first_image[0]
            head_src = "手动输入"
        else:
            cache_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "output", "qibo_panorama_cache"))
            first_cache = os.path.join(cache_dir, f"first_image_{cache_id}.png")
            if not os.path.exists(first_cache):
                raise ValueError(f"未找到首张图缓存 {first_cache}，请手动连 first_image 或先运行生成节点。")
            img = Image.open(first_cache)
            if img.mode != "RGB":
                img = img.convert("RGB")
            arr = np.array(img).astype(np.float32) / 255.0
            head = torch.from_numpy(arr)
            head_src = f"缓存({cache_id})"

        # 不裁生成图顶部；裁掉每张图底部 crop_top 像素（给下一段做参考的边缘条，和下一段顶部重叠），最后一张不裁
        segments = [head] + [images[i] for i in range(images.shape[0])]
        for i in range(len(segments) - 1):
            if crop_top > 0 and segments[i].shape[0] > crop_top:
                segments[i] = segments[i][:-crop_top, :, :]
                print(f"  ✂️ 图 {i}: 裁掉底部 {crop_top}px 参考区域，剩余 {segments[i].shape[0]}px")

        print(f"🔗 合并长图: 首张图({head_src}) {head.shape[1]}x{head.shape[0]} + {images.shape[0]} 段生成图, 裁底部{crop_top}px(除最后一张), 直接拼接")

        # 直接垂直拼接，不做颜色匹配或融合
        panorama = torch.cat(segments, dim=0)

        # 自动保存到 output/qibo_changtu 画廊目录
        changtu_dir = _resolve_changtu_dir()
        os.makedirs(changtu_dir, exist_ok=True)
        import time
        ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())
        out_name = f"pj_长图合并_{ts}.png"
        out_path = os.path.join(changtu_dir, out_name)
        arr = (panorama.cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
        Image.fromarray(arr).save(out_path)
        try:
            meta = _load_changtu_meta()
            meta[out_name] = {
                "seg_prompt": f"合并长图（首图+{images.shape[0]}段，裁底部{crop_top}px）",
                "edit_model": "QIBOPanoramaMergeNode",
                "seg_desc": f"首张参考图+{images.shape[0]}段生成图垂直拼接而成的超长图",
                "segment_index": -1,
            }
            _save_changtu_meta(meta)
        except Exception as e:
            print(f"⚠️ 写入 meta JSON 失败: {e}")
        print(f"💾 长图已保存到画廊: {out_path}")
        if _SERVER_OK:
            try:
                PromptServer.instance.send_sync("qibo_panorama_gallery_update", {"saved": 1})
            except Exception:
                pass

        info = f"长图: {panorama.shape[1]}x{panorama.shape[0]} (首张{head.shape[0]} + {images.shape[0]}段) | 已保存: {out_path}"
        print(f"✅ 合并完成: {panorama.shape[1]}x{panorama.shape[0]}")
        return (panorama.unsqueeze(0), info)


class QIBOPanoramaGalleryNode:
    """超长图画廊：读取 output/qibo_changtu 目录下所有图片，两列方格缩略图显示。
    收到 info 输入时自动把 info 中引用的生成图片保存到 output/qibo_changtu + meta JSON。
    保留 selected_info 输出端口返回空串，兼容旧工作流中残留的连线（不再用于循环连接）。
    选中生成由前端按钮直接调后端 API 实现。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {},
            "optional": {
                "info": ("STRING", {"multiline": True, "default": "",
                    "tooltip": "连接 QIBO 超长图生成节点的 info 输出。连线后每次生成完成自动保存图片到 output/qibo_changtu 并刷新画廊。"}),
                "selected_files": ("STRING", {"multiline": True, "default": "",
                    "tooltip": "前端选中长图按钮自动写入，JSON 文件名数组，按选中顺序加载图片输出为 IMAGE batch。"}),
            },
        }

    RETURN_TYPES = ("STRING", "IMAGE")
    RETURN_NAMES = ("selected_info", "selected_images")
    OUTPUT_NODE = True
    FUNCTION = "save_from_info"
    CATEGORY = "QIBO_API"

    def save_from_info(self, info=None, selected_files=None):
        if info:
            try:
                self._save_info_images_to_changtu(info)
            except Exception as e:
                print(f"⚠️ [QIBO 超长图画廊] 保存 info 图片失败: {e}")
                import traceback
                traceback.print_exc()
        stitch_path = os.path.join(_resolve_cache_dir(), "selected_stitch.json")
        stitch_files = None
        if os.path.isfile(stitch_path):
            try:
                with open(stitch_path, 'r', encoding='utf-8') as f:
                    stitch_files = f.read()
                print(f"📐 [QIBO 超长图画廊] 从 selected_stitch.json 读取选中文件列表")
            except Exception:
                stitch_files = None
        if not stitch_files:
            stitch_files = selected_files
        selected_images = self._load_selected_images(stitch_files)
        print(f"📐 [QIBO 超长图画廊] selected_images batch shape: {selected_images.shape}")
        return {"ui": {}, "result": ("", selected_images)}

    @staticmethod
    def _load_selected_images(selected_files_str):
        """从 selected_files JSON 字符串加载选中的图片，按顺序返回 IMAGE batch tensor。
        无选中或加载失败时返回空 batch (0,64,64,3)。"""
        empty = torch.zeros((0, 64, 64, 3), dtype=torch.float32)
        if not selected_files_str or not selected_files_str.strip():
            return empty
        try:
            filenames = json.loads(selected_files_str.strip())
        except (json.JSONDecodeError, ValueError):
            return empty
        if not isinstance(filenames, list) or not filenames:
            return empty
        from PIL import Image
        changtu_dir = _resolve_changtu_dir()
        tensors = []
        for fname in filenames:
            fpath = os.path.join(changtu_dir, fname)
            if not os.path.isfile(fpath):
                print(f"⚠️ [QIBO 超长图画廊] 选中图片不存在: {fname}")
                continue
            try:
                img = Image.open(fpath)
                if img.mode != "RGB":
                    img = img.convert("RGB")
                arr = np.array(img).astype(np.float32) / 255.0
                tensors.append(torch.from_numpy(arr))
            except Exception as e:
                print(f"⚠️ [QIBO 超长图画廊] 加载选中图片失败 {fname}: {e}")
        if not tensors:
            return empty
        batch = torch.stack(tensors, dim=0)
        print(f"📐 [QIBO 超长图画廊] 选中长图: {len(tensors)} 张，顺序: {filenames}")
        return batch

    @staticmethod
    def _save_info_images_to_changtu(info_str):
        """解析 info JSON，把每段 generated_image 引用的图片复制到 output/qibo_changtu。
        同时把段信息保存到 qibo_changtu_meta.json，供 hover 显示提示词和选中生成使用。
        文件名优先用 seg_desc 中解析出的 title，其次 segment_index，非法字符自动过滤。"""
        import shutil
        print(f"📥 [QIBO 超长图画廊] 收到 info，开始保存图片到 output/qibo_changtu")
        try:
            segments = json.loads(info_str.strip())
        except (json.JSONDecodeError, ValueError) as e:
            print(f"⚠️ [QIBO 超长图画廊] info JSON 解析失败: {e}")
            print(f"   info 前 200 字: {info_str[:200]}")
            return
        if not isinstance(segments, list):
            segments = [segments]
        print(f"   info 包含 {len(segments)} 段")
        changtu_dir = _resolve_changtu_dir()
        os.makedirs(changtu_dir, exist_ok=True)
        meta = _load_changtu_meta()
        saved = 0
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            gen_path = seg.get("generated_image", "")
            seg_idx = seg.get("segment_index", 0)
            if not gen_path:
                print(f"   ⚠️ 段 {seg_idx}: generated_image 为空，跳过")
                continue
            if not os.path.isfile(gen_path):
                print(f"   ⚠️ 段 {seg_idx}: 图片不存在 {gen_path}，跳过")
                continue
            safe_name = QIBOPanoramaGalleryNode._extract_title_from_seg(seg, seg_idx)
            dst_path = os.path.join(changtu_dir, f"{safe_name}.png")
            if os.path.abspath(dst_path) == os.path.abspath(gen_path):
                print(f"   ⏭️ 段 {seg_idx}: 源和目标相同，跳过")
                continue
            try:
                shutil.copy2(gen_path, dst_path)
                meta[f"{safe_name}.png"] = seg
                saved += 1
                print(f"   🖼️ 段 {seg_idx}: 已保存 {safe_name}.png <- {gen_path}")
            except Exception as e:
                print(f"   ⚠️ 段 {seg_idx}: 保存失败 {gen_path}: {e}")
        if saved:
            _save_changtu_meta(meta)
            print(f"✅ [QIBO 超长图画廊] 共保存 {saved} 张图片到 {changtu_dir}，段信息已写入 meta JSON")
            if _SERVER_OK:
                try:
                    PromptServer.instance.send_sync("qibo_panorama_gallery_update", {"saved": saved})
                except Exception:
                    pass
        else:
            print(f"⚠️ [QIBO 超长图画廊] 未保存任何图片，请检查 info 中 generated_image 路径是否存在")

    @staticmethod
    def _extract_title_from_seg(seg, seg_idx):
        """从 seg 中提取 title 做文件名：优先用 seg.title 字段，再从 seg_desc/seg_prompt
        JSON 中解析 title，最后回退 seg{index}。"""
        title_val = str(seg.get("title", "")).strip() if isinstance(seg, dict) else ""
        if title_val:
            safe = "".join(c for c in title_val if c not in '\\/:*?"<>|\n\r\t').strip()
            if len(safe) > 120:
                safe = safe[:120]
            if safe:
                return safe
        for field in ("seg_desc", "seg_prompt"):
            raw = (seg.get(field) or "").strip()
            if not raw:
                continue
            if raw.startswith("{"):
                try:
                    obj = json.loads(raw)
                    if isinstance(obj, dict):
                        title = str(obj.get("title", "")).strip()
                        if title:
                            safe = "".join(c for c in title if c not in '\\/:*?"<>|\n\r\t').strip()
                            if len(safe) > 120:
                                safe = safe[:120]
                            if safe:
                                return safe
                except (json.JSONDecodeError, ValueError):
                    pass
        return f"seg{seg_idx}"


def _resolve_changtu_dir():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "output", "qibo_changtu"))


def _resolve_changtu_meta_path():
    return os.path.join(_resolve_changtu_dir(), "qibo_changtu_meta.json")


def _load_changtu_meta():
    """读取 qibo_changtu_meta.json，返回 {filename: seg_info} 字典。"""
    path = _resolve_changtu_meta_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _save_changtu_meta(meta):
    """写入 qibo_changtu_meta.json。"""
    path = _resolve_changtu_meta_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def _match_seg_from_records(fname, segments):
    """从 gen_records segments 中为 fname 匹配段信息。
    匹配顺序：title 精确 > segN.png 按索引 > title 模糊包含。"""
    base = os.path.splitext(fname)[0]
    for seg in segments:
        title = QIBOPanoramaGalleryNode._extract_title_from_seg(seg, seg.get("segment_index", 0))
        if title and f"{title}.png" == fname:
            return seg
    if base.startswith("seg") and base[3:].isdigit():
        idx = int(base[3:])
        for seg in segments:
            if seg.get("segment_index") == idx:
                return seg
    for seg in segments:
        title = QIBOPanoramaGalleryNode._extract_title_from_seg(seg, seg.get("segment_index", 0))
        if title and title in base:
            return seg
    return None


def _resolve_cache_dir():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "output", "qibo_panorama_cache"))


if _SERVER_OK:
    _routes = PromptServer.instance.routes

    @_routes.get("/qibo/panorama_gallery/list")
    async def qibo_panorama_gallery_list(request):
        """读取 output/qibo_changtu 目录下所有图片，按 mtime 倒序返回。
        返回结构与 qibo_pic_gallery_node 的 list 接口一致，支持 limit/offset 分页。"""
        d = _resolve_changtu_dir()
        os.makedirs(d, exist_ok=True)
        limit = request.rel_url.query.get("limit")
        offset = request.rel_url.query.get("offset")
        limit = int(limit) if limit and limit.isdigit() else None
        offset = int(offset) if offset and offset.isdigit() else 0
        items = []
        if os.path.isdir(d):
            exts = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
            files = [f for f in os.listdir(d) if f.lower().endswith(exts)]
            files.sort(key=lambda f: os.path.getmtime(os.path.join(d, f)), reverse=True)
            import time as _t
            import math as _math
            meta = _load_changtu_meta()
            records_segs = []
            records_path = os.path.join(_resolve_cache_dir(), "gen_records_default.json")
            if os.path.isfile(records_path):
                try:
                    with open(records_path, 'r', encoding='utf-8') as rf:
                        records_segs = json.load(rf).get("segments", [])
                except Exception:
                    pass
            meta_changed = False
            for idx, fname in enumerate(files):
                fpath = os.path.join(d, fname)
                try:
                    from PIL import Image as _Img
                    img = _Img.open(fpath)
                    w, h = img.size
                    gcd = _math.gcd(w, h) if w and h else 0
                    ratio = f"{w // gcd}:{h // gcd}" if gcd > 0 else f"{w}:{h}"
                except Exception:
                    w, h, ratio = 0, 0, ""
                mtime = os.path.getmtime(fpath)
                seg_info = meta.get(fname)
                if not seg_info and records_segs:
                    seg_info = _match_seg_from_records(fname, records_segs)
                    if seg_info:
                        meta[fname] = seg_info
                        meta_changed = True
                if not seg_info:
                    seg_info = {}
                items.append({
                    "index": idx + 1,
                    "filename": fname,
                    "prompt": seg_info.get("seg_prompt", ""),
                    "model": seg_info.get("edit_model", ""),
                    "seg_desc": seg_info.get("seg_desc", ""),
                    "negative_prompt": seg_info.get("negative_prompt", ""),
                    "timestamp": _t.strftime("%Y-%m-%d %H:%M:%S", _t.localtime(mtime)),
                    "width": w,
                    "height": h,
                    "ratio": ratio,
                })
            if meta_changed:
                _save_changtu_meta(meta)

        total = len(items)
        if limit is not None:
            items = items[offset:offset + limit]
        return web.json_response({"items": items, "total": total})

    @_routes.post("/qibo/panorama_gallery/delete")
    async def qibo_panorama_gallery_delete(request):
        """删除 output/qibo_changtu 目录下指定图片。"""
        try:
            data = await request.json()
        except Exception:
            data = {}
        filename = data.get("filename", "")
        if not filename:
            return web.json_response({"ok": False, "error": "参数无效"})
        d = _resolve_changtu_dir()
        filepath = os.path.join(d, filename)
        if os.path.isfile(filepath):
            try:
                os.remove(filepath)
            except Exception as e:
                return web.json_response({"ok": False, "error": str(e)})
        meta = _load_changtu_meta()
        if filename in meta:
            del meta[filename]
            _save_changtu_meta(meta)
        return web.json_response({"ok": True})

    @_routes.post("/qibo/panorama_gallery/clear")
    async def qibo_panorama_gallery_clear(request):
        """清空 output/qibo_changtu 目录下所有图片。"""
        d = _resolve_changtu_dir()
        os.makedirs(d, exist_ok=True)
        exts = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
        removed = 0
        for fname in os.listdir(d):
            if fname.lower().endswith(exts):
                try:
                    os.remove(os.path.join(d, fname))
                    removed += 1
                except Exception:
                    pass
        _save_changtu_meta({})
        return web.json_response({"ok": True, "removed": removed})

    @_routes.post("/qibo/panorama_gallery/regenerate")
    async def qibo_panorama_gallery_regenerate(request):
        """重新生成选中的图片。直接从 qibo_changtu_meta.json 读取段信息，
        调用 _regenerate_segment 重新生成，新图片保存到 qibo_changtu，文件名加时间戳不覆盖原图。"""
        try:
            data = await request.json()
        except Exception:
            data = {}
        filenames = data.get("filenames", [])
        _pj = [f for f in filenames if str(f).startswith("pj_")]
        if _pj:
            print(f"⏭️ [QIBO 画廊] 重新生成过滤掉 {len(_pj)} 张拼接图(pj_): {_pj}")
        filenames = [f for f in filenames if not str(f).startswith("pj_")]
        if not filenames:
            return web.json_response({"ok": False, "error": "选中的全是拼接图(pj_)，不能对拼接图重新生成"})

        api_token_list = load_api_tokens()
        if not api_token_list:
            return web.json_response({"ok": False, "error": "未配置 API Token，请先登录"})
        api_tokens = ",".join(api_token_list)

        meta = _load_changtu_meta()
        cache_id = "default"
        outpaint_overlap = 64

        changtu_dir = _resolve_changtu_dir()
        os.makedirs(changtu_dir, exist_ok=True)
        gen_node = QIBOPanoramaGenNode()
        import time as _t
        from PIL import Image as _Img

        results = []
        for fname in filenames:
            matched_seg = meta.get(fname)
            if not matched_seg:
                results.append({"filename": fname, "ok": False, "error": f"meta 中未找到 {fname} 的段信息"})
                print(f"⚠️ [QIBO 超长图画廊] 重新生成跳过: {fname} (meta 中未找到段信息)")
                continue

            try:
                regen_info = json.dumps(matched_seg, ensure_ascii=False)
                batch, info = gen_node._regenerate_segment(regen_info, api_tokens, cache_id, outpaint_overlap)
                title_key = os.path.splitext(fname)[0]
                ts = _t.strftime("%Y%m%d_%H%M%S", _t.localtime())
                new_name = f"{title_key}_{ts}.png"
                new_path = os.path.join(changtu_dir, new_name)
                img_tensor = batch[0]
                img_np = (255.0 * img_tensor.cpu().numpy()).clip(0, 255).astype(np.uint8)
                _Img.fromarray(img_np).save(new_path)
                new_segs = json.loads(info)
                if isinstance(new_segs, list) and new_segs:
                    meta[new_name] = new_segs[0]
                    _save_changtu_meta(meta)
                results.append({"filename": fname, "ok": True, "new_filename": new_name})
                print(f"✅ [QIBO 超长图画廊] 重新生成: {fname} -> {new_name}")
            except Exception as e:
                results.append({"filename": fname, "ok": False, "error": str(e)})
                print(f"⚠️ [QIBO 超长图画廊] 重新生成失败: {fname}: {e}")
                import traceback
                traceback.print_exc()

        saved = sum(1 for r in results if r.get("ok"))
        if saved:
            try:
                PromptServer.instance.send_sync("qibo_panorama_gallery_update", {"saved": saved})
            except Exception:
                pass
        return web.json_response({"ok": True, "results": results, "saved": saved})

    @_routes.post("/qibo/panorama_gallery/select_stitch")
    async def qibo_panorama_gallery_select_stitch(request):
        """前端选中长图按钮调用，把选中文件名列表存到 selected_stitch.json。
        save_from_info 执行时读取该文件加载图片输出为 IMAGE batch，连线到合并节点。"""
        try:
            data = await request.json()
        except Exception:
            data = {}
        filenames = data.get("filenames", [])
        if not filenames:
            return web.json_response({"ok": False, "error": "未选中任何图片"})
        cache_dir = _resolve_cache_dir()
        os.makedirs(cache_dir, exist_ok=True)
        stitch_path = os.path.join(cache_dir, "selected_stitch.json")
        with open(stitch_path, 'w', encoding='utf-8') as f:
            json.dump(filenames, f, ensure_ascii=False)
        print(f"📐 [QIBO 超长图画廊] 选中长图: {len(filenames)} 张 -> {stitch_path}")
        return web.json_response({"ok": True, "count": len(filenames)})

    @_routes.post("/qibo/panorama_gallery/stitch_selected")
    async def qibo_panorama_gallery_stitch_selected(request):
        """前端选中拼接按钮直接调用：在后端把首图缓存 + 选中图片按选中顺序
        直接垂直拼接成长图，保存到 output/qibo_changtu 画廊。无需运行工作流。"""
        try:
            data = await request.json()
        except Exception:
            data = {}
        filenames = data.get("filenames", [])
        _pj = [f for f in filenames if str(f).startswith("pj_")]
        if _pj:
            print(f"⏭️ [QIBO 画廊] 选中拼接过滤掉 {len(_pj)} 张拼接图(pj_): {_pj}")
        filenames = [f for f in filenames if not str(f).startswith("pj_")]
        if not filenames:
            return web.json_response({"ok": False, "error": "选中的全是拼接图(pj_)，不能对拼接图再拼接"})
        crop_top = int(data.get("crop_top", 0) or 0)
        cache_id = data.get("cache_id", "default") or "default"

        cache_dir = _resolve_cache_dir()
        first_cache = os.path.join(cache_dir, f"first_image_{cache_id}.png")
        if not os.path.isfile(first_cache):
            return web.json_response({"ok": False, "error": f"未找到首图缓存 first_image_{cache_id}.png，请先运行生成节点生成首图"})

        from PIL import Image
        import time

        head_img = Image.open(first_cache)
        if head_img.mode != "RGB":
            head_img = head_img.convert("RGB")
        head_tensor = torch.from_numpy(np.array(head_img).astype(np.float32) / 255.0)

        changtu_dir = _resolve_changtu_dir()
        seg_tensors = []
        for fname in filenames:
            fpath = os.path.join(changtu_dir, fname)
            if not os.path.isfile(fpath):
                print(f"⚠️ [QIBO 选中拼接] 图片不存在: {fname}")
                continue
            try:
                img = Image.open(fpath)
                if img.mode != "RGB":
                    img = img.convert("RGB")
                arr = np.array(img).astype(np.float32) / 255.0
                seg_tensors.append(torch.from_numpy(arr))
            except Exception as e:
                print(f"⚠️ [QIBO 选中拼接] 加载失败 {fname}: {e}")

        if not seg_tensors:
            return web.json_response({"ok": False, "error": "选中图片全部加载失败"})

        segments = [head_tensor] + seg_tensors
        for i in range(len(segments) - 1):
            if crop_top > 0 and segments[i].shape[0] > crop_top:
                segments[i] = segments[i][:-crop_top, :, :]

        panorama = torch.cat(segments, dim=0)

        os.makedirs(changtu_dir, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())
        out_name = f"pj_长图拼接_{ts}.png"
        out_path = os.path.join(changtu_dir, out_name)
        arr_out = (panorama.cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
        Image.fromarray(arr_out).save(out_path)

        try:
            meta = _load_changtu_meta()
            meta[out_name] = {
                "seg_prompt": f"选中拼接长图（首图+{len(seg_tensors)}张选中，裁底部{crop_top}px）",
                "edit_model": "QIBOPanoramaGalleryNode",
                "seg_desc": f"首图+{len(seg_tensors)}张选中图按勾选顺序垂直拼接",
                "segment_index": -1,
            }
            _save_changtu_meta(meta)
        except Exception as e:
            print(f"⚠️ [QIBO 选中拼接] 写入 meta JSON 失败: {e}")

        print(f"💾 [QIBO 选中拼接] 长图已保存: {out_path} ({panorama.shape[1]}x{panorama.shape[0]}, 首图+{len(seg_tensors)}张)")

        if _SERVER_OK:
            try:
                PromptServer.instance.send_sync("qibo_panorama_gallery_update", {"saved": 1})
            except Exception:
                pass

        return web.json_response({
            "ok": True,
            "count": len(seg_tensors),
            "saved_path": out_path,
            "width": int(panorama.shape[1]),
            "height": int(panorama.shape[0]),
        })


NODE_CLASS_MAPPINGS = {
    "QIBOImageStitchNode": QIBOImageStitchNode,
    "QIBOPanoramaGenNode": QIBOPanoramaGenNode,
    "QIBOPanoramaMergeNode": QIBOPanoramaMergeNode,
    "QIBOPanoramaGalleryNode": QIBOPanoramaGalleryNode,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBOImageStitchNode": "QIBO 图片拼接融合",
    "QIBOPanoramaGenNode": "QIBO 超长图生成",
    "QIBOPanoramaMergeNode": "QIBO 超长图合并",
    "QIBOPanoramaGalleryNode": "QIBO 超长图生成画廊",
}