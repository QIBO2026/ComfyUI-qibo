class QIBOGoohaiNoteNode:
    """qibo 注释节点：可编辑文本便签/注释节点。

    纯前端节点，无实际后端计算逻辑。
    双击节点编辑文本，右键滑动调整大小。
    支持字体大小、颜色、背景色、圆角、描边、行距、对齐等样式配置。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {},
        }

    RETURN_TYPES = ()
    FUNCTION = "note"
    CATEGORY = "QIBO_API"
    OUTPUT_NODE = True

    def note(self):
        return {"ui": {}, "result": ()}


NODE_CLASS_MAPPINGS = {
    "QIBOGoohaiNoteNode": QIBOGoohaiNoteNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBOGoohaiNoteNode": "qibo 注释",
}