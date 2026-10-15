class QIBOShowTextNode:
    """文本显示节点。

    text 为 forceInput 输入端口（不在节点上画原生 widget，避免被连线移除）。
    前端用 ComfyWidgets.STRING 画一个只读 multiline widget 始终可见，
    执行后把接收到的文本写入该 widget。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"multiline": True, "default": "", "forceInput": True}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "show_text"
    CATEGORY = "QIBO_API"
    OUTPUT_NODE = True

    def show_text(self, text=""):
        text = text or ""
        return {"ui": {"text": [text]}, "result": (text,)}


NODE_CLASS_MAPPINGS = {
    "QIBOShowTextNode": QIBOShowTextNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBOShowTextNode": "QIBO 文本显示",
}
