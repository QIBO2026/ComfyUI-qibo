"""
QIBO 分块上传模块
解决 ComfyUI 服务端 / 反向代理对单次请求体大小的限制。
客户端将大图片切成多个小 chunk 逐块上传，服务端收齐后合并为完整文件。

服务端 API（注册在 ComfyUI PromptServer 上）：
  POST /qibo/chunked_upload/init    — 初始化上传会话
  POST /qibo/chunked_upload/chunk   — 上传单个分块
  POST /qibo/chunked_upload/merge   — 合并所有分块，写入 input 目录
  GET  /qibo/chunked_upload/status  — 查询上传进度
  POST /qibo/chunked_upload/cancel  — 取消并清理临时文件
"""

import os
import uuid
import json
import time
import shutil
import asyncio
import requests
from typing import Optional, Dict, Any

try:
    from server import PromptServer
    from aiohttp import web
    SERVER_AVAILABLE = True
except ImportError:
    SERVER_AVAILABLE = False
    PromptServer = None
    web = None

TEMP_DIR = os.path.join(os.path.dirname(__file__), "chunked_upload_temp")
os.makedirs(TEMP_DIR, exist_ok=True)

DEFAULT_CHUNK_SIZE = 512 * 1024

_upload_sessions: Dict[str, Dict[str, Any]] = {}


def _cleanup_session(upload_id: str):
    session_dir = os.path.join(TEMP_DIR, upload_id)
    if os.path.isdir(session_dir):
        shutil.rmtree(session_dir, ignore_errors=True)
    _upload_sessions.pop(upload_id, None)


def _auto_cleanup_expired(max_age_seconds=3600):
    now = time.time()
    for uid in list(_upload_sessions.keys()):
        info = _upload_sessions.get(uid, {})
        if now - info.get("created_at", 0) > max_age_seconds:
            _cleanup_session(uid)


def register_server_routes():
    if not SERVER_AVAILABLE:
        return

    routes = PromptServer.instance.routes

    @routes.post("/qibo/chunked_upload/init")
    async def chunked_init(request):
        _auto_cleanup_expired()
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)

        filename = data.get("filename", f"upload_{int(time.time())}.png")
        total_chunks = int(data.get("total_chunks", 0))
        total_size = int(data.get("total_size", 0))
        upload_type = data.get("type", "input")
        subfolder = data.get("subfolder", "")

        if total_chunks <= 0:
            return web.json_response({"error": "total_chunks must be > 0"}, status=400)

        upload_id = uuid.uuid4().hex[:16]
        session_dir = os.path.join(TEMP_DIR, upload_id)
        os.makedirs(session_dir, exist_ok=True)

        _upload_sessions[upload_id] = {
            "filename": filename,
            "total_chunks": total_chunks,
            "total_size": total_size,
            "received": set(),
            "type": upload_type,
            "subfolder": subfolder,
            "created_at": time.time(),
        }

        return web.json_response({
            "upload_id": upload_id,
            "chunk_size": DEFAULT_CHUNK_SIZE,
            "session_dir": session_dir,
        })

    @routes.post("/qibo/chunked_upload/chunk")
    async def chunked_chunk(request):
        try:
            post = await request.post()
        except Exception:
            return web.json_response({"error": "invalid form data"}, status=400)

        upload_id = post.get("upload_id", "")
        chunk_index_str = post.get("chunk_index", "")
        chunk_file = post.get("data")

        if upload_id not in _upload_sessions:
            return web.json_response({"error": "invalid upload_id"}, status=400)

        try:
            chunk_index = int(chunk_index_str)
        except ValueError:
            return web.json_response({"error": "invalid chunk_index"}, status=400)

        if chunk_file is None or not hasattr(chunk_file, "file"):
            return web.json_response({"error": "missing chunk data"}, status=400)

        session = _upload_sessions[upload_id]
        if chunk_index < 0 or chunk_index >= session["total_chunks"]:
            return web.json_response({"error": "chunk_index out of range"}, status=400)

        chunk_path = os.path.join(TEMP_DIR, upload_id, f"chunk_{chunk_index:06d}")
        with open(chunk_path, "wb") as f:
            f.write(chunk_file.file.read())

        session["received"].add(chunk_index)

        return web.json_response({
            "upload_id": upload_id,
            "chunk_index": chunk_index,
            "received_count": len(session["received"]),
            "total_chunks": session["total_chunks"],
        })

    @routes.post("/qibo/chunked_upload/merge")
    async def chunked_merge(request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)

        upload_id = data.get("upload_id", "")
        if upload_id not in _upload_sessions:
            return web.json_response({"error": "invalid upload_id"}, status=400)

        session = _upload_sessions[upload_id]
        if len(session["received"]) != session["total_chunks"]:
            missing = set(range(session["total_chunks"])) - session["received"]
            return web.json_response({
                "error": "not all chunks received",
                "missing": sorted(missing),
                "received": len(session["received"]),
                "total": session["total_chunks"],
            }, status=400)

        filename = session["filename"]
        upload_type = session.get("type", "input")
        subfolder = session.get("subfolder", "")

        try:
            from folder_paths import get_directory_by_type
            upload_dir = get_directory_by_type(upload_type)
            if upload_dir is None:
                upload_dir = get_directory_by_type("input")
        except Exception:
            upload_dir = os.path.join(os.path.dirname(__file__), "..", "..", "input")
            upload_dir = os.path.abspath(upload_dir)

        full_output_folder = os.path.join(upload_dir, os.path.normpath(subfolder))
        if not os.path.exists(full_output_folder):
            os.makedirs(full_output_folder)

        filepath = os.path.abspath(os.path.join(full_output_folder, filename))
        if os.path.commonpath((upload_dir, filepath)) != upload_dir:
            return web.json_response({"error": "invalid path"}, status=400)

        split = os.path.splitext(filename)
        i = 1
        while os.path.exists(filepath):
            filename = f"{split[0]} ({i}){split[1]}"
            filepath = os.path.join(full_output_folder, filename)
            i += 1

        session_dir = os.path.join(TEMP_DIR, upload_id)
        with open(filepath, "wb") as out_f:
            for idx in range(session["total_chunks"]):
                chunk_path = os.path.join(session_dir, f"chunk_{idx:06d}")
                with open(chunk_path, "rb") as chunk_f:
                    out_f.write(chunk_f.read())

        _cleanup_session(upload_id)

        return web.json_response({
            "name": filename,
            "subfolder": subfolder,
            "type": upload_type,
            "size": os.path.getsize(filepath),
        })

    @routes.get("/qibo/chunked_upload/status")
    async def chunked_status(request):
        upload_id = request.query.get("upload_id", "")
        if upload_id not in _upload_sessions:
            return web.json_response({"error": "invalid upload_id"}, status=404)

        session = _upload_sessions[upload_id]
        return web.json_response({
            "upload_id": upload_id,
            "filename": session["filename"],
            "received": sorted(session["received"]),
            "received_count": len(session["received"]),
            "total_chunks": session["total_chunks"],
            "total_size": session["total_size"],
        })

    @routes.post("/qibo/chunked_upload/cancel")
    async def chunked_cancel(request):
        try:
            data = await request.json()
        except Exception:
            data = {}
        upload_id = data.get("upload_id", "")
        if upload_id in _upload_sessions:
            _cleanup_session(upload_id)
            return web.json_response({"cancelled": True, "upload_id": upload_id})
        return web.json_response({"error": "invalid upload_id"}, status=404)


def chunked_upload(
    file_path: str,
    server_url: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    upload_type: str = "input",
    subfolder: str = "",
    overwrite: bool = False,
    progress_callback=None,
) -> Dict[str, Any]:
    """
    客户端分块上传工具函数。

    参数:
        file_path:     本地文件路径
        server_url:    ComfyUI 服务根 URL（如 https://example.com:8188）
        chunk_size:    每块大小（字节），默认 512KB
        upload_type:   "input" / "output" / "temp"
        subfolder:     子目录
        overwrite:     是否覆盖同名文件
        progress_callback: 可选回调 fn(received, total) 用于显示进度

    返回:
        {"name": "file.png", "subfolder": "", "type": "input", "size": 12345}
    """
    server_url = server_url.rstrip("/")
    file_size = os.path.getsize(file_path)
    filename = os.path.basename(file_path)

    total_chunks = (file_size + chunk_size - 1) // chunk_size

    print(f"📦 分块上传: {filename} ({file_size/1024/1024:.2f}MB) → {total_chunks} 块 × {chunk_size/1024:.0f}KB")

    resp = requests.post(
        f"{server_url}/qibo/chunked_upload/init",
        json={
            "filename": filename,
            "total_chunks": total_chunks,
            "total_size": file_size,
            "type": upload_type,
            "subfolder": subfolder,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise Exception(f"初始化失败: {resp.status_code} {resp.text}")

    init_data = resp.json()
    upload_id = init_data["upload_id"]

    for idx in range(total_chunks):
        offset = idx * chunk_size
        with open(file_path, "rb") as f:
            f.seek(offset)
            chunk_data = f.read(chunk_size)

        resp = requests.post(
            f"{server_url}/qibo/chunked_upload/chunk",
            data={"upload_id": upload_id, "chunk_index": str(idx)},
            files={"data": (f"chunk_{idx}", chunk_data, "application/octet-stream")},
            timeout=120,
        )
        if resp.status_code != 200:
            raise Exception(f"块 {idx}/{total_chunks} 上传失败: {resp.status_code} {resp.text}")

        if progress_callback:
            progress_callback(idx + 1, total_chunks)
        elif (idx + 1) % 10 == 0 or idx + 1 == total_chunks:
            print(f"   ⬆️ 已上传 {idx + 1}/{total_chunks} 块 ({(idx+1)*100//total_chunks}%)")

    print(f"   🔗 正在合并 {total_chunks} 个分块...")
    resp = requests.post(
        f"{server_url}/qibo/chunked_upload/merge",
        json={"upload_id": upload_id, "filename": filename, "type": upload_type},
        timeout=60,
    )
    if resp.status_code != 200:
        raise Exception(f"合并失败: {resp.status_code} {resp.text}")

    result = resp.json()
    print(f"✅ 上传完成: {result.get('name')} ({result.get('size', 0)/1024/1024:.2f}MB)")
    return result


def chunked_upload_pil(
    pil_image,
    server_url: str,
    filename: str = "upload.png",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    upload_type: str = "input",
    subfolder: str = "",
    progress_callback=None,
) -> Dict[str, Any]:
    """
    PIL Image 分块上传（先写入临时文件，再分块上传）。
    """
    import tempfile
    from PIL import Image

    ext = os.path.splitext(filename)[1].lower()
    fmt = "PNG" if ext == ".png" else "JPEG" if ext in (".jpg", ".jpeg") else "PNG"

    tmp_path = os.path.join(tempfile.gettempdir(), f"qibo_chunked_{int(time.time()*1000)}{ext}")
    try:
        pil_image.save(tmp_path, format=fmt)
        return chunked_upload(
            tmp_path, server_url, chunk_size, upload_type, subfolder,
            progress_callback=progress_callback,
        )
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)