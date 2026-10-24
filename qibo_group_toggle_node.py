"""QIBO 组开关节点。

无输入无输出。前端 js/qibo_group_toggle_node.js 会扫描当前工作流的分组，
在节点上把每个组列成一行：组名 + 开关。
开关打开 = 组内所有节点启用(mode=ALWAYS)；开关关闭 = 组内所有节点
旁路(mode=BYPASS，数据直通不执行)，同时写入 group.mode 与 ComfyUI 原生
组 Bypass/Mute 状态一致。开关状态随工作流保存(节点 mode 天然序列化)。
"""


class QIBOGroupToggleNode:
    CATEGORY = "QIBO"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {},
        }

    RETURN_TYPES = ()
    FUNCTION = "run"

    def run(self):
        return ()


NODE_CLASS_MAPPINGS = {
    "QIBOGroupToggleNode": QIBOGroupToggleNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBOGroupToggleNode": "qibo 组开关",
}