"""
QIBO 文件上传节点
上传任意文件到 input 目录，输出完整路径（STRING）。
用 image_upload widget 复用 ComfyUI 内置上传按钮，下拉列出 input 目录所有文件。
"""
import os

try:
    from folder_paths import get_input_directory, get_full_path
except Exception:
    get_input_directory = None
    get_full_path = None


def _input_dir():
    if get_input_directory:
        try:
            return get_input_directory()
        except Exception:
            pass
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "input"))


def _list_files():
    d = _input_dir()
    if not os.path.isdir(d):
        return []
    return sorted([f for f in os.listdir(d) if os.path.isfile(os.path.join(d, f))])


class QIBOFileUploadNode:
    """文件上传：上传任意文件，输出完整路径。在搜索面板搜 QIBO 即可找到。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "file": (sorted(_list_files()), {"image_upload": True, "tooltip": "点击上传按钮选择文件，或从下拉列表选择已上传文件。文件存于 ComfyUI 的 input 目录。"}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("file_path",)
    FUNCTION = "get_path"
    CATEGORY = "QIBO_API"

    def get_path(self, file):
        d = _input_dir()
        path = os.path.join(d, file)
        if not os.path.exists(path):
            raise Exception(f"文件不存在: {path}")
        print(f"📎 文件上传节点: {path}")
        return (path,)

    @classmethod
    def IS_CHANGED(cls, file):
        return float("NaN")


NODE_CLASS_MAPPINGS = {"QIBOFileUploadNode": QIBOFileUploadNode}
NODE_DISPLAY_NAME_MAPPINGS = {"QIBOFileUploadNode": "QIBO 文件上传"}