class QIBOTextInputNode:
    """文本输入节点：在节点上直接输入多行文本，输出 STRING。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"multiline": True, "default": ""}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "output_text"
    CATEGORY = "QIBO_API"

    def output_text(self, text=""):
        return (text,)


NODE_CLASS_MAPPINGS = {
    "QIBOTextInputNode": QIBOTextInputNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBOTextInputNode": "QIBO 文本输入",
}