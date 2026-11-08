# -*- coding: utf-8 -*-
"""QIBO H3 接力存档管理 API

配合 js/qibo_h3_archive_manager.js 的存档管理弹窗：
  GET  /qibo/h3_archives          — 列出 output/qibo_h3/ 下的全部存档（文件名/大小/时间）
  POST /qibo/h3_archives/delete   — 删除选中存档（支持批量，names 为文件名数组）
"""

import os
import time

try:
    from server import PromptServer
    from aiohttp import web
    SERVER_AVAILABLE = True
except ImportError:
    SERVER_AVAILABLE = False

from .qibo_h3_selflift_relay_node import _relay_dir


def register_server_routes():
    if not SERVER_AVAILABLE:
        return

    routes = PromptServer.instance.routes

    @routes.get("/qibo/h3_archives")
    async def qibo_h3_archives_list(request):
        d = _relay_dir()
        items = []
        try:
            names = sorted(os.listdir(d))
        except OSError as e:
            return web.json_response({"archives": [], "dir": d, "error": str(e)})
        for fn in names:
            if not fn.endswith(".pt"):
                continue
            fp = os.path.join(d, fn)
            try:
                items.append({
                    "name": fn,
                    "size_mb": round(os.path.getsize(fp) / 1048576, 2),
                    "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(fp))),
                })
            except OSError:
                continue
        return web.json_response({"archives": items, "dir": d})

    @routes.post("/qibo/h3_archives/delete")
    async def qibo_h3_archives_delete(request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)
        names = data.get("names") or []
        d = _relay_dir()
        deleted, errors = [], []
        for name in names:
            if (not isinstance(name, str) or not name.endswith(".pt")
                    or os.path.basename(name) != name):
                errors.append(str(name))
                continue
            fp = os.path.join(d, name)
            try:
                os.remove(fp)
                deleted.append(name)
            except OSError as e:
                errors.append("{}: {}".format(name, e))
        return web.json_response({"deleted": deleted, "errors": errors})
