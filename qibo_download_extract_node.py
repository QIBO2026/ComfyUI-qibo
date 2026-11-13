"""QIBO 下载解压节点。

前端 js/qibo_download_extract_node.js 在节点上提供：
- 网址输入框：输入要下载的文件 URL
- 下载按钮：点击后从 URL 下载文件到 ComfyUI 根目录，实时显示下载进度
- 解压按钮：点击后将下载的文件解压，自动查找含多个 ComfyUI 文件夹的目录，
  将其内容移动到 ComfyUI/custom_nodes 目录
- 覆盖选项：勾选则移动时覆盖已存在文件，不勾选则跳过已存在文件

后端路由：
- POST /qibo/download_url_file  body {url} -> 启动后台下载线程，返回 task_id
- POST /qibo/download_progress  body {task_id} -> 查询下载进度
- POST /qibo/extract_to_custom_nodes  body {filename, overwrite} -> 解压并智能移动到 custom_nodes
"""

import os
import shutil
import zipfile
import tarfile
import threading
import urllib.request
import urllib.parse

try:
    from server import PromptServer
    from aiohttp import web
    SERVER_AVAILABLE = True
except ImportError:
    SERVER_AVAILABLE = False
    PromptServer = None
    web = None


_download_progress = {}
_download_lock = threading.Lock()


def _get_comfyui_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _download_thread(url, dest_path, task_id):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=300) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            with _download_lock:
                _download_progress[task_id] = {
                    "status": "downloading",
                    "total": total,
                    "downloaded": 0,
                    "filename": os.path.basename(dest_path),
                }
            downloaded = 0
            with open(dest_path, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    with _download_lock:
                        _download_progress[task_id]["downloaded"] = downloaded
        with _download_lock:
            _download_progress[task_id]["status"] = "done"
            _download_progress[task_id]["size"] = os.path.getsize(dest_path)
    except Exception as e:
        with _download_lock:
            _download_progress[task_id]["status"] = "error"
            _download_progress[task_id]["error"] = str(e)


def _find_comfyui_dirs(root_dir):
    """递归查找所有 ComfyUI 开头的目录（ComfyUI-xxx 或 ComfyUI_xxx），返回完整路径列表"""
    result = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        for d in dirnames:
            if d.startswith("ComfyUI") or d.startswith("comfyui"):
                result.append(os.path.join(dirpath, d))
    return result


def _move_single_item(src_path, dest_dir, overwrite=False):
    """将单个目录/文件移动到 dest_dir，返回 moved 或 skipped"""
    name = os.path.basename(src_path)
    dest_path = os.path.join(dest_dir, name)
    if os.path.exists(dest_path) and not overwrite:
        return "skipped", name
    if os.path.exists(dest_path) and overwrite:
        if os.path.isdir(dest_path):
            shutil.rmtree(dest_path)
        else:
            os.remove(dest_path)
    shutil.move(src_path, dest_path)
    return "moved", name


def register_server_routes():
    if not SERVER_AVAILABLE:
        return

    routes = PromptServer.instance.routes

    @routes.post("/qibo/download_url_file")
    async def download_url_file(request):
        try:
            data = await request.json()
            url = data.get("url", "").strip()
            if not url:
                return web.json_response({"error": "请输入网址"}, status=400)

            parsed = urllib.parse.urlparse(url)
            filename = os.path.basename(parsed.path)
            if not filename:
                filename = "downloaded_file"

            comfyui_root = _get_comfyui_root()
            dest_path = os.path.join(comfyui_root, filename)

            task_id = filename + "_" + str(threading.get_ident())
            thread = threading.Thread(
                target=_download_thread,
                args=(url, dest_path, task_id),
                daemon=True,
            )
            thread.start()

            return web.json_response({
                "success": True,
                "task_id": task_id,
                "filename": filename,
            })
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @routes.post("/qibo/download_progress")
    async def download_progress(request):
        try:
            data = await request.json()
            task_id = data.get("task_id", "")
            with _download_lock:
                info = _download_progress.get(task_id, {})
            if not info:
                return web.json_response({"error": "任务不存在"}, status=404)
            return web.json_response(info)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @routes.post("/qibo/extract_to_custom_nodes")
    async def extract_to_custom_nodes(request):
        try:
            data = await request.json()
            filename = data.get("filename", "").strip()
            overwrite = data.get("overwrite", False)

            comfyui_root = _get_comfyui_root()

            if not filename:
                for candidate in ["custom_nodes.zip", "custom_nodes_backup.tar.gz",
                                  "custom_nodes_backup.zip", "custom_nodes.tar.gz"]:
                    candidate_path = os.path.join(comfyui_root, candidate)
                    if os.path.exists(candidate_path):
                        filename = candidate
                        break
                if not filename:
                    for f in os.listdir(comfyui_root):
                        if f.endswith((".zip", ".tar.gz", ".tgz", ".tar.bz2", ".tar")):
                            filename = f
                            break
                if not filename:
                    return web.json_response({"error": "未找到压缩文件，请先下载"}, status=404)

            filepath = os.path.join(comfyui_root, filename)

            if not os.path.exists(filepath):
                return web.json_response({"error": f"文件不存在: {filepath}"}, status=404)

            custom_nodes_dir = os.path.join(comfyui_root, "custom_nodes")

            temp_extract_dir = os.path.join(comfyui_root, "_qibo_temp_extract")
            if os.path.exists(temp_extract_dir):
                shutil.rmtree(temp_extract_dir)
            os.makedirs(temp_extract_dir)

            if filepath.endswith(".zip"):
                with zipfile.ZipFile(filepath, "r") as zf:
                    zf.extractall(temp_extract_dir)
            elif filepath.endswith((".tar.gz", ".tgz", ".tar.bz2", ".tar", ".gz")):
                with tarfile.open(filepath, "r:*") as tf:
                    tf.extractall(temp_extract_dir)
            else:
                shutil.rmtree(temp_extract_dir)
                return web.json_response({"error": f"不支持的格式: {filepath}"}, status=400)

            comfyui_dirs = _find_comfyui_dirs(temp_extract_dir)

            moved = []
            skipped = []

            if comfyui_dirs:
                for d in comfyui_dirs:
                    status, name = _move_single_item(d, custom_nodes_dir, overwrite)
                    if status == "moved":
                        moved.append(name)
                    else:
                        skipped.append(name)
                action_desc = f"找到 {len(comfyui_dirs)} 个 ComfyUI 目录"
            else:
                src_dir = temp_extract_dir
                while True:
                    items = os.listdir(src_dir)
                    if len(items) == 1 and os.path.isdir(os.path.join(src_dir, items[0])):
                        src_dir = os.path.join(src_dir, items[0])
                        continue
                    break
                for item in os.listdir(src_dir):
                    src_item = os.path.join(src_dir, item)
                    status, name = _move_single_item(src_item, custom_nodes_dir, overwrite)
                    if status == "moved":
                        moved.append(name)
                    else:
                        skipped.append(name)
                action_desc = "直接移动"

            shutil.rmtree(temp_extract_dir)

            return web.json_response({
                "success": True,
                "action": action_desc,
                "moved_count": len(moved),
                "skipped_count": len(skipped),
                "moved": moved[:50],
                "skipped": skipped[:50],
            })
        except Exception as e:
            if os.path.exists(temp_extract_dir):
                shutil.rmtree(temp_extract_dir)
            return web.json_response({"error": str(e)}, status=500)


class QIBODownloadExtractNode:
    CATEGORY = "QIBO"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "url": ("STRING", {"default": "https://modelscope.cn/datasets/lanren/fahuo/resolve/master/custom_nodes_backup.tar.gz", "multiline": False}),
                "overwrite": ("BOOLEAN", {"default": False}),
            },
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "run"
    OUTPUT_NODE = True

    def run(self, url, overwrite):
        return ("此节点通过按钮下载和解压文件：输入网址后点「下载文件」按钮下载（实时显示进度），再点「解压到 custom_nodes」按钮解压。解压后自动查找含多个 ComfyUI 文件夹的目录，将内容移动到 custom_nodes。覆盖选项控制是否覆盖已存在文件。",)


NODE_CLASS_MAPPINGS = {
    "QIBODownloadExtractNode": QIBODownloadExtractNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBODownloadExtractNode": "qibo 下载解压",
}