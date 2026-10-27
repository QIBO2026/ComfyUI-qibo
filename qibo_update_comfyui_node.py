"""QIBO 一键更新 ComfyUI 节点。

前端 js/qibo_update_comfyui_node.js 会在节点上添加"一键更新 ComfyUI"按钮，
点击后调用后端 POST /qibo/update_comfyui 在 ComfyUI 根目录执行 git pull +
pip install -r requirements.txt，并轮询 /qibo/update_comfyui_progress 显示实时进度。
"""


class QIBOUpdateComfyUINode:
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
        return ("此节点通过按钮一键更新 ComfyUI，点击节点上的「一键更新 ComfyUI」按钮即可。",)


NODE_CLASS_MAPPINGS = {
    "QIBOUpdateComfyUINode": QIBOUpdateComfyUINode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBOUpdateComfyUINode": "QIBO 一键更新 ComfyUI",
}