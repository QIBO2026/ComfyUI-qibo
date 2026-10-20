"""QIBO 模型移动节点。

前端 js/qibo_model_move_node.js 在节点上添加"列举本地模型"按钮，
点击后列出 models 目录下已下载的模型，勾选后右键选目标目录，
点"移动选中"调用后端 POST /qibo/modelscope/move 完成移动。
"""


class QIBOModelMoveNode:
    CATEGORY = "QIBO"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {},
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "run"
    OUTPUT_NODE = True

    def run(self):
        return ("此节点通过按钮管理本地模型：点「列举本地模型」列出 models 目录已下载的模型，勾选后右键选目标目录，点「移动选中」即可移动。",)


NODE_CLASS_MAPPINGS = {
    "QIBOModelMoveNode": QIBOModelMoveNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBOModelMoveNode": "qibo 模型移动",
}