class QIBONumberDisplayNode:
    """数字输入显示节点。

    number 为 FLOAT 输入（可直接在节点上输入，也可连线输入）。
    执行后把数字显示在只读显示框，并输出该数字。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "number": ("FLOAT", {"default": 0.0, "min": -1000000000.0, "max": 1000000000.0, "step": 0.01}),
            },
        }

    RETURN_TYPES = ("FLOAT",)
    RETURN_NAMES = ("number",)
    FUNCTION = "show_number"
    CATEGORY = "QIBO_API"
    OUTPUT_NODE = True

    def show_number(self, number=0.0):
        return {"ui": {"number": [number]}, "result": (number,)}


NODE_CLASS_MAPPINGS = {
    "QIBONumberDisplayNode": QIBONumberDisplayNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBONumberDisplayNode": "QIBO 数字显示",
}