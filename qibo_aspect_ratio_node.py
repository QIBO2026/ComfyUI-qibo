"""QIBO 宽高比分辨率选择节点：选择宽高比 + 基准大小，输出对应的 width/height。"""


ASPECT_RATIOS = {
    "1:1":  (2048, 2048),
    "4:3":  (2400, 1792),
    "3:4":  (1792, 2400),
    "3:2":  (2528, 1696),
    "2:3":  (1696, 2528),
    "16:9": (2752, 1536),
    "9:16": (1536, 2752),
}

RATIO_PAIRS = {
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


class QIBOAspectRatioNode:
    """选择宽高比，输出对应的分辨率 width / height。

    base_size = 0 时使用预设最佳分辨率；
    base_size > 0 时以该值为长边按比例计算，并对齐到 8 的倍数。
    """

    @classmethod
    def INPUT_TYPES(cls):
        keys = list(ASPECT_RATIOS.keys())
        return {
            "required": {
                "aspect_ratio": (keys, {"default": keys[0]}),
                "base_size": ("INT", {"default": 0, "min": 0, "max": 4096, "step": 8,
                                       "tooltip": "0=使用预设最佳分辨率；>0=以该值为长边按比例计算"}),
            }
        }

    RETURN_TYPES = ("INT", "INT")
    RETURN_NAMES = ("width", "height")
    FUNCTION = "get_resolution"
    CATEGORY = "QIBO_API"

    def get_resolution(self, aspect_ratio, base_size=0):
        if base_size and base_size > 0:
            rw, rh = RATIO_PAIRS.get(aspect_ratio, (1, 1))
            if rw >= rh:
                w = base_size
                h = _align8(base_size * rh / rw)
            else:
                h = base_size
                w = _align8(base_size * rw / rh)
            return (w, h)
        w, h = ASPECT_RATIOS.get(aspect_ratio, (2048, 2048))
        return (w, h)


NODE_CLASS_MAPPINGS = {
    "QIBOAspectRatioNode": QIBOAspectRatioNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBOAspectRatioNode": "QIBO 宽高比分辨率",
}
