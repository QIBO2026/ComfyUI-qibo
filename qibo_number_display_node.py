class QIBONumberDisplayNode:
    """任何值输入显示节点。

    value 为 * 通配类型 forceInput 输入端口，可接 INT/FLOAT/STRING 等任何连线。
    执行后把值转换成文本，前端用只读 multiline widget 显示。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "value": ("*", {"forceInput": True}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "show_value"
    CATEGORY = "QIBO_API"
    OUTPUT_NODE = True

    def show_value(self, value=None):
        text = self._to_text(value)
        return {"ui": {"text": [text]}, "result": (text,)}

    @staticmethod
    def _to_text(value):
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if hasattr(value, "shape"):
            try:
                return f"<{type(value).__name__} shape={tuple(value.shape)}>"
            except Exception:
                pass
        if isinstance(value, dict):
            try:
                import json
                return json.dumps(value, ensure_ascii=False, indent=2, default=str)
            except Exception:
                return str(value)
        if isinstance(value, (list, tuple)):
            return "\n".join(str(v) for v in value)
        return str(value)


NODE_CLASS_MAPPINGS = {
    "QIBONumberDisplayNode": QIBONumberDisplayNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBONumberDisplayNode": "QIBO 任何值输入",
}