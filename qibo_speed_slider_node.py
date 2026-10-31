"""QIBO 速度滑块节点。

输出一个 -10 ~ +10 的 FLOAT 值，前端用滑块条拖动调节。
"""


class QIBOSpeedSliderNode:
    CATEGORY = "QIBO"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "value": ("FLOAT", {"default": 0.0, "min": -10.0, "max": 10.0, "step": 0.1, "tooltip": "速度值，-10 ~ +10"}),
            }
        }

    RETURN_TYPES = ("FLOAT",)
    RETURN_NAMES = ("value",)
    FUNCTION = "run"

    def run(self, value):
        return (float(value),)


NODE_CLASS_MAPPINGS = {
    "QIBOSpeedSliderNode": QIBOSpeedSliderNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBOSpeedSliderNode": "qibo 速度滑块",
}