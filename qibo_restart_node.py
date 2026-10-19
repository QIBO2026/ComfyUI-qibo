"""QIBO 重启 ComfyUI 节点。

前端 js/qibo_restart_node.js 会在节点上添加"重启 ComfyUI"按钮，
点击后调用后端 POST /qibo/restart_comfyui 完成重启。
"""


class QIBORestartNode:
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
        return ("此节点通过按钮重启 ComfyUI，点击节点上的「重启 ComfyUI」按钮即可。",)


NODE_CLASS_MAPPINGS = {
    "QIBORestartNode": QIBORestartNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBORestartNode": "qibo 重启 ComfyUI",
}