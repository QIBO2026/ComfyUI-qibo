"""QIBO 文本选择器节点：动态添加/删除文本，下拉选择输出对应文本。"""

import json


class QIBOTextSelectorNode:
    """上方输入文本并添加到列表，下方下拉选择输出对应文本，可删除选中项。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text_data": ("STRING", {"default": '{"items":[],"selected":0}'}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("selected_text",)
    FUNCTION = "select_text"
    CATEGORY = "QIBO_API"

    def select_text(self, text_data='{"items":[],"selected":0}'):
        try:
            data = json.loads(text_data) if text_data else {}
        except Exception:
            data = {}
        items = data.get("items", [])
        selected = int(data.get("selected", 0))
        if not items:
            return ("",)
        idx = max(0, min(len(items) - 1, selected))
        return (items[idx],)


NODE_CLASS_MAPPINGS = {
    "QIBOTextSelectorNode": QIBOTextSelectorNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBOTextSelectorNode": "QIBO 文本选择器",
}
