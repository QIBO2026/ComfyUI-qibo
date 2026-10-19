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


HF_MIRROR_HOST = "hf-mirror.com"


def _to_hf_mirror(url):
    """将 huggingface.co 链接替换为国内镜像 hf-mirror.com，加速下载。非 HF 链接原样返回。"""
    if not url:
        return url
    try:
        parsed = urllib.parse.urlsplit(url)
    except Exception:
        return url
    if (parsed.hostname or "").lower() == "huggingface.co":
        return urllib.parse.urlunsplit(parsed._replace(netloc=HF_MIRROR_HOST))
    return url


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
        if "/resolve/master/" in url and "404" in str(e):
            try:
                r = _stream_get(url.replace("/resolve/master/", "/resolve/master/split_files/", 1), timeout)
            except Exception as e2:
                with _task_lock:
                    t = _download_tasks.get(task_id)
                    if t:
                        t["status"] = "error"
                        t["error"] = str(e2)
                return
        else:
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
            t["status"] = "downloading"
    cancelled = False
    with open(dest_path, "wb") as f:
        for chunk in r.iter_content(1024 * 1024):
            if chunk:
                f.write(chunk)
                done += len(chunk)
                now = time.time()
                with _task_lock:
                    t = _download_tasks.get(task_id)
                    if t:
                        if t.get("cancel"):
                            cancelled = True
                            break
                        t["downloaded"] = done
                        t["status"] = "downloading"
                        rc = t["recent_chunks"]
                        rc.append((now, len(chunk)))
                        cutoff = now - 3
                        while rc and rc[0][0] < cutoff:
                            rc.pop(0)
    if cancelled:
        try:
            if os.path.exists(dest_path):
                os.remove(dest_path)
        except Exception:
            pass
        with _task_lock:
            t = _download_tasks.get(task_id)
            if t:
                t["status"] = "cancelled"
        return
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


def _parse_resolve_url(url):
    """识别单文件直链:
    - HF 兼容: {base}/{owner}/{name}/resolve/{rev}/{fpath}
    - ModelScope: modelscope.cn/{owner}/{name}/resolve/{rev}/{fpath}
                  modelscope.cn/models/{owner}/{name}/resolve/{rev}/{fpath}
    返回 (owner, name, rev, fpath, source, base_url) 或 None。
    """
    uo = urllib.parse.urlsplit(url)
    host = (uo.hostname or "").lower()
    path = uo.path
    if "modelscope.cn" in host:
        m = re.match(r'^/(?:models/)?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/resolve/([A-Za-z0-9_.-]+)/(.+)$', path)
        if m:
            return m.group(1), m.group(2), m.group(3), m.group(4), "modelscope", "https://www.modelscope.cn"
    m = re.match(r'^/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/resolve/([A-Za-z0-9_.-]+)/(.+)$', path)
    if m:
        base = f"{uo.scheme}://{uo.netloc}"
        return m.group(1), m.group(2), m.group(3), m.group(4), "huggingface", base
    return None


def _head_resolve_file(direct_url):
    """HEAD 请求拿文件大小；拿不到返回 0。"""
    try:
        r = requests.head(direct_url, headers={"User-Agent": UA}, timeout=20, allow_redirects=True)
        if r.ok:
            cl = r.headers.get("Content-Length")
            if cl:
                try:
                    return int(cl)
                except Exception:
                    return 0
    except Exception:
        pass
    return 0


def _guess_local_folder(fpath, folder_keys):
    parts = fpath.replace("\\", "/").split("/")
    for part in parts:
        if part in folder_keys:
            return part
    parent = os.path.basename(os.path.dirname(fpath))
    return parent if parent in folder_keys else None


_MANIFEST_TEXT_EXTS = (".json", ".txt", ".tsv", ".csv", ".md")
_MS_DATASET_VIEW_RE = re.compile(r'modelscope\.cn/datasets/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/file/view/([^/?#]+)/([^?#]+)')


def _fetch_url_text(url):
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30, allow_redirects=True)
    r.raise_for_status()
    return r.text


def _mark_local_exists(files):
    for f in files:
        f["local_exists"] = False
        folder = f.get("local_folder")
        if folder:
            dest_dir = _resolve_dest_dir(folder)
            if dest_dir and os.path.exists(os.path.join(dest_dir, f.get("name") or "")):
                f["local_exists"] = True
    return files


def _parse_manifest_text(text, folder_keys):
    """解析清单文本为文件列表。支持:
    - JSON: {"models":[{"model_id","files":[{"name","size","download_url"}]}]}
    - TSV: 目录<TAB>文件名<TAB>大小(字节)<TAB>下载URL (大小/URL 列可空)
    - 单列 URL 行: 从 resolve 直链推断目录与文件名
    返回文件列表或 None。
    """
    t = (text or "").strip()
    if not t:
        return None
    if t[0] in "{[":
        try:
            data = json.loads(t)
        except Exception:
            data = None
        if data is not None:
            files = []
            models = data.get("models") if isinstance(data, dict) else data
            if isinstance(models, list):
                for mdl in models:
                    if not isinstance(mdl, dict):
                        continue
                    for f in (mdl.get("files") or []):
                        if not isinstance(f, dict):
                            continue
                        fname = os.path.basename(f.get("name") or "")
                        if not fname:
                            continue
                        fpath = (f.get("name") or fname).replace("\\", "/")
                        files.append({
                            "path": fpath,
                            "name": fname,
                            "size": f.get("size") or 0,
                            "parent_dir": os.path.dirname(fpath),
                            "local_folder": _guess_local_folder(fpath, folder_keys),
                            "direct_url": f.get("download_url") or "",
                        })
                if files:
                    return _mark_local_exists(files)
    lines = [ln for ln in t.splitlines() if ln.strip()]
    files = []
    tsv_rows = 0
    for ln in lines:
        cols = [c.strip() for c in ln.split("\t")]
        if len(cols) >= 2 and "." in cols[1]:
            folder = cols[0].replace("\\", "/").strip("/")
            if folder.lower().startswith("models/"):
                folder = folder[len("models/"):].strip("/")
            name = os.path.basename(cols[1].replace("\\", "/"))
            size = int(cols[2]) if len(cols) >= 3 and cols[2].isdigit() else 0
            durl = cols[3] if len(cols) >= 4 else ""
            if folder and folder in folder_keys:
                local_folder = folder
            elif folder:
                local_folder = _guess_local_folder(folder + "/" + name, folder_keys) or folder
            else:
                local_folder = _guess_local_folder(name, folder_keys)
            files.append({
                "path": (folder + "/" + name) if folder else name,
                "name": name,
                "size": size,
                "parent_dir": folder or "",
                "local_folder": local_folder,
                "direct_url": durl,
            })
            tsv_rows += 1
        elif len(cols) == 1 and cols[0].lower().startswith("http"):
            rp = _parse_resolve_url(cols[0])
            if rp:
                owner, rname, rev, fpath, source, base_url = rp
                name = os.path.basename(fpath)
                files.append({
                    "path": fpath,
                    "name": name,
                    "size": 0,
                    "parent_dir": os.path.basename(os.path.dirname(fpath)),
                    "local_folder": _guess_local_folder(fpath, folder_keys),
                    "direct_url": f"{base_url}/{owner}/{rname}/resolve/{rev}/{fpath}",
                })
                tsv_rows += 1
    if tsv_rows > 0:
        return _mark_local_exists(files)
    return None


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
        subpath = (payload.get("subpath") or "").strip()
        subpath_parts = [p for p in subpath.replace("\\", "/").split("/") if p and p != "."]
        rename_to = (payload.get("rename_to") or "").strip()
        if direct_url:
            direct_url = _to_hf_mirror(direct_url)

        dest_dir = _resolve_dest_dir(folder)
        if not dest_dir:
            return web.json_response({"error": f"未找到模型目录: {folder}"})

        if direct_url:
            fname = filename or os.path.basename(urllib.parse.urlparse(direct_url).path) or "model.bin"
            if subpath_parts:
                dest = os.path.join(dest_dir, *subpath_parts, fname)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
            else:
                dest = os.path.join(dest_dir, fname)
            final_dest = dest
            if rename_to and rename_to != fname:
                final_dest = os.path.join(os.path.dirname(dest), rename_to)
            task_id = str(uuid.uuid4())
            with _task_lock:
                _download_tasks[task_id] = {
                    "status": "connecting",
                    "filename": rename_to or fname,
                    "folder": folder,
                    "subpath": "/".join(subpath_parts),
                    "dest_path": final_dest,
                    "downloaded": 0,
                    "total": 0,
                    "start_time": time.time(),
                    "recent_chunks": [],
                    "error": None,
                    "cancel": False,
                }

            def _do_download():
                try:
                    if rename_to and rename_to != fname:
                        _download_direct_with_progress(direct_url, dest, task_id)
                        try:
                            if os.path.exists(final_dest):
                                os.remove(final_dest)
                            os.rename(dest, final_dest)
                        except Exception as re:
                            with _task_lock:
                                t = _download_tasks.get(task_id)
                                if t:
                                    t["status"] = "error"
                                    t["error"] = f"重命名失败: {re}"
                            return
                    else:
                        _download_direct_with_progress(direct_url, dest, task_id)
                except Exception as e:
                    with _task_lock:
                        t = _download_tasks.get(task_id)
                        if t:
                            t["status"] = "error"
                            t["error"] = str(e)

            thread = threading.Thread(target=_do_download, daemon=True)
            thread.start()
            return web.json_response({"task_id": task_id, "filename": rename_to or fname, "folder": folder, "dest_path": final_dest})
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
            rc = t.get("recent_chunks", [])
            if len(rc) >= 2:
                window_bytes = sum(sz for _, sz in rc)
                window_span = rc[-1][0] - rc[0][0]
                if window_span > 0:
                    speed = window_bytes / window_span
                else:
                    speed = downloaded / elapsed if elapsed > 0 else 0
            else:
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
    @routes.post("/qibo/modelscope/cancel_download")
    async def ms_cancel_download(request):
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        task_id = payload.get("task_id", "")
        with _task_lock:
            t = _download_tasks.get(task_id)
            if not t:
                return web.json_response({"error": "task not found"})
            t["cancel"] = True
        return web.json_response({"ok": True})

    @routes.post("/qibo/modelscope/delete")
    async def ms_delete(request):
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        models = payload.get("models") or []
        if isinstance(models, dict):
            models = [models]
        if not isinstance(models, list) or len(models) == 0:
            return web.json_response({"error": "models 为空或格式错误", "results": []})

        def _find_dir_readonly(folder):
            try:
                import folder_paths as fp
                if folder in fp.folder_names_and_paths:
                    dirs = fp.folder_names_and_paths[folder][0]
                    for d in dirs:
                        if os.path.basename(os.path.normpath(d)) == folder and os.path.isdir(d):
                            return d
                    for d in dirs:
                        if os.path.isdir(d):
                            return d
            except Exception:
                pass
            return None

        def _del_one(item):
            folder = (item.get("folder") or "").strip()
            subpath = (item.get("subpath") or "").strip()
            filename = (item.get("filename") or "").strip()
            if not folder or not filename:
                return {"folder": folder, "subpath": subpath, "filename": filename, "ok": False, "error": "folder/filename 为空"}
            dest_dir = _find_dir_readonly(folder)
            if not dest_dir:
                return {"folder": folder, "subpath": subpath, "filename": filename, "ok": False, "error": f"未知模型目录: {folder}"}
            parts = [p for p in subpath.replace("\\", "/").split("/") if p and p not in (".", "..")]
            dest = os.path.realpath(os.path.join(dest_dir, *parts, filename))
            base = os.path.realpath(dest_dir)
            if not dest.startswith(base + os.sep):
                return {"folder": folder, "subpath": subpath, "filename": filename, "ok": False, "error": "非法路径"}
            if not os.path.isfile(dest):
                return {"folder": folder, "subpath": subpath, "filename": filename, "ok": False, "error": "文件不存在"}
            try:
                os.remove(dest)
                return {"folder": folder, "subpath": subpath, "filename": filename, "ok": True, "path": dest}
            except Exception as e:
                return {"folder": folder, "subpath": subpath, "filename": filename, "ok": False, "error": str(e)}

        results = [_del_one(item) if isinstance(item, dict) else {"filename": "?", "ok": False, "error": "格式错误"} for item in models]
        ok_count = sum(1 for r in results if r.get("ok"))
        return web.json_response({"ok": ok_count, "total": len(results), "results": results})

    @routes.post("/qibo/modelscope/list_files")
    async def ms_list_files(request):
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        url = (payload.get("url") or "").strip()
        if not url:
            return web.json_response({"error": "url 为空", "files": []})
        try:
            import folder_paths as fp
            folder_keys = set(fp.folder_names_and_paths.keys())
        except Exception:
            folder_keys = set()
        rparsed = _parse_resolve_url(url)
        if rparsed:
            owner, name, rev, fpath, source, base_url = rparsed
            if source == "huggingface":
                direct_url = f"{_to_hf_mirror(base_url)}/{owner}/{name}/resolve/{rev}/{fpath}"
            else:
                direct_url = url
            ext = os.path.splitext(fpath)[1].lower()
            if ext in _MANIFEST_TEXT_EXTS:
                try:
                    text = await asyncio.to_thread(_fetch_url_text, direct_url)
                except Exception as e:
                    return web.json_response({"error": f"拉取清单文件失败: {e}", "files": []})
                files = _parse_manifest_text(text, folder_keys)
                if files is None:
                    return web.json_response({"error": f"清单文件内容无法解析（支持 JSON / TSV 目录<TAB>文件名<TAB>大小<TAB>URL）: {direct_url}", "files": []})
                return web.json_response({"files": files, "model_id": f"{owner}/{name}/{fname}"})
            size = await asyncio.to_thread(_head_resolve_file, direct_url)
            local_folder = _guess_local_folder(fpath, folder_keys)
            parent = os.path.basename(os.path.dirname(fpath))
            local_exists = False
            if local_folder:
                dest_dir = _resolve_dest_dir(local_folder)
                if dest_dir and os.path.exists(os.path.join(dest_dir, fname)):
                    local_exists = True
            return web.json_response({
                "files": [{
                    "path": fpath,
                    "name": fname,
                    "size": size,
                    "parent_dir": parent,
                    "local_folder": local_folder,
                    "direct_url": direct_url,
                    "local_exists": local_exists,
                }],
                "model_id": f"{owner}/{name}",
            })
        parsed = _parse_repo_url(url)
        if not parsed:
            m = _MS_DATASET_VIEW_RE.search(url)
            if m:
                api = ("https://www.modelscope.cn/api/v1/datasets/" + m.group(1) + "/" + m.group(2)
                       + "/repo?Revision=" + m.group(3) + "&FilePath=" + urllib.parse.quote(m.group(4)))
                try:
                    text = await asyncio.to_thread(_fetch_url_text, api)
                except Exception as e:
                    return web.json_response({"error": f"modelscope dataset 拉取失败: {e}", "files": []})
                files = _parse_manifest_text(text, folder_keys)
                if files is not None:
                    return web.json_response({"files": files, "model_id": f"{m.group(1)}/{m.group(2)}/{m.group(4)}"})
                return web.json_response({"error": "modelscope dataset 返回内容无法解析为清单", "files": []})
            try:
                text = await asyncio.to_thread(_fetch_url_text, url)
            except Exception:
                text = ""
            if text:
                files = _parse_manifest_text(text, folder_keys)
                if files is not None:
                    return web.json_response({"files": files, "model_id": url})
            return web.json_response({"error": "无法解析 URL（支持 modelscope 仓库/直链/dataset 清单、HF 兼容站点、JSON/TSV 文本清单直链）", "files": []})
        owner, name, rev, path, source, base_url = parsed
        try:
            if source == "huggingface":
                base_url = _to_hf_mirror(base_url)
                files = await asyncio.to_thread(_list_hf_repo_files, owner, name, rev, path, base_url)
            else:
                files = await asyncio.to_thread(_list_repo_files, owner, name, rev, path)
        except Exception as e:
            return web.json_response({"error": f"列文件失败: {e}", "files": []})
        return web.json_response({"files": files, "model_id": f"{owner}/{name}"})

    @routes.post("/qibo/fetch_text")
    async def qibo_fetch_text(request):
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        url = (payload.get("url") or "").strip()
        if not url:
            return web.json_response({"error": "url 为空"})
        try:
            def _fetch():
                import urllib.request as _ur
                req = _ur.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with _ur.urlopen(req, timeout=15) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            text = await asyncio.to_thread(_fetch)
            return web.json_response({"text": text})
        except Exception as e:
            return web.json_response({"error": f"获取失败: {e}"})

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
            direct_url = _to_hf_mirror(direct_url) if direct_url else direct_url
            fname = f.get("name") or os.path.basename(f.get("path", ""))
            subpath = (f.get("subpath") or "").strip()
            subpath_parts = [p for p in subpath.replace("\\", "/").split("/") if p and p != "."]
            rename_to = (f.get("rename_to") or "").strip()
            dest_dir = _resolve_dest_dir(folder)
            if not dest_dir:
                results.append({"name": rename_to or fname, "error": f"未找到目录: {folder}"})
                continue
            if subpath_parts:
                dest = os.path.join(dest_dir, *subpath_parts, fname)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
            else:
                dest = os.path.join(dest_dir, fname)
            final_dest = dest
            if rename_to and rename_to != fname:
                final_dest = os.path.join(os.path.dirname(dest), rename_to)
            try:
                res = await asyncio.to_thread(_download_direct, direct_url, dest)
                if rename_to and rename_to != fname and res.get("ok"):
                    try:
                        if os.path.exists(final_dest):
                            os.remove(final_dest)
                        os.rename(dest, final_dest)
                        res["full_path"] = final_dest
                    except Exception as re:
                        res["ok"] = False
                        res["error"] = f"重命名失败: {re}"
                        res["full_path"] = dest
                res["folder"] = folder
                if not res.get("full_path"):
                    res["full_path"] = final_dest
                res["name"] = rename_to or fname
                results.append(res)
            except Exception as e:
                results.append({"name": rename_to or fname, "error": str(e)})
        ok_count = sum(1 for r in results if r.get("ok"))
        return web.json_response({"results": results, "total": len(results), "ok": ok_count})
