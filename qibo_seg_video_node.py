"""QIBO 分段视频管理节点。

列举 MiniMax H3 Director 分段视频导出目录（output/minimax_seg_export/<时间戳>/seg_XXXX.mp4），
前端按文件夹分组显示，支持全选/全不选、勾选删除、ffmpeg 合成为一个视频并下载。

后端路由：
- GET  /qibo/seg_video/list    列举所有文件夹与分段 mp4
- POST /qibo/seg_video/delete  删除选中的视频文件
- POST /qibo/seg_video/concat  ffmpeg concat 合成选中视频到 output 目录
"""

import os
import time
import shutil
import subprocess
import uuid

try:
    import folder_paths
except Exception:
    folder_paths = None

try:
    from server import PromptServer
    from aiohttp import web
    _SERVER_OK = True
except Exception:
    _SERVER_OK = False
    PromptServer = None
    web = None


SEG_EXPORT_ROOTNAME = "minimax_seg_export"


def _output_dir():
    if folder_paths:
        try:
            return folder_paths.get_output_directory()
        except Exception:
            pass
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "output"))


def _seg_root():
    return os.path.join(_output_dir(), SEG_EXPORT_ROOTNAME)


def _ffmpeg_path():
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    return None


def _is_safe_name(name):
    if not name:
        return False
    if os.sep in name or "/" in name or "\\" in name or name in (".", ".."):
        return False
    return True


def _list_folders():
    root = _seg_root()
    folders = []
    if not os.path.isdir(root):
        return folders
    for name in os.listdir(root):
        fp = os.path.join(root, name)
        if not os.path.isdir(fp):
            continue
        files = []
        for fn in os.listdir(fp):
            if not fn.lower().endswith(".mp4"):
                continue
            full = os.path.join(fp, fn)
            if not os.path.isfile(full):
                continue
            try:
                size = os.path.getsize(full)
                mtime = int(os.path.getmtime(full))
            except Exception:
                size = 0
                mtime = 0
            files.append({"filename": fn, "size": size, "mtime": mtime})
        files.sort(key=lambda x: x["filename"])
        folders.append({
            "folder": name,
            "file_count": len(files),
            "total_size": sum(f["size"] for f in files),
            "files": files,
        })
    folders.sort(key=lambda x: x["folder"], reverse=True)
    return folders


if _SERVER_OK:
    _routes = PromptServer.instance.routes

    @_routes.get("/qibo/seg_video/list")
    async def qibo_seg_video_list(request):
        folders = _list_folders()
        return web.json_response({"folders": folders, "root": _seg_root()})

    @_routes.post("/qibo/seg_video/delete")
    async def qibo_seg_video_delete(request):
        try:
            data = await request.json()
        except Exception:
            data = {}
        items = data.get("items", []) or []
        removed = 0
        errors = []
        for it in items:
            folder = it.get("folder", "")
            filename = it.get("filename", "")
            if not _is_safe_name(folder) or not _is_safe_name(filename):
                errors.append(f"{folder}/{filename}: 非法名称")
                continue
            fp = os.path.join(_seg_root(), folder, filename)
            if os.path.isfile(fp):
                try:
                    os.remove(fp)
                    removed += 1
                except Exception as e:
                    errors.append(f"{folder}/{filename}: {e}")
        return web.json_response({"ok": True, "removed": removed, "errors": errors})

    @_routes.post("/qibo/seg_video/concat")
    async def qibo_seg_video_concat(request):
        try:
            data = await request.json()
        except Exception:
            data = {}
        items = data.get("items", []) or []
        if not items:
            return web.json_response({"ok": False, "error": "未选择任何视频"})
        ffmpeg = _ffmpeg_path()
        if not ffmpeg:
            return web.json_response({"ok": False, "error": "未找到 ffmpeg，请安装 ffmpeg 或 imageio-ffmpeg"})
        paths = []
        for it in items:
            folder = it.get("folder", "")
            filename = it.get("filename", "")
            if not _is_safe_name(folder) or not _is_safe_name(filename):
                continue
            fp = os.path.join(_seg_root(), folder, filename)
            if os.path.isfile(fp):
                paths.append(fp)
        if not paths:
            return web.json_response({"ok": False, "error": "选中文件均不存在"})
        out_dir = _output_dir()
        os.makedirs(out_dir, exist_ok=True)
        out_name = f"qibo_seg_concat_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.mp4"
        out_path = os.path.join(out_dir, out_name)
        list_path = out_path + ".txt"
        with open(list_path, "w", encoding="utf-8") as f:
            for p in paths:
                esc = p.replace("'", "\\'")
                f.write(f"file '{esc}'\n")
        try:
            cmd = [ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                   "-i", list_path, "-c", "copy", out_path]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600)
            if proc.returncode != 0:
                cmd2 = [ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                        "-i", list_path, "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                        "-c:a", "aac", out_path]
                proc2 = subprocess.run(cmd2, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1800)
                if proc2.returncode != 0:
                    err = proc2.stderr.decode("utf-8", errors="replace") or proc.stderr.decode("utf-8", errors="replace")
                    return web.json_response({"ok": False, "error": f"ffmpeg 合成失败: {err}"})
        finally:
            try:
                os.remove(list_path)
            except Exception:
                pass
        size = os.path.getsize(out_path) if os.path.isfile(out_path) else 0
        return web.json_response({
            "ok": True,
            "filename": out_name,
            "subfolder": "",
            "type": "output",
            "size": size,
            "url": f"/view?filename={out_name}&type=output&subfolder=",
        })


class QIBOSegVideoManagerNode:
    """列举 MiniMax H3 Director 分段视频导出目录，前端支持勾选删除/合成/下载。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {}}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("info",)
    FUNCTION = "run"
    OUTPUT_NODE = True
    CATEGORY = "QIBO"

    def run(self):
        folders = _list_folders()
        total = sum(f["file_count"] for f in folders)
        return (f"共 {len(folders)} 个文件夹，{total} 个分段视频。请在节点界面操作。",)


NODE_CLASS_MAPPINGS = {
    "QIBOSegVideoManagerNode": QIBOSegVideoManagerNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBOSegVideoManagerNode": "qibo 分段视频管理",
}