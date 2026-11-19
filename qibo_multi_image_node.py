"""
QIBO 多图载入节点
移植自 TaiYang_MultiImage，支持从 input 和 output 目录读取图片。
16 路 IMAGE 输出，按顺序喂给各多图接入节点。

图片路径格式：
  - "xxx.png"          → 从 input 目录读取（默认）
  - "output/xxx.png"   → 从 output 目录读取
"""
import json
import math
import os

import numpy as np
import torch
from PIL import Image

try:
    import folder_paths
    from comfy.utils import common_upscale
except Exception:
    folder_paths = None
    common_upscale = None

MAX_IMAGES = 16


class QIBOMultiImageLoader:
    """多图参考输入节点：16 路 IMAGE 输出，支持从 input/output 目录读取图片。

    前端会自动把本节点的输出连到目标节点的 images.image_N 或 ref_images.ref_image_N 槽位，
    空槽位返回 None，避免把 64x64 黑图当成参考图送进模型。
    """

    def __init__(self):
        if folder_paths:
            self.input_dir = folder_paths.get_input_directory()
            self.output_dir = folder_paths.get_output_directory()
        else:
            base = os.path.join(os.path.dirname(__file__), "..", "..")
            self.input_dir = os.path.abspath(os.path.join(base, "input"))
            self.output_dir = os.path.abspath(os.path.join(base, "output"))

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image_files": ("STRING", {"default": "[]", "multiline": False}),
                "auto_link": (["自动", "关闭"], {"default": "自动"}),
                "upscale_method": (["nearest-exact", "bilinear", "area", "bicubic", "lanczos"], {"default": "bilinear"}),
                "megapixels": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 16.0, "step": 0.01}),
                "resolution_steps": ("INT", {"default": 32, "min": 1, "max": 256}),
            },
        }

    RETURN_TYPES = tuple(["IMAGE"] * MAX_IMAGES)
    RETURN_NAMES = tuple([f"image_{i + 1}" for i in range(MAX_IMAGES)])
    FUNCTION = "load_images"
    CATEGORY = "QIBO_API"

    def _parse_files(self, image_files):
        if isinstance(image_files, (list, tuple)):
            raw = list(image_files)
        else:
            try:
                raw = json.loads(image_files or "[]")
            except Exception:
                raw = []
            if not isinstance(raw, list):
                raw = []
        return [f for f in raw if isinstance(f, str) and f.strip()][:MAX_IMAGES]

    def _resolve_path(self, rel_path):
        """解析图片路径，支持 output/ 前缀标识来自 output 目录。"""
        rel = rel_path.replace("\\", "/").lstrip("/")
        if rel.startswith("output/"):
            actual_rel = rel[7:]
            base_dir = os.path.abspath(self.output_dir)
            path = os.path.abspath(os.path.join(base_dir, actual_rel))
            if os.path.commonpath([base_dir, path]) != base_dir:
                raise ValueError(f"非法路径: {rel_path}")
            return path
        base_dir = os.path.abspath(self.input_dir)
        path = os.path.abspath(os.path.join(base_dir, rel))
        if os.path.commonpath([base_dir, path]) != base_dir:
            raise ValueError(f"非法路径: {rel_path}")
        return path

    def _load_one(self, rel_path):
        path = self._resolve_path(rel_path)
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
        img = Image.open(path).convert("RGB")
        arr = np.array(img).astype(np.float32) / 255.0
        return torch.from_numpy(arr)[None,]

    def _scale_to_total_pixels(self, img, upscale_method, megapixels, resolution_steps):
        """把单张图缩放到总像素数 = megapixels x 1024^2，等价内置 ImageScaleToTotalPixels。"""
        if megapixels is None or megapixels <= 0:
            return img
        if common_upscale is None:
            return img
        samples = img.movedim(-1, 1)
        total = float(megapixels) * 1024 * 1024
        height = samples.shape[2]
        width = samples.shape[3]
        if height <= 0 or width <= 0:
            return img
        scale_by = math.sqrt(total / (width * height))
        steps = max(1, int(resolution_steps or 32))
        new_w = max(steps, int(round(width * scale_by / steps)) * steps)
        new_h = max(steps, int(round(height * scale_by / steps)) * steps)
        out = common_upscale(samples, new_w, new_h, upscale_method, "disabled")
        return out.movedim(1, -1)

    def load_images(self, image_files, auto_link="自动", upscale_method="bilinear",
                    megapixels=0.0, resolution_steps=32):
        files = self._parse_files(image_files)
        results = []
        for i in range(MAX_IMAGES):
            if i < len(files):
                try:
                    img = self._load_one(files[i])
                    img = self._scale_to_total_pixels(img, upscale_method, megapixels, resolution_steps)
                    results.append(img)
                except Exception as e:
                    print(f"[QIBOMultiImageLoader] 读取失败 {files[i]}: {e}")
                    results.append(None)
            else:
                results.append(None)
        return tuple(results)


NODE_CLASS_MAPPINGS = {
    "QIBOMultiImageLoader": QIBOMultiImageLoader,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBOMultiImageLoader": "QIBO 多图载入",
}