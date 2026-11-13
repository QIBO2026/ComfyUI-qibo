"""QIBO 下载解压节点。

前端 js/qibo_download_extract_node.js 在节点上提供：
- 网址输入框：输入要下载的文件 URL
- 下载按钮：点击后从 URL 下载文件到 ComfyUI 根目录
- 解压按钮：点击后将下载的文件解压到 ComfyUI/custom_nodes 目录
- 覆盖选项：勾选则解压时覆盖已存在文件，不勾选则跳过已存在文件

后端路由：
- POST /qibo/download_url_file  body {url} -> 下载文件到 ComfyUI 根目录
- POST /qibo/extract_to_custom_nodes  body {filename, overwrite} -> 解压到 custom_nodes
"""

import os
import zipfile
import tarfile
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


def _get_comfyui_root():
    """获取 ComfyUI 根目录（custom_nodes 的上级目录）"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _download_file(url, dest_dir):
    """从 URL 下载文件到指定目录，返回保存的文件路径"""
    parsed = urllib.parse.urlparse(url)
    filename = os.path.basename(parsed.path)
    if not filename:
        filename = "downloaded_file"
    dest_path = os.path.join(dest_dir, filename)

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        with open(dest_path, "wb") as f:
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                f.write(chunk)
    return dest_path


def _extract_file(filepath, dest_dir, overwrite=False):
    """解压 zip 或 tar 文件到指定目录，返回解出的文件列表"""
    extracted = []
    skipped = []

    if filepath.endswith(".zip"):
        with zipfile.ZipFile(filepath, "r") as zf:
            for member in zf.namelist():
                target = os.path.join(dest_dir, member)
                if os.path.exists(target) and not overwrite:
                    skipped.append(member)
                    continue
                zf.extract(member, dest_dir)
                extracted.append(member)
    elif filepath.endswith((".tar.gz", ".tgz", ".tar.bz2", ".tar", ".gz")):
        with tarfile.open(filepath, "r:*") as tf:
            for member in tf.getmembers():
                target = os.path.join(dest_dir, member.name)
                if os.path.exists(target) and not overwrite:
                    skipped.append(member.name)
                    continue
                tf.extract(member, dest_dir)
                extracted.append(member.name)
    else:
        raise ValueError(f"不支持的文件格式: {filepath}（仅支持 zip/tar.gz/tgz/tar.bz2/tar）")

    return {"extracted": extracted, "skipped": skipped}


def register_server_routes():
    """注册下载解压相关的服务端路由"""
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

            comfyui_root = _get_comfyui_root()
            dest_path = _download_file(url, comfyui_root)
            filename = os.path.basename(dest_path)

            return web.json_response({
                "success": True,
                "filename": filename,
                "path": dest_path,
                "size": os.path.getsize(dest_path),
            })
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @routes.post("/qibo/extract_to_custom_nodes")
    async def extract_to_custom_nodes(request):
        try:
            data = await request.json()
            filename = data.get("filename", "").strip()
            overwrite = data.get("overwrite", False)

            if not filename:
                return web.json_response({"error": "缺少文件名参数"}, status=400)

            comfyui_root = _get_comfyui_root()
            filepath = os.path.join(comfyui_root, filename)

            if not os.path.exists(filepath):
                return web.json_response({"error": f"文件不存在: {filepath}"}, status=404)

            custom_nodes_dir = os.path.join(comfyui_root, "custom_nodes")
            result = _extract_file(filepath, custom_nodes_dir, overwrite)

            return web.json_response({
                "success": True,
                "extracted_count": len(result["extracted"]),
                "skipped_count": len(result["skipped"]),
                "extracted": result["extracted"][:50],
                "skipped": result["skipped"][:50],
            })
        except Exception as e:
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
        return ("此节点通过按钮下载和解压文件：输入网址后点「下载文件」按钮下载，再点「解压到 custom_nodes」按钮解压。覆盖选项控制解压时是否覆盖已存在文件。",)


NODE_CLASS_MAPPINGS = {
    "QIBODownloadExtractNode": QIBODownloadExtractNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBODownloadExtractNode": "qibo 下载解压",
}