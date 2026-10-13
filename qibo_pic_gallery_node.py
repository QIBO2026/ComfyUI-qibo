"""QIBO 图片画廊节点：显示 input/qibo_in_pic 或 output/qibo_out_pic 目录下所有图片，按倒序排列。

元数据采用统一 JSON 文件：
- output 画廊：output/qibo_out_pic/qibo_out_pic.json
- input 画廊：input/qibo_in_pic/qibo_in_pic.json

JSON 结构：
{
  "images": [
    {
      "filename": "qibo_xxx.png",
      "model": "...",
      "prompt": "...",
      "timestamp": "2026-09-21 12:34:56",
      "width": 1024, "height": 1024, "ratio": "1:1",
      "ref_images": [{"index": 1, "base64": "data:image/jpeg;base64,..."}]
    }
  ]
}
"""

import os
import glob
import json
import time
import math
import torch
import numpy as np
from PIL import Image

try:
    import folder_paths
except Exception:
    folder_paths = None

try:
    from server import PromptServer
    from aiohttp import web
    _SERVER_OK = True
except Exception:
    _SERVER_OK = False
    PromptServer = None
    web = None


def _resolve_gallery_dir(gallery_type):
    """根据 'output' 或 'input' 返回 qibo_out_pic / qibo_in_pic 的绝对路径。"""
    if folder_paths:
        base = folder_paths.get_directory_by_type(gallery_type)
    else:
        base = os.path.join(os.path.dirname(__file__), "..", "..", gallery_type)
    sub = "qibo_out_pic" if gallery_type == "output" else "qibo_in_pic"
    return os.path.join(base, sub)


def _resolve_meta_json_path(gallery_type):
    """统一元数据 JSON 文件路径。"""
    directory = _resolve_gallery_dir(gallery_type)
    filename = "qibo_out_pic.json" if gallery_type == "output" else "qibo_in_pic.json"
    return os.path.join(directory, filename)


def _resolve_index_json_path():
    """输入画廊序号映射 JSON 路径。"""
    directory = _resolve_gallery_dir("input")
    return os.path.join(directory, "qibo_in_pic_index.json")


def _load_index_map():
    """读取序号映射 {"1": "filename", "2": "filename", ...}。"""
    path = _resolve_index_json_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k): v for k, v in data.items()}
    except Exception:
        pass
    return {}


def _save_index_map(index_map):
    """写入序号映射 JSON。"""
    path = _resolve_index_json_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(index_map, f, ensure_ascii=False, indent=2)


def _list_input_items_with_index(directory):
    """输入画廊：按序号映射正序返回，自动为新文件分配序号（优先复用空缺）。"""
    os.makedirs(directory, exist_ok=True)
    index_map = _load_index_map()
    exts = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
    if not os.path.isdir(directory):
        return []
    existing_files = set(f for f in os.listdir(directory) if f.lower().endswith(exts))

    for num_str, fname in list(index_map.items()):
        if fname not in existing_files:
            del index_map[num_str]

    mapped_files = set(index_map.values())
    unmapped = [f for f in existing_files if f not in mapped_files]
    unmapped.sort(key=lambda f: os.path.getmtime(os.path.join(directory, f)))

    all_nums = set(int(n) for n in index_map.keys())
    candidate = 1
    for fname in unmapped:
        while candidate in all_nums:
            candidate += 1
        index_map[str(candidate)] = fname
        all_nums.add(candidate)
        candidate += 1

    _save_index_map(index_map)

    items = []
    for num in sorted(all_nums):
        fname = index_map.get(str(num))
        if fname and fname in existing_files:
            items.append({
                "index": num,
                "filename": fname,
                "prompt": "",
                "model": "",
                "timestamp": "",
                "width": 0,
                "height": 0,
                "ratio": "",
            })
    return items


def _load_meta_json(gallery_type):
    """读取统一元数据 JSON，返回 {'images': [...]}。"""
    path = _resolve_meta_json_path(gallery_type)
    if not os.path.isfile(path):
        return {"images": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "images" not in data:
            return {"images": []}
        return data
    except Exception:
        return {"images": []}


def _save_meta_json(gallery_type, data):
    """写入统一元数据 JSON。"""
    path = _resolve_meta_json_path(gallery_type)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _append_meta_record(gallery_type, record):
    """向统一 JSON 追加一条记录（最新在前）。"""
    data = _load_meta_json(gallery_type)
    data["images"].insert(0, record)
    _save_meta_json(gallery_type, data)


def _list_gallery_items(gallery_type):
    """枚举指定画廊目录下所有图片。input 按序号映射正序，output 按文件名倒序。"""
    directory = _resolve_gallery_dir(gallery_type)
    os.makedirs(directory, exist_ok=True)

    if gallery_type == "input":
        return _list_input_items_with_index(directory)

    meta = _load_meta_json(gallery_type)
    meta_map = {rec.get("filename", ""): rec for rec in meta.get("images", [])}
    items = []
    if not os.path.isdir(directory):
        return items
    exts = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
    files = [f for f in os.listdir(directory) if f.lower().endswith(exts)]
    files.sort(key=lambda f: os.path.getmtime(os.path.join(directory, f)), reverse=True)
    for idx, fname in enumerate(files):
        rec = meta_map.get(fname, {})
        items.append({
            "index": idx + 1,
            "filename": fname,
            "prompt": rec.get("prompt", ""),
            "model": rec.get("model", ""),
            "timestamp": rec.get("timestamp", ""),
            "width": rec.get("width", 0),
            "height": rec.get("height", 0),
            "ratio": rec.get("ratio", ""),
        })
    return items


if _SERVER_OK:
    _routes = PromptServer.instance.routes

    @_routes.get("/qibo/pic_gallery/list")
    async def qibo_pic_gallery_list(request):
        gallery_type = request.rel_url.query.get("type", "output")
        if gallery_type not in ("output", "input"):
            gallery_type = "output"
        limit = request.rel_url.query.get("limit")
        offset = request.rel_url.query.get("offset")
        limit = int(limit) if limit and limit.isdigit() else None
        offset = int(offset) if offset and offset.isdigit() else 0
        items = _list_gallery_items(gallery_type)
        total = len(items)
        if limit is not None:
            items = items[offset:offset + limit]
        return web.json_response({"items": items, "type": gallery_type, "total": total})

    @_routes.post("/qibo/pic_gallery/delete")
    async def qibo_pic_gallery_delete(request):
        try:
            data = await request.json()
        except Exception:
            data = {}
        gallery_type = data.get("type", "input")
        filename = data.get("filename", "")
        if not filename or gallery_type not in ("input", "output"):
            return web.json_response({"ok": False, "error": "参数无效"})
        directory = _resolve_gallery_dir(gallery_type)
        filepath = os.path.join(directory, filename)
        if os.path.isfile(filepath):
            try:
                os.remove(filepath)
            except Exception as e:
                return web.json_response({"ok": False, "error": str(e)})
        if gallery_type == "input":
            index_map = _load_index_map()
            for num_str, fname in list(index_map.items()):
                if fname == filename:
                    del index_map[num_str]
            _save_index_map(index_map)
        else:
            meta = _load_meta_json("output")
            meta["images"] = [r for r in meta.get("images", []) if r.get("filename") != filename]
            _save_meta_json("output", meta)
        return web.json_response({"ok": True})

    @_routes.post("/qibo/pic_gallery/clear")
    async def qibo_pic_gallery_clear(request):
        """清空指定画廊目录下所有图片与映射/元数据 JSON。
        input 画廊：删除全部图片 + qibo_in_pic_index.json + qibo_in_pic.json，
                    重新上传时 _list_input_items_with_index 会自动重建映射。
        output 画廊：删除全部图片 + qibo_out_pic.json。
        """
        try:
            data = await request.json()
        except Exception:
            data = {}
        gallery_type = data.get("type", "input")
        if gallery_type not in ("input", "output"):
            return web.json_response({"ok": False, "error": "参数无效"})
        directory = _resolve_gallery_dir(gallery_type)
        os.makedirs(directory, exist_ok=True)
        exts = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
        removed = 0
        for fname in os.listdir(directory):
            if fname.lower().endswith(exts):
                try:
                    os.remove(os.path.join(directory, fname))
                    removed += 1
                except Exception:
                    pass
        if gallery_type == "input":
            for json_name in ("qibo_in_pic_index.json", "qibo_in_pic.json"):
                jp = os.path.join(directory, json_name)
                if os.path.isfile(jp):
                    try:
                        os.remove(jp)
                    except Exception:
                        pass
        else:
            meta_path = _resolve_meta_json_path("output")
            if os.path.isfile(meta_path):
                try:
                    os.remove(meta_path)
                except Exception:
                    pass
        return web.json_response({"ok": True, "removed": removed})


def _encode_ref_images(ref_images):
    """将 ref_images (IMAGE batch) 缩放后转 base64 列表。"""
    if ref_images is None:
        return []
    import io as _io
    import base64 as _b64
    ref_batch = ref_images if len(ref_images.shape) == 4 else ref_images.unsqueeze(0)
    out = []
    for idx in range(ref_batch.shape[0]):
        ref_t = ref_batch[idx]
        ref_np = (255.0 * ref_t.cpu().numpy()).clip(0, 255).astype(np.uint8)
        ref_pil = Image.fromarray(ref_np)
        max_side = 512
        rw, rh = ref_pil.size
        if max(rw, rh) > max_side:
            scale = max_side / max(rw, rh)
            ref_pil = ref_pil.resize((int(rw * scale), int(rh * scale)), Image.LANCZOS)
        buf = _io.BytesIO()
        ref_pil.save(buf, format="JPEG", quality=85)
        b64 = "data:image/jpeg;base64," + _b64.b64encode(buf.getvalue()).decode("ascii")
        out.append({"index": idx + 1, "base64": b64})
    return out


def _decode_ref_images(ref_list):
    """从 ref_images 列表解码出 IMAGE tensor batch。"""
    if not ref_list:
        return None
    import io as _io
    import base64 as _b64
    tensors = []
    for ref in ref_list:
        b64 = ref.get("base64", "")
        if "," in b64:
            b64 = b64.split(",", 1)[1]
        try:
            img_pil = Image.open(_io.BytesIO(_b64.b64decode(b64))).convert("RGB")
            img_np = np.array(img_pil).astype(np.float32) / 255.0
            tensors.append(torch.from_numpy(img_np))
        except Exception:
            pass
    return torch.stack(tensors) if tensors else None


def _save_image_and_meta(gallery_type, image, prompt, model, ref_images=None, filename_override=None):
    """保存图片到指定画廊目录，并追加元数据到统一 JSON。返回 (filename, w, h) 或 None。"""
    if image is None:
        print(f"⚠️ [QIBO 画廊] image 输入为 None，未保存图片。请确认已将上游节点的 IMAGE 输出连接到本节点的 image 输入端口。")
        return None
    try:
        directory = _resolve_gallery_dir(gallery_type)
        os.makedirs(directory, exist_ok=True)
        img_tensor = image[0] if len(image.shape) == 4 else image
        img_np = (255.0 * img_tensor.cpu().numpy()).clip(0, 255).astype(np.uint8)
        img_pil = Image.fromarray(img_np)
        w, h = img_pil.size
        now = time.time()
        if filename_override:
            filename = filename_override
            base, ext = os.path.splitext(filename)
            counter = 1
            while os.path.exists(os.path.join(directory, filename)):
                filename = f"{base}_{counter}{ext}"
                counter += 1
        else:
            ts = time.strftime("%Y%m%d_%H%M%S", time.localtime(now))
            ms = int((now - int(now)) * 1000)
            filename = f"qibo_{ts}_{ms:03d}.png"
        # 原子写入：先写临时文件并 fsync 落盘，再 os.replace 原子替换。
        # 避免 send_sync 通知前端后，/view 接口读到半截 PNG 而报 "image file is truncated"。
        final_path = os.path.join(directory, filename)
        tmp_path = final_path + ".tmp"
        with open(tmp_path, "wb") as f:
            img_pil.save(f, format="PNG")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, final_path)
        gcd = math.gcd(w, h)
        ratio = f"{w // gcd}:{h // gcd}" if gcd > 0 else f"{w}:{h}"
        record = {
            "filename": filename,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
            "model": model or "",
            "prompt": prompt or "",
            "width": w,
            "height": h,
            "ratio": ratio,
            "ref_images": _encode_ref_images(ref_images),
        }
        _append_meta_record(gallery_type, record)
        print(f"✅ [QIBO 画廊] 已保存: {filename} ({w}x{h}) 并追加元数据到统一 JSON @ {directory}")
        if _SERVER_OK:
            try:
                PromptServer.instance.send_sync("qibo_pic_gallery_update", {
                    "type": gallery_type, "filename": filename
                })
            except Exception:
                pass
        return filename, w, h
    except Exception as e:
        print(f"❌ [QIBO 画廊] 保存失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def _load_images_from_dir(directory, reverse=True, draw_index=False):
    if not os.path.isdir(directory):
        return []
    exts = ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.bmp")
    files = []
    for ext in exts:
        files.extend(glob.glob(os.path.join(directory, ext)))
    files = sorted(set(files), reverse=reverse)
    from PIL import ImageDraw, ImageFont
    tensors = []
    target_size = None
    for f in files:
        try:
            img = Image.open(f).convert("RGB")
            if target_size is None:
                target_size = img.size
            elif img.size != target_size:
                img = img.resize(target_size, Image.LANCZOS)
            if draw_index:
                draw = ImageDraw.Draw(img)
                idx = len(tensors) + 1
                label = f"图{idx}"
                font_size = max(20, img.size[0] // 12)
                try:
                    font = ImageFont.truetype("arial.ttf", font_size)
                except Exception:
                    font = ImageFont.load_default()
                bbox = draw.textbbox((0, 0), label, font=font)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                x = img.size[0] - tw - 8
                y = 8
                draw.rectangle([x - 4, y - 2, x + tw + 4, y + th + 2], fill=(0, 0, 0))
                draw.text((x, y), label, fill=(255, 255, 0), font=font)
            img_np = np.array(img).astype(np.float32) / 255.0
            tensors.append(torch.from_numpy(img_np))
        except Exception:
            pass
    return tensors


class QIBOInputPicGalleryNode:
    """显示 input/qibo_in_pic 目录下所有图片，按序号映射正序排列（先上传在前），
    右上角标注图编号。仅输出 IMAGE 图片接口。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {}}

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("images", "filenames")
    FUNCTION = "load_gallery"
    CATEGORY = "QIBO_API"

    def load_gallery(self):
        directory = _resolve_gallery_dir("input")
        os.makedirs(directory, exist_ok=True)
        items = _list_input_items_with_index(directory)
        tensors = []
        filenames = []
        target_size = None
        for item in items:
            fpath = os.path.join(directory, item["filename"])
            try:
                img = Image.open(fpath).convert("RGB")
                if target_size is None:
                    target_size = img.size
                elif img.size != target_size:
                    img = img.resize(target_size, Image.LANCZOS)
                img_np = np.array(img).astype(np.float32) / 255.0
                tensors.append(torch.from_numpy(img_np))
                filenames.append(item["filename"])
            except Exception:
                pass
        images_out = torch.stack(tensors) if tensors else torch.zeros((1, 64, 64, 3), dtype=torch.float32)
        filenames_out = "\n".join(filenames)
        return (images_out, filenames_out)


class QIBOOutputPicGalleryNode:
    """保存传入图片到 output/qibo_out_pic 并追加元数据到 qibo_out_pic.json。
    仅接收一条 qibodata 连线（包含 image/prompt/model/ref_images），无输出端口。
    双击画廊图片由前端 lightbox 直接预览放大，不触发节点执行。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {},
            "optional": {
                "qibodata": ("QIBODATA",),
            }
        }

    RETURN_TYPES = ()
    OUTPUT_NODE = True
    FUNCTION = "save_gallery"
    CATEGORY = "QIBO_API"

    def save_gallery(self, qibodata=None):
        if qibodata is None:
            print(f"⚠️ [QIBO 画廊] qibodata 输入为 None，未保存图片。请确认已将上游节点的 qibodata 输出连接到本节点的 qibodata 输入端口。")
            return {}
        image = qibodata.get("image")
        prompt = qibodata.get("prompt", "")
        model = qibodata.get("model", "")
        ref_images = qibodata.get("ref_images")
        _save_image_and_meta("output", image, prompt, model, ref_images)
        return {}


class QIBOSavePicWithMetaNode:
    """已废弃：保留空类以兼容旧工作流加载，不再注册到 NODE_CLASS_MAPPINGS。"""
    pass


NODE_CLASS_MAPPINGS = {
    "QIBOInputPicGalleryNode": QIBOInputPicGalleryNode,
    "QIBOOutputPicGalleryNode": QIBOOutputPicGalleryNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBOInputPicGalleryNode": "QIBO 输入图片画廊",
    "QIBOOutputPicGalleryNode": "QIBO 输出图片画廊",
}
