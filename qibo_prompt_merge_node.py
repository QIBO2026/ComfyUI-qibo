class QIBOPromptMergeNode:
    """提示词合并节点：输入两个文本提示词，按指定分隔符合并为一个输出。"""

    _SEP_MAP = {"双换行": "\n\n", "单换行": "\n", "逗号": ", ", "空格": " ", "无": ""}

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt_a": ("STRING", {"multiline": True, "default": "", "forceInput": True}),
                "prompt_b": ("STRING", {"multiline": True, "default": "", "forceInput": True}),
                "separator": (["双换行", "单换行", "逗号", "空格", "无"], {"default": "双换行"}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("prompt",)
    FUNCTION = "merge_prompt"
    CATEGORY = "QIBO_API"

    def merge_prompt(self, prompt_a="", prompt_b="", separator="双换行"):
        a = (prompt_a or "").strip()
        b = (prompt_b or "").strip()
        sep = self._SEP_MAP.get(separator, "\n\n")
        if a and b:
            merged = f"{a}{sep}{b}"
        else:
            merged = a or b
        return (merged,)


NODE_CLASS_MAPPINGS = {
    "QIBOPromptMergeNode": QIBOPromptMergeNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBOPromptMergeNode": "QIBO 提示词合并",
}