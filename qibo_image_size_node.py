"""QIBO 图片尺寸节点：输入 IMAGE，输出其高和宽（像素）。"""


class QIBOImageSizeNode:
    """获取图片的高和宽。

    IMAGE tensor 形状为 [B, H, W, C]，取第 1、2 维即像素高、宽。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE", {"tooltip": "输入图片，输出其像素高和宽"}),
            }
        }

    RETURN_TYPES = ("INT", "INT")
    RETURN_NAMES = ("width", "height")
    FUNCTION = "get_size"
    CATEGORY = "QIBO_API"

    def get_size(self, image):
        _, h, w, _ = image.shape
        return (int(w), int(h))


NODE_CLASS_MAPPINGS = {
    "QIBOImageSizeNode": QIBOImageSizeNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBOImageSizeNode": "QIBO 图片尺寸",
}