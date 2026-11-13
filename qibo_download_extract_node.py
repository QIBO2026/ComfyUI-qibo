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
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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


def _find_comfyui_cluster_dir(root_dir):
    """递归查找包含多个 ComfyUI 名称子目录的目录，返回该目录路径或 None"""
    for dirpath, dirnames, filenames in os.walk(root_dir):
        comfyui_dirs = [d for d in dirnames if "ComfyUI" in d or "comfyui" in d]
        if len(comfyui_dirs) >= 2:
            return dirpath
    return None


def _move_contents(src_dir, dest_dir, overwrite=False):
    """将 src_dir 下的所有内容移动到 dest_dir"""
    moved = []
    skipped = []
    for item in os.listdir(src_dir):
        src_item = os.path.join(src_dir, item)
        dest_item = os.path.join(dest_dir, item)
        if os.path.exists(dest_item) and not overwrite:
            skipped.append(item)
            continue
        if os.path.exists(dest_item) and overwrite:
            if os.path.isdir(dest_item):
                shutil.rmtree(dest_item)
            else:
                os.remove(dest_item)
        shutil.move(src_item, dest_item)
        moved.append(item)
    return {"moved": moved, "skipped": skipped}


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

            cluster_dir = _find_comfyui_cluster_dir(temp_extract_dir)

            if cluster_dir:
                result = _move_contents(cluster_dir, custom_nodes_dir, overwrite)
                action_desc = f"从 {os.path.relpath(cluster_dir, temp_extract_dir)} 移动"
            else:
                items = os.listdir(temp_extract_dir)
                if len(items) == 1:
                    sole = os.path.join(temp_extract_dir, items[0])
                    if os.path.isdir(sole) and items[0] == "custom_nodes":
                        result = _move_contents(sole, custom_nodes_dir, overwrite)
                        action_desc = "从 custom_nodes 目录提取内容"
                    else:
                        result = _move_contents(temp_extract_dir, custom_nodes_dir, overwrite)
                        action_desc = "直接移动"
                else:
                    result = _move_contents(temp_extract_dir, custom_nodes_dir, overwrite)
                    action_desc = "直接移动"

            shutil.rmtree(temp_extract_dir)

            return web.json_response({
                "success": True,
                "action": action_desc,
                "moved_count": len(result["moved"]),
                "skipped_count": len(result["skipped"]),
                "moved": result["moved"][:50],
                "skipped": result["skipped"][:50],
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