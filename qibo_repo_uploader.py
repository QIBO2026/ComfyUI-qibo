import os
import json
import hashlib
import threading
import subprocess
import time
import base64
import requests
from PIL import Image
from io import BytesIO
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

try:
    import numpy as np
    import torch
    _HAS_TORCH = True
except Exception:
    _HAS_TORCH = False

REPO_NAME = "qibo_ref_images"
MODELSCOPE_HOST = "https://modelscope.cn"
REF_DIR_IN_REPO = "ref_images"
MAX_EDGE = 2048
JPEG_QUALITY = 85

_lock = threading.Lock()
_cache = None
_cache_loaded = False
_user_info_cache = {}

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.join(_BASE_DIR, "qibo_ref_repo")
_CACHE_FILE = os.path.join(_BASE_DIR, "qibo_ref_md5_cache.json")


def _load_cache():
    global _cache, _cache_loaded
    if _cache_loaded:
        return
    _cache_loaded = True
    try:
        if os.path.exists(_CACHE_FILE):
            with open(_CACHE_FILE, "r", encoding="utf-8") as f:
                _cache = json.load(f)
        else:
            _cache = {}
    except Exception:
        _cache = {}


def _save_cache():
    try:
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ [repo_uploader] 缓存写入失败: {e}", flush=True)


def _get_user_info(token):
    """用 token 调 /openapi/v1/users/me 获取 (username, email)。按 token 前缀缓存。"""
    if not token:
        return None, None
    cache_key = token[:16]
    if cache_key in _user_info_cache:
        return _user_info_cache[cache_key]
    headers = {
        "Authorization": f"Bearer {token.strip()}",
        "User-Agent": "modelscope-comfyui-plugin/2.0",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.get(f"{MODELSCOPE_HOST}/openapi/v1/users/me", headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json().get("data", resp.json())
            username = (data.get("Username") or data.get("username")
                        or data.get("name") or data.get("preferred_username") or "")
            email = data.get("Email") or data.get("email") or ""
            if username:
                info = (username, email or f"{username}@modelscope.cn")
                _user_info_cache[cache_key] = info
                return info
        print(f"⚠️ [repo_uploader] 获取用户信息失败: HTTP {resp.status_code} {resp.text[:120]}", flush=True)
    except Exception as e:
        print(f"⚠️ [repo_uploader] 获取用户信息异常: {e}", flush=True)
    return None, None


def _create_repo(token, username):
    """调 POST /api/v1/datasets 创建数据集 {username}/qibo_ref_images。

    数据集端点要求 multipart/form-data（非 JSON），且认证需 cookie m_session_id + Bearer 双发。
    字段：Owner/Name/Visibility/License/Description（PascalCase）。
    """
    import uuid
    tok = token.strip()
    headers = {
        "Authorization": f"Bearer {tok}",
        "User-Agent": "modelscope-comfyui-plugin/2.0",
        "X-Request-ID": uuid.uuid4().hex,
    }
    form_fields = {
        "Owner": username,
        "Name": REPO_NAME,
        "Visibility": "5",
        "License": "Apache-2.0",
        "Description": "QIBO ComfyUI 参考图托管数据集（自动创建）",
    }
    files = {k: (None, str(v)) for k, v in form_fields.items()}
    cookies = {"m_session_id": tok}
    try:
        resp = requests.post(f"{MODELSCOPE_HOST}/api/v1/datasets",
                             headers=headers, files=files, cookies=cookies, timeout=20)
        if resp.status_code in (200, 201):
            print(f"✅ [repo_uploader] 已创建数据集 {username}/{REPO_NAME}", flush=True)
            return True
        txt = resp.text[:300]
        if "already exist" in txt.lower() or "已存在" in txt or "exist" in txt.lower():
            return True
        print(f"⚠️ [repo_uploader] 创建数据集失败: HTTP {resp.status_code} {txt}", flush=True)
    except Exception as e:
        print(f"⚠️ [repo_uploader] 创建数据集异常: {e}", flush=True)
    return False


def _ensure_repo_public(token, username):
    """确保数据集 {username}/{REPO_NAME} 可见性为公开（Visibility=5）。

    Visibility 枚举：1=private, 3=internal, 5=public。创建时若误传 1 会致公开 URL 403/404。
    用 GET 查可见性，非 5 则 PUT /api/v1/datasets/{数字Id} 改公开。
    """
    tok = token.strip()
    headers = {"Authorization": f"Bearer {tok}", "User-Agent": "modelscope-comfyui-plugin/2.0"}
    cookies = {"m_session_id": tok}
    repo_id = _repo_id_for(username)
    try:
        resp = requests.get(f"{MODELSCOPE_HOST}/api/v1/datasets/{repo_id}",
                            headers=headers, cookies=cookies, timeout=15)
        data = resp.json().get("Data", {}) or {}
        vis = data.get("Visibility")
        if vis == 5:
            return True
        ds_id = data.get("Id")
        if not ds_id:
            print(f"⚠️ [repo_uploader] 无法获取数据集 {repo_id} 的 Id，跳过公开设置", flush=True)
            return False
        r = requests.put(f"{MODELSCOPE_HOST}/api/v1/datasets/{ds_id}",
                         headers={**headers, "Content-Type": "application/json"},
                         cookies=cookies, json={"Visibility": 5}, timeout=15)
        if r.status_code in (200, 201) and r.json().get("Code") in (200, 201):
            print(f"✅ [repo_uploader] 已将数据集 {repo_id} 设为公开", flush=True)
            return True
        print(f"⚠️ [repo_uploader] 设置公开失败: HTTP {r.status_code} {r.text[:200]}", flush=True)
    except Exception as e:
        print(f"⚠️ [repo_uploader] 设置公开异常: {e}", flush=True)
    return False


def _work_dir_for(username):
    return os.path.join(_REPO_ROOT, username)


def _repo_id_for(username):
    return f"{username}/{REPO_NAME}"


def _clone_url_for(token, username):
    host = MODELSCOPE_HOST.split("://")[1]
    return f"https://oauth2:{token}@{host}/datasets/{_repo_id_for(username)}.git"


def _force_rmtree(path):
    """Windows 上 .git 内 pack 文件常带只读属性，shutil.rmtree 会失败。先 chmod 再删，失败回退 rd /s /q。"""
    if not os.path.exists(path):
        return True
    import shutil, stat
    def _on_rm_error(func, p, exc_info):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass
    try:
        shutil.rmtree(path, onerror=_on_rm_error)
        if not os.path.exists(path):
            return True
    except Exception:
        pass
    if os.name == "nt":
        try:
            r = subprocess.run(["cmd", "/c", "rd", "/s", "/q", path],
                               capture_output=True, text=True, timeout=30)
            return r.returncode == 0 and not os.path.exists(path)
        except Exception:
            return not os.path.exists(path)
    try:
        subprocess.run(["rm", "-rf", path], capture_output=True, timeout=30)
    except Exception:
        pass
    return not os.path.exists(path)


def _ensure_repo_clone(token, username):
    """确保本地有 {username}/qibo_ref_images 数据集的 clone。不存在或 remote 不匹配时重 clone。"""
    work_dir = _work_dir_for(username)
    expected_clone_url = _clone_url_for(token, username)
    expected_repo_id = _repo_id_for(username)
    if os.path.isdir(os.path.join(work_dir, ".git")):
        rc, out, _ = _git(["config", "--get", "remote.origin.url"], work_dir, username, "", timeout=10)
        cur_remote = (out or "").strip()
        if expected_repo_id in cur_remote and ("datasets/" in cur_remote or "models/" in cur_remote):
            _ensure_repo_public(token, username)
            return True, work_dir
        print(f"ℹ️ [repo_uploader] 本地 clone remote 不匹配 ({cur_remote[:60]})，重新 clone...", flush=True)
        if not _force_rmtree(work_dir):
            print(f"❌ [repo_uploader] 旧目录删除失败: {work_dir}", flush=True)
            return False, work_dir
    os.makedirs(_REPO_ROOT, exist_ok=True)
    if os.path.exists(work_dir):
        if not _force_rmtree(work_dir):
            print(f"❌ [repo_uploader] clone 前清空目录失败: {work_dir}", flush=True)
            return False, work_dir
    clone_url = _clone_url_for(token, username)
    for attempt in (1, 2):
        r = subprocess.run(
            ["git", "clone", "--depth", "1", clone_url, work_dir],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode == 0:
            _ensure_repo_public(token, username)
            return True, work_dir
        err = r.stderr or ""
        if attempt == 1 and ("not found" in err.lower() or "does not exist" in err.lower()
                             or "repository" in err.lower() and "not" in err.lower()):
            print(f"ℹ️ [repo_uploader] 仓库 {username}/{REPO_NAME} 不存在，尝试自动创建...", flush=True)
            if _create_repo(token, username):
                continue
        print(f"❌ [repo_uploader] clone 失败: {err[:200]}", flush=True)
        return False, work_dir
    return False, work_dir


def _git(args, work_dir, author_name, author_email, timeout=30):
    cmd = ["git"] + args
    env = dict(os.environ)
    env["GIT_AUTHOR_EMAIL"] = author_email
    env["GIT_AUTHOR_NAME"] = author_name
    env["GIT_COMMITTER_EMAIL"] = author_email
    env["GIT_COMMITTER_NAME"] = author_name
    try:
        r = subprocess.run(cmd, cwd=work_dir, capture_output=True, text=True, timeout=timeout, env=env)
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return -1, "", str(e)


def _prepare_pil(img_pil):
    w, h = img_pil.size
    if max(w, h) > MAX_EDGE:
        ratio = MAX_EDGE / max(w, h)
        img_pil = img_pil.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
    if img_pil.mode != "RGB":
        img_pil = img_pil.convert("RGB")
    buf = BytesIO()
    img_pil.save(buf, format="JPEG", quality=JPEG_QUALITY)
    data = buf.getvalue()
    return img_pil, data


def _md5_of_bytes(data):
    return hashlib.md5(data).hexdigest()


def _public_url(filename_in_repo, username):
    return f"{MODELSCOPE_HOST}/datasets/{_repo_id_for(username)}/resolve/master/{REF_DIR_IN_REPO}/{filename_in_repo}"


def _url_reachable(url, timeout=6):
    """校验 URL 可访问性。HEAD 失败时回退 GET（仅读状态码不读 body）。"""
    for method in ("HEAD", "GET"):
        try:
            req = Request(url, method=method)
            with urlopen(req, timeout=timeout) as resp:
                return resp.status == 200
        except HTTPError as e:
            if e.code == 404:
                return False
            if method == "HEAD" and e.code in (405, 501):
                continue
            return e.code == 200
        except (URLError, TimeoutError, Exception):
            if method == "HEAD":
                continue
            return False
    return False


def upload_pil_image(img_pil, token):
    """上传 PIL 图片到 ModelScope 仓库，返回 (公开URL, 处理后PIL)。
    失败时返回 (None, pil)。调用方应回退 base64。
    仓库归属由 token 对应账号决定，自动适配不同账号。"""
    global _cache
    _load_cache()
    prepared_pil, data = _prepare_pil(img_pil)
    md5 = _md5_of_bytes(data)
    username, email = _get_user_info(token)
    if not username:
        print(f"⚠️ [repo] 无法获取 token 账号信息，回退 base64", flush=True)
        return None, prepared_pil
    with _lock:
        if _cache and md5 in _cache:
            url = _cache[md5]
            if _url_reachable(url):
                print(f"  💾 [repo] MD5 命中缓存，复用已上传 URL", flush=True)
                return url, prepared_pil
            print(f"  ⚠️ [repo] 缓存 URL 不可访问(404)，重新上传: {url}", flush=True)
            _cache.pop(md5, None)
            _save_cache()
        ok, work_dir = _ensure_repo_clone(token, username)
        if not ok:
            return None, prepared_pil
        filename = f"{md5}.jpg"
        dest = os.path.join(work_dir, REF_DIR_IN_REPO, filename)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(data)

        def _try_add_commit_push():
            rc1, _, err1 = _git(["add", f"{REF_DIR_IN_REPO}/{filename}"], work_dir, username, email)
            if rc1 != 0:
                return False, err1
            rc2, _, err2 = _git(["commit", "-m", f"upload ref {md5}"], work_dir, username, email)
            if rc2 != 0 and "nothing to commit" not in err2 and "nothing to commit" not in _git(["status", "--short"], work_dir, username, email)[1]:
                return False, err2
            rc3, _, err3 = _git(["push", "origin", "master"], work_dir, username, email, timeout=60)
            if rc3 != 0:
                return False, err3
            return True, ""

        ok_push, push_err = _try_add_commit_push()
        if not ok_push:
            print(f"⚠️ [repo] git push 首次失败: {push_err[:150]}，尝试 fetch+reset 同步远程后重试...", flush=True)
            _git(["fetch", "origin", "master"], work_dir, username, email, timeout=30)
            _git(["reset", "--hard", "origin/master"], work_dir, username, email, timeout=15)
            with open(dest, "wb") as f:
                f.write(data)
            ok_push, push_err = _try_add_commit_push()
        if not ok_push:
            print(f"❌ [repo] git push 重试仍失败: {push_err[:150]}", flush=True)
            return None, prepared_pil
        url = _public_url(filename, username)
        if _cache is None:
            _cache = {}
        _cache[md5] = url
        _save_cache()
        print(f"  ✅ [repo] 已上传 {filename} ({len(data)//1024}KB) → {url}", flush=True)
        return url, prepared_pil


def tensor_to_repo_url(image_tensor, token):
    """上传 tensor 到仓库返回 URL；失败回退 base64 data URL。"""
    try:
        if len(image_tensor.shape) == 4:
            image_tensor = image_tensor.squeeze(0)
        if image_tensor.max() <= 1.0:
            image_np = (image_tensor.cpu().numpy() * 255).astype(np.uint8)
        else:
            image_np = image_tensor.cpu().numpy().astype(np.uint8)
        pil_image = Image.fromarray(image_np)
        url, _ = upload_pil_image(pil_image, token)
        if url:
            return url
        buffer = BytesIO()
        pil_image.save(buffer, format="JPEG", quality=JPEG_QUALITY)
        b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
        print(f"  ↩️ [repo] 上传失败，回退 base64", flush=True)
        return f"data:image/jpeg;base64,{b64}"
    except Exception as e:
        raise Exception(f"图像上传/转换失败: {str(e)}")


def upload_images_to_repo(images_list, token):
    """批量上传图片列表到仓库，返回 (image_urls, compressed_pils, temp_img_paths)。
    上传失败的项 url 置 None（不回退 base64），调用方据 None 报错或过滤。"""
    image_urls = []
    compressed_pils = []
    temp_img_paths = []
    for idx, img_tensor in enumerate(images_list):
        pil_obj = None
        try:
            img_np = 255. * img_tensor.cpu().numpy()
            img_pil = Image.fromarray(np.clip(img_np, 0, 255).astype(np.uint8))
            url, prepared = upload_pil_image(img_pil, token)
            pil_obj = prepared
            if url:
                image_urls.append(url)
                w, h = prepared.size
                print(f"  ✅ 第{idx+1}/{len(images_list)}张已上传仓库 ({w}x{h})", flush=True)
            else:
                image_urls.append(None)
                print(f"  ❌ 第{idx+1}/{len(images_list)}张仓库上传失败（token/网络/git 异常），不回退 base64", flush=True)
            compressed_pils.append(prepared)
            temp_img_paths.append(None)
        except Exception as e:
            print(f"⚠️ 第{idx+1}张处理异常: {str(e)}", flush=True)
            image_urls.append(None)
            compressed_pils.append(pil_obj)
            temp_img_paths.append(None)
    valid = sum(1 for u in image_urls if u)
    repo_count = sum(1 for u in image_urls if u and u.startswith("http"))
    print(f"📤 准备完成: {valid}/{len(images_list)} 张可用 (仓库URL {repo_count} 张)", flush=True)
    return image_urls, compressed_pils, temp_img_paths


def pil_to_repo_url_or_base64(img_pil, token):
    """供拼接网格图等场景使用：上传 PIL 到仓库，失败抛异常（不回退 base64）。返回 (url, True)。"""
    url, prepared = upload_pil_image(img_pil, token)
    if url:
        return url, True
    raise Exception("拼接网格图仓库上传失败（token/网络/git 异常），不回退 base64")
