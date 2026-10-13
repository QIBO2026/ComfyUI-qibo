"""
QIBO 分块图片上传节点
在 ComfyUI 搜索面板中可搜到，提供图片上传入口。
大文件上传时前端 JS 自动分块，节点端负责加载图片并输出 IMAGE。
"""
import os
import numpy as np
import torch
from PIL import Image

try:
    from folder_paths import get_input_directory, get_filename_list, get_full_path
except Exception:
    get_input_directory = None
    get_filename_list = None
    get_full_path = None


def _list_images():
    if get_filename_list:
        try:
            return get_filename_list("input")
        except Exception:
            pass
    input_dir = os.path.join(os.path.dirname(__file__), "..", "..", "input")
    input_dir = os.path.abspath(input_dir)
    if not os.path.isdir(input_dir):
        return []
    exts = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff")
    return sorted([f for f in os.listdir(input_dir) if f.lower().endswith(exts)])


def _load_image_file(filename):
    if get_full_path:
        try:
            path = get_full_path("input", filename)
        except Exception:
            path = None
    if not path:
        input_dir = os.path.join(os.path.dirname(__file__), "..", "..", "input")
        path = os.path.join(os.path.abspath(input_dir), filename)
    if not os.path.exists(path):
        raise Exception(f"图片不存在: {filename}")

    img = Image.open(path)
    if img.mode != "RGB":
        img = img.convert("RGB")
    img_np = np.array(img).astype(np.float32) / 255.0
    return torch.from_numpy(img_np)[None,]


class QIBOChunkedImageUploadNode:
    """分块图片上传：在搜索面板搜 QIBO 即可找到。大文件自动分块上传后加载为 IMAGE。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": (sorted(_list_images()), {"image_upload": True}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "load_image"
    CATEGORY = "QIBO_API"

    def load_image(self, image):
        return (_load_image_file(image),)

    @classmethod
    def IS_CHANGED(cls, image):
        return float("NaN")


NODE_CLASS_MAPPINGS = {"QIBOChunkedImageUploadNode": QIBOChunkedImageUploadNode}
NODE_DISPLAY_NAME_MAPPINGS = {"QIBOChunkedImageUploadNode": "QIBO 分块图片上传"}