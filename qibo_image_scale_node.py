import torch
import numpy as np
from PIL import Image


class QIBOImageScaleNode:
    """按长边等比缩放图片，避免超过 ModelScope API 2048x2048 输入限制。
    输出缩放后的图像及宽高，宽高可直连编辑节点设置输出尺寸。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "max_size": ("INT", {"default": 2048, "min": 64, "max": 4096, "step": 8}),
                "method": (["lanczos", "bilinear", "bicubic", "nearest"], {"default": "lanczos"}),
                "only_shrink": ("BOOLEAN", {"default": True, "label_on": "仅缩小", "label_off": "允许放大"}),
            }
        }

    RETURN_TYPES = ("IMAGE", "INT", "INT")
    RETURN_NAMES = ("image", "width", "height")
    FUNCTION = "scale_image"
    CATEGORY = "QIBO_API"

    def scale_image(self, image, max_size=2048, method="lanczos", only_shrink=True):
        if len(image.shape) == 4:
            batch = image
        else:
            batch = image[None,]

        resample_map = {
            "lanczos": Image.LANCZOS,
            "bilinear": Image.BILINEAR,
            "bicubic": Image.BICUBIC,
            "nearest": Image.NEAREST,
        }
        resample = resample_map.get(method, Image.LANCZOS)

        out_tensors = []
        new_w, new_h = 0, 0
        for idx, img in enumerate(batch):
            img_np = 255. * img.cpu().numpy()
            img_pil = Image.fromarray(np.clip(img_np, 0, 255).astype(np.uint8))

            w, h = img_pil.size
            longest = max(w, h)
            new_w, new_h = w, h
            if longest > max_size:
                ratio = max_size / longest
                new_w = int(w * ratio)
                new_h = int(h * ratio)
                img_pil = img_pil.resize((new_w, new_h), resample)
                print(f"📐 QIBO图片缩放[{idx}]: {w}x{h} → {new_w}x{new_h}")
            elif not only_shrink and longest < max_size:
                ratio = max_size / longest
                new_w = int(w * ratio)
                new_h = int(h * ratio)
                img_pil = img_pil.resize((new_w, new_h), resample)
                print(f"📐 QIBO图片缩放[{idx}](放大): {w}x{h} → {new_w}x{new_h}")
            else:
                print(f"📐 QIBO图片缩放[{idx}]: 保持原尺寸 {w}x{h}")

            out_np = np.array(img_pil).astype(np.float32) / 255.0
            out_tensors.append(torch.from_numpy(out_np)[None,])

        batch_tensor = torch.cat(out_tensors, dim=0)
        return (batch_tensor, new_w, new_h)


class QIBOImageScaleBatchNode:
    """批量缩放节点：一个节点处理多张图片，输出多张缩放后的图片，直接连到编辑节点的各输入口。"""

    @classmethod
    def INPUT_TYPES(cls):
        optional = {}
        for i in range(1, 11):
            optional[f"image_{i}"] = ("IMAGE",)
        return {
            "required": {
                "max_size": ("INT", {"default": 2048, "min": 64, "max": 4096, "step": 8}),
                "method": (["lanczos", "bilinear", "bicubic", "nearest"], {"default": "lanczos"}),
                "only_shrink": ("BOOLEAN", {"default": True, "label_on": "仅缩小", "label_off": "允许放大"}),
            },
            "optional": optional,
        }

    RETURN_TYPES = ("IMAGE",) * 10
    RETURN_NAMES = tuple(f"image_{i}" for i in range(1, 11))
    FUNCTION = "scale_batch"
    CATEGORY = "QIBO_API"

    def scale_batch(self, max_size=2048, method="lanczos", only_shrink=True,
                    image_1=None, image_2=None, image_3=None, image_4=None,
                    image_5=None, image_6=None, image_7=None, image_8=None, image_9=None, image_10=None):
        resample_map = {
            "lanczos": Image.LANCZOS, "bilinear": Image.BILINEAR,
            "bicubic": Image.BICUBIC, "nearest": Image.NEAREST,
        }
        resample = resample_map.get(method, Image.LANCZOS)
        inputs = [image_1, image_2, image_3, image_4, image_5, image_6, image_7, image_8, image_9, image_10]
        results = []
        for i in range(10):
            if inputs[i] is not None:
                results.append(self._scale_one(inputs[i], max_size, resample, only_shrink, i))
            else:
                results.append(None)
        return tuple(results)

    @staticmethod
    def _scale_one(image, max_size, resample, only_shrink, idx):
        batch = image if len(image.shape) == 4 else image[None,]
        out_tensors = []
        for img in batch:
            img_np = 255. * img.cpu().numpy()
            img_pil = Image.fromarray(np.clip(img_np, 0, 255).astype(np.uint8))
            w, h = img_pil.size
            longest = max(w, h)
            if longest > max_size:
                ratio = max_size / longest
                nw, nh = int(w * ratio), int(h * ratio)
                img_pil = img_pil.resize((nw, nh), resample)
                print(f"📐 QIBO批量缩放[{idx}]: {w}x{h} → {nw}x{nh}")
            elif not only_shrink and longest < max_size:
                ratio = max_size / longest
                nw, nh = int(w * ratio), int(h * ratio)
                img_pil = img_pil.resize((nw, nh), resample)
                print(f"📐 QIBO批量缩放[{idx}](放大): {w}x{h} → {nw}x{nh}")
            else:
                print(f"📐 QIBO批量缩放[{idx}]: 保持 {w}x{h}")
            out_np = np.array(img_pil).astype(np.float32) / 255.0
            out_tensors.append(torch.from_numpy(out_np)[None,])
        return torch.cat(out_tensors, dim=0)


NODE_CLASS_MAPPINGS = {
    "QIBOImageScaleNode": QIBOImageScaleNode,
    "QIBOImageScaleBatchNode": QIBOImageScaleBatchNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBOImageScaleNode": "QIBO 图片缩放",
    "QIBOImageScaleBatchNode": "QIBO 图片批量缩放",
}