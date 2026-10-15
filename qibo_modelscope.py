"""QIBO 魔搭模型搜索与下载（网页方式，不依赖魔搭 API/token）。

POST /qibo/modelscope/search   body {filename} -> 用 DuckDuckGo 搜 site:modelscope.cn <filename>，解析候选模型ID + 直接文件链接
POST /qibo/modelscope/download body {model_id?, folder, filename?, direct_url?} -> 下载到 models/<folder>/（直链优先，SDK 兜底）
"""

import os
import re
import json
import asyncio
import base64
import urllib.parse
import threading
import time
import uuid


try:
    from server import PromptServer
    from aiohttp import web
    SERVER_AVAILABLE = True
except ImportError:
    SERVER_AVAILABLE = False
    PromptServer = None
    web = None

try:
    import requests
except ImportError:
    requests = None

BING_URL = "https://www.bing.com/search"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"


def _bing_decode_urls(html):
    urls = []
    for m in re.finditer(r'u=a1([A-Za-z0-9_-]+)', html):
        s = m.group(1)
        s += "=" * (-len(s) % 4)
        try:
            urls.append(base64.urlsafe_b64decode(s).decode("utf-8", "ignore"))
        except Exception:
            pass
    return urls


def _parse_modelscope_url(url):
    candidates = []
    m = re.search(r'modelscope\.cn/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/resolve/([A-Za-z0-9_.-]+)/(.+)', url)
    if m:
        owner, name, rev, fpath = m.group(1), m.group(2), m.group(3), urllib.parse.unquote(m.group(4))
        mid = f"{owner}/{name}"
        direct = f"https://www.modelscope.cn/{mid}/resolve/{rev}/{fpath}"
        candidates.append({"model_id": mid, "page_url": f"https://www.modelscope.cn/models/{mid}", "direct_file_url": direct, "files": [fpath]})
    m = re.search(r'modelscope\.cn/api/v1/models/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/repo', url)
    if m:
        owner, name = m.group(1), m.group(2)
        mid = f"{owner}/{name}"
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        rev = params.get("Revision", ["master"])[0]
        fpath = params.get("FilePath", [""])[0]
        direct = f"https://www.modelscope.cn/{mid}/resolve/{rev}/{fpath}" if fpath else None
        candidates.append({"model_id": mid, "page_url": f"https://www.modelscope.cn/models/{mid}", "direct_file_url": direct, "files": [fpath] if fpath else []})
    if not candidates:
        m = re.search(r'modelscope\.cn/models/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)', url)
        if m:
            mid = f"{m.group(1)}/{m.group(2)}"
            candidates.append({"model_id": mid, "page_url": f"https://www.modelscope.cn/models/{mid}", "direct_file_url": None, "files": []})
    for c in candidates:
        c["files"] = c["files"][:10]
    return {"candidates": candidates, "query": f"url:{url}"}


def _search_modelscope(filename, timeout=25):
    if requests is None:
        return {"error": "requests 未安装", "candidates": []}
    q = f"site:modelscope.cn {filename}"
    try:
        r = requests.get(BING_URL, params={"q": q}, headers={"User-Agent": UA}, timeout=timeout)
    except Exception as e:
        return {"error": f"Bing 请求失败: {e}", "candidates": []}

    links = _bing_decode_urls(r.text)
    candidates = {}
    for link in links:
        if "modelscope.cn" not in link:
            continue
        m = re.search(r'modelscope\.cn/models/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)', link)
        if m:
            mid = f"{m.group(1)}/{m.group(2)}"
            candidates.setdefault(mid, {"model_id": mid, "page_url": f"https://www.modelscope.cn/models/{mid}", "direct_file_url": None, "files": []})
        m = re.search(r'modelscope\.cn/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/resolve/([A-Za-z0-9_.-]+)/([^\s"\'<>]+)', link)
        if m:
            owner, name, rev, fpath = m.group(1), m.group(2), m.group(3), urllib.parse.unquote(m.group(4))
            mid = f"{owner}/{name}"
            c = candidates.setdefault(mid, {"model_id": mid, "page_url": f"https://www.modelscope.cn/models/{mid}", "direct_file_url": None, "files": []})
            c["files"].append(fpath)
            if fpath == filename or fpath.endswith(filename) or filename in fpath:
                c["direct_file_url"] = f"https://www.modelscope.cn/{mid}/resolve/{rev}/{fpath}"

    cands = list(candidates.values())
    for c in cands:
        c["files"] = c["files"][:10]
    cands.sort(key=lambda c: (c["direct_file_url"] is None, c["model_id"]))
    return {"candidates": cands[:15], "query": q}


def _resolve_dest_dir(folder):
    try:
        import folder_paths as fp
        if folder in fp.folder_names_and_paths:
            dirs = fp.folder_names_and_paths[folder][0]
            if dirs:
                for d in dirs:
                    if os.path.basename(os.path.normpath(d)) == folder:
                        os.makedirs(d, exist_ok=True)
                        return d
                d = dirs[0]
                os.makedirs(d, exist_ok=True)
                return d
    except Exception:
        pass
    return None


def _build_download_headers(url):
    """根据下载 URL 域名构造请求头，避免跨站 Referer 触发防盗链返回 HTML。"""
    host = urllib.parse.urlparse(url).hostname or ""
    headers = {"User-Agent": UA, "Accept": "application/octet-stream,*/*"}
    if "modelscope.cn" in host:
        headers["Referer"] = "https://www.modelscope.cn/"
    return headers


def _stream_get(url, timeout=1200):
    """发起流式下载请求；若返回 HTML 则换无 Referer 浏览器头重试一次，仍 HTML 则抛异常。"""
    r = requests.get(url, stream=True, headers=_build_download_headers(url), timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    if "text/html" not in r.headers.get("Content-Type", ""):
        return r
    r.close()
    r = requests.get(url, stream=True, headers={"User-Agent": UA, "Accept": "*/*"}, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    if "text/html" in r.headers.get("Content-Type", ""):
        raise RuntimeError(f"下载链接返回 HTML 页面而非文件（可能需登录或链接已失效）: {url}")
    return r


def _download_direct(url, dest_path, timeout=1200):
    r = _stream_get(url, timeout)
    total = int(r.headers.get("Content-Length", 0))
    done = 0
    with open(dest_path, "wb") as f:
        for chunk in r.iter_content(1024 * 1024):
            if chunk:
                f.write(chunk)
                done += len(chunk)
    return {"ok": True, "path": dest_path, "size": os.path.getsize(dest_path), "downloaded": done}


_download_tasks = {}
_task_lock = threading.Lock()


def _download_direct_with_progress(url, dest_path, task_id, timeout=1200):
    try:
        r = _stream_get(url, timeout)
    except Exception as e:
        with _task_lock:
            t = _download_tasks.get(task_id)
            if t:
                t["status"] = "error"
                t["error"] = str(e)
        return
    total = int(r.headers.get("Content-Length", 0))
    done = 0
    start_time = time.time()
    with _task_lock:
        t = _download_tasks.get(task_id)
        if t:
            t["total"] = total
            t["start_time"] = start_time
    with open(dest_path, "wb") as f:
        for chunk in r.iter_content(1024 * 1024):
            if chunk:
                f.write(chunk)
                done += len(chunk)
                with _task_lock:
                    t = _download_tasks.get(task_id)
                    if t:
                        t["downloaded"] = done
                        t["status"] = "downloading"
    with _task_lock:
        t = _download_tasks.get(task_id)
        if t:
            t["status"] = "done"
            t["downloaded"] = os.path.getsize(dest_path)


def _download_sdk(model_id, dest_dir, filename, timeout=1200):
    from modelscope.hub.snapshot_download import snapshot_download
    kwargs = {"local_dir": dest_dir}
    if filename:
        kwargs["allow_file_pattern"] = filename
    saved = snapshot_download(model_id, **kwargs)
    files = []
    for root, _, fs in os.walk(saved):
        for fn in fs:
            files.append(os.path.relpath(os.path.join(root, fn), saved))
    return {"ok": True, "dir": saved, "files": files[:50]}


def _parse_repo_url(url):
    m = re.search(r'modelscope\.cn/models/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/tree/([A-Za-z0-9_.-]+)/(.*)', url)
    if m:
        return m.group(1), m.group(2), m.group(3), m.group(4), "modelscope", "https://www.modelscope.cn"
    m = re.search(r'modelscope\.cn/models/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)', url)
    if m:
        return m.group(1), m.group(2), "master", "", "modelscope", "https://www.modelscope.cn"
    m = re.search(r'(https?://[A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/tree/([A-Za-z0-9_.-]+)/?(.*)', url)
    if m:
        return m.group(2), m.group(3), m.group(4), m.group(5), "huggingface", m.group(1)
    m = re.search(r'(https?://[A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/?$', url)
    if m:
        return m.group(2), m.group(3), "main", "", "huggingface", m.group(1)
    return None


def _guess_local_folder(fpath, folder_keys):
    parts = fpath.replace("\\", "/").split("/")
    for part in parts:
        if part in folder_keys:
            return part
    parent = os.path.basename(os.path.dirname(fpath))
    return parent if parent in folder_keys else None


def _list_repo_files(owner, name, revision, path):
    api_url = f"https://www.modelscope.cn/api/v1/models/{owner}/{name}/repo/files"
    params = {"Revision": revision, "Recursive": "true"}
    if path:
        params["FilePath"] = path
    r = requests.get(api_url, params=params, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    data = r.json()
    raw_files = data.get("Data", {}).get("Files", [])

    try:
        import folder_paths as fp
        folder_keys = set(fp.folder_names_and_paths.keys())
    except Exception:
        folder_keys = set()

    path_prefix = (path.rstrip("/") + "/") if path else ""
    result = []
    for f in raw_files:
        if f.get("Type") != "blob":
            continue
        fpath = f.get("Path", "")
        if path_prefix and not fpath.startswith(path_prefix):
            continue
        size = f.get("Size", 0)
        local_folder = _guess_local_folder(fpath, folder_keys)
        parent = os.path.basename(os.path.dirname(fpath))
        direct_url = f"https://www.modelscope.cn/{owner}/{name}/resolve/{revision}/{fpath}"
        fname = os.path.basename(fpath)
        local_exists = False
        if local_folder:
            dest_dir = _resolve_dest_dir(local_folder)
            if dest_dir and os.path.exists(os.path.join(dest_dir, fname)):
                local_exists = True
        result.append({
            "path": fpath,
            "name": fname,
            "size": size,
            "parent_dir": parent,
            "local_folder": local_folder,
            "direct_url": direct_url,
            "local_exists": local_exists,
        })
    return result


def _list_hf_repo_files(owner, name, revision, path, base_url="https://hf-mirror.com"):
    api_url = f"{base_url}/api/models/{owner}/{name}/tree/{revision}"
    params = {"recursive": "true"}
    r = requests.get(api_url, params=params, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    raw_files = r.json()

    try:
        import folder_paths as fp
        folder_keys = set(fp.folder_names_and_paths.keys())
    except Exception:
        folder_keys = set()

    path_prefix = (path.rstrip("/") + "/") if path else ""
    result = []
    for f in raw_files:
        if f.get("type") != "file":
            continue
        fpath = f.get("path", "")
        if path_prefix and not fpath.startswith(path_prefix):
            continue
        size = f.get("size", 0)
        local_folder = _guess_local_folder(fpath, folder_keys)
        parent = os.path.basename(os.path.dirname(fpath))
        direct_url = f"{base_url}/{owner}/{name}/resolve/{revision}/{fpath}"
        fname = os.path.basename(fpath)
        local_exists = False
        if local_folder:
            dest_dir = _resolve_dest_dir(local_folder)
            if dest_dir and os.path.exists(os.path.join(dest_dir, fname)):
                local_exists = True
        result.append({
            "path": fpath,
            "name": fname,
            "size": size,
            "parent_dir": parent,
            "local_folder": local_folder,
            "direct_url": direct_url,
            "local_exists": local_exists,
        })
    return result


def register_server_routes():
    if not SERVER_AVAILABLE:
        return

    routes = PromptServer.instance.routes

    @routes.post("/qibo/modelscope/search")
    async def ms_search(request):
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        url = (payload.get("url") or "").strip()
        if url:
            result = _parse_modelscope_url(url)
            return web.json_response(result)
        filename = (payload.get("filename") or "").strip()
        if not filename:
            return web.json_response({"error": "filename 为空", "candidates": []})
        result = await asyncio.to_thread(_search_modelscope, filename)
        return web.json_response(result)

    @routes.post("/qibo/modelscope/download")
    async def ms_download(request):
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        folder = payload.get("folder") or "checkpoints"
        filename = (payload.get("filename") or "").strip() or None
        direct_url = (payload.get("direct_url") or "").strip() or None
        model_id = (payload.get("model_id") or "").strip() or None

        dest_dir = _resolve_dest_dir(folder)
        if not dest_dir:
            return web.json_response({"error": f"未找到模型目录: {folder}"})

        if direct_url:
            fname = filename or os.path.basename(urllib.parse.urlparse(direct_url).path) or "model.bin"
            dest = os.path.join(dest_dir, fname)
            task_id = str(uuid.uuid4())
            with _task_lock:
                _download_tasks[task_id] = {
                    "status": "starting",
                    "filename": fname,
                    "folder": folder,
                    "dest_path": dest,
                    "downloaded": 0,
                    "total": 0,
                    "start_time": time.time(),
                    "error": None,
                }

            def _do_download():
                try:
                    _download_direct_with_progress(direct_url, dest, task_id)
                except Exception as e:
                    with _task_lock:
                        t = _download_tasks.get(task_id)
                        if t:
                            t["status"] = "error"
                            t["error"] = str(e)

            thread = threading.Thread(target=_do_download, daemon=True)
            thread.start()
            return web.json_response({"task_id": task_id, "filename": fname, "folder": folder, "dest_path": dest})
        elif model_id:
            try:
                res = await asyncio.to_thread(_download_sdk, model_id, dest_dir, filename)
                res["folder"] = folder
                res["dest_dir"] = dest_dir
            except Exception as e:
                return web.json_response({"error": f"下载失败: {e}"})
            return web.json_response(res)
        else:
            return web.json_response({"error": "需提供 direct_url 或 model_id"})

    @routes.post("/qibo/modelscope/download_progress")
    async def ms_download_progress(request):
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        task_id = payload.get("task_id", "")
        with _task_lock:
            t = _download_tasks.get(task_id)
            if not t:
                return web.json_response({"error": "task not found"})
            elapsed = time.time() - t["start_time"]
            downloaded = t["downloaded"]
            total = t["total"]
            speed = downloaded / elapsed if elapsed > 0 else 0
            percent = (downloaded / total * 100) if total > 0 else 0
            return web.json_response({
                "status": t["status"],
                "filename": t["filename"],
                "folder": t["folder"],
                "downloaded": downloaded,
                "total": total,
                "speed": speed,
                "percent": percent,
                "error": t["error"],
            })
    @routes.post("/qibo/modelscope/list_files")
    async def ms_list_files(request):
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        url = (payload.get("url") or "").strip()
        if not url:
            return web.json_response({"error": "url 为空", "files": []})
        parsed = _parse_repo_url(url)
        if not parsed:
            return web.json_response({"error": "无法解析仓库 URL（支持 modelscope.cn / 任意 HF 兼容站点 /{owner}/{repo}）", "files": []})
        owner, name, rev, path, source, base_url = parsed
        try:
            if source == "huggingface":
                files = await asyncio.to_thread(_list_hf_repo_files, owner, name, rev, path, base_url)
            else:
                files = await asyncio.to_thread(_list_repo_files, owner, name, rev, path)
        except Exception as e:
            return web.json_response({"error": f"列文件失败: {e}", "files": []})
        return web.json_response({"files": files, "model_id": f"{owner}/{name}"})

    @routes.post("/qibo/modelscope/batch_download")
    async def ms_batch_download(request):
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        files = payload.get("files", [])
        default_folder = payload.get("folder") or "checkpoints"
        results = []
        for f in files:
            folder = f.get("local_folder") or default_folder
            direct_url = f.get("direct_url")
            fname = f.get("name") or os.path.basename(f.get("path", ""))
            dest_dir = _resolve_dest_dir(folder)
            if not dest_dir:
                results.append({"name": fname, "error": f"未找到目录: {folder}"})
                continue
            dest = os.path.join(dest_dir, fname)
            try:
                res = await asyncio.to_thread(_download_direct, direct_url, dest)
                res["folder"] = folder
                res["full_path"] = dest
                results.append(res)
            except Exception as e:
                results.append({"name": fname, "error": str(e)})
        ok_count = sum(1 for r in results if r.get("ok"))
        return web.json_response({"results": results, "total": len(results), "ok": ok_count})
