"""QIBO 工作流体检服务端路由。

POST /qibo/workflow_check
  body: {"nodes": {node_id: {"class_type": str, "inputs": {field: value}}}}
  返回: {"missing_nodes": [...], "missing_models": [...], "present_models": [...]}

不依赖工作流执行，可在缺节点/缺模型时直接核对当前画布引用是否齐全。

POST /qibo/install_missing_nodes
  body: {"nodes": [{"class_type": str, "install_url": str}, ...]}
  返回: {"status": "started", "total": N}  启动后台线程逐个 git clone + pip install

GET /qibo/install_progress
  返回: {"status": "running|done|idle", "total": N, "done": N, "failed": N,
         "current": str, "results": [{"class_type","url","status","msg"}, ...]}
"""

import os
import json
import threading
import subprocess
import sys
import time
import asyncio

try:
    from server import PromptServer
    from aiohttp import web
    SERVER_AVAILABLE = True
except ImportError:
    SERVER_AVAILABLE = False
    PromptServer = None
    web = None

_HERE = os.path.dirname(os.path.abspath(__file__))
_MANAGER_MAP = os.path.normpath(
    os.path.join(_HERE, "..", "ComfyUI-Manager", "extension-node-map.json")
)
_CUSTOM_NODES_DIR = os.path.normpath(os.path.join(_HERE, ".."))

_install_lock = threading.Lock()
_install_state = {
    "status": "idle",
    "total": 0,
    "done": 0,
    "failed": 0,
    "current": "",
    "results": [],
    "started_at": 0,
}


def _set_install_state(**kwargs):
    with _install_lock:
        _install_state.update(kwargs)


def _get_install_state():
    with _install_lock:
        return dict(_install_state)


def _repo_dir_name(url):
    base = url.rstrip("/").split("/")[-1]
    if base.endswith(".git"):
        base = base[:-4]
    return base


def _run_install_one(class_type, install_url):
    node_dir = _repo_dir_name(install_url)
    dest = os.path.join(_CUSTOM_NODES_DIR, node_dir)
    if os.path.exists(dest):
        return "skip", f"目录已存在: {node_dir}"
    try:
        proc = subprocess.run(
            ["git", "clone", "--recursive", install_url, dest],
            cwd=_CUSTOM_NODES_DIR,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if proc.returncode != 0:
            return "error", f"git clone 失败: {proc.stderr[:300]}"
    except subprocess.TimeoutExpired:
        return "error", "git clone 超时 (>600s)"
    except Exception as e:
        return "error", f"git clone 异常: {e}"

    req_file = os.path.join(dest, "requirements.txt")
    if os.path.exists(req_file):
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", req_file],
                capture_output=True,
                text=True,
                timeout=600,
            )
        except Exception:
            pass
    return "ok", f"已克隆到 {node_dir}（重启 ComfyUI 后生效）"


def _install_worker(nodes):
    _set_install_state(
        status="running",
        total=len(nodes),
        done=0,
        failed=0,
        current="",
        results=[],
        started_at=time.time(),
    )
    done = 0
    failed = 0
    results = []
    for i, item in enumerate(nodes):
        ct = item.get("class_type", "?")
        url = item.get("install_url", "")
        if not url:
            results.append({"class_type": ct, "url": "", "status": "error", "msg": "无 install_url"})
            failed += 1
            _set_install_state(done=done, failed=failed, results=list(results), current=ct)
            continue
        _set_install_state(current=f"{ct}  克隆中...")
        status, msg = _run_install_one(ct, url)
        results.append({"class_type": ct, "url": url, "status": status, "msg": msg})
        if status == "ok":
            done += 1
        else:
            failed += 1
        _set_install_state(done=done, failed=failed, results=list(results), current=ct)
    _set_install_state(status="done", current="")


def _load_node_install_map():
    try:
        with open(_MANAGER_MAP, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    m = {}
    for url, val in data.items():
        try:
            names = val[0]
            for nm in names:
                if isinstance(nm, str) and nm not in m:
                    m[nm] = url
        except Exception:
            pass
    return m


MODEL_FIELD_FOLDER = {
    ("CheckpointLoaderSimple", "ckpt_name"): "checkpoints",
    ("CheckpointLoader", "ckpt_name"): "checkpoints",
    ("CheckpointLoaderGGUF", "ckpt_name"): "checkpoints",
    ("UNETLoader", "unet_name"): "diffusion_models",
    ("UNETLoaderGGUF", "unet_name"): "diffusion_models",
    ("UnetLoaderGGUF", "unet_name"): "diffusion_models",
    ("LoraLoader", "lora_name"): "loras",
    ("LoraLoaderModelOnly", "lora_name"): "loras",
    ("LoraLoaderGGUF", "lora_name"): "loras",
    ("CLIPLoader", "clip_name"): "text_encoders",
    ("CLIPLoaderGGUF", "clip_name"): "text_encoders",
    ("DualCLIPLoader", "clip_name1"): "text_encoders",
    ("DualCLIPLoader", "clip_name2"): "text_encoders",
    ("VAELoader", "vae_name"): "vae",
    ("VAELoaderFile", "vae_name"): "vae",
    ("ControlNetLoader", "control_net_name"): "controlnet",
    ("ControlNetLoadSimple", "control_net_name"): "controlnet",
    ("ControlNetLoadSimpleAdvanced", "control_net_name"): "controlnet",
    ("ControlNetLoaderAdvanced", "control_net_name"): "controlnet",
    ("DiffControlNetLoader", "model_name"): "controlnet",
    ("UpscaleModelLoader", "model_name"): "upscale_models",
    ("UpscaleModelLoaderUrl", "model_name"): "upscale_models",
    ("GLIGENLoader", "gligen_name"): "gligen",
    ("HypernetworkLoader", "hypernetwork_name"): "hypernetworks",
    ("StyleModelLoader", "style_model_name"): "style_models",
    ("QwenImage21Cache", "model_name"): "diffusion_models",
    ("QwenImage21CacheFP8", "model_name"): "diffusion_models",
    ("QwenImage21CacheINT8", "model_name"): "diffusion_models",
    ("QwenImage21VAELoader", "vae_name"): "vae",
    ("Qwen2VLLoader", "model_name"): "llms",
    ("Qwen2VLGGUFLoader", "model_name"): "llms",
    ("LTXVLoader", "model_name"): "diffusion_models",
    ("LTXVModelLoader", "model_name"): "diffusion_models",
    ("MiniMaxH3Loader", "model_name"): "diffusion_models",
}

FIELD_NAME_FOLDER = [
    ("ckpt_name", "checkpoints"),
    ("unet_name", "diffusion_models"),
    ("lora_name", "loras"),
    ("clip_name", "text_encoders"),
    ("clip_name1", "text_encoders"),
    ("clip_name2", "text_encoders"),
    ("vae_name", "vae"),
    ("control_net_name", "controlnet"),
    ("controlnet_name", "controlnet"),
    ("gligen_name", "gligen"),
    ("hypernetwork_name", "hypernetworks"),
    ("style_model_name", "style_models"),
    ("upscaler", "upscale_models"),
    ("upscale_model", "upscale_models"),
]

MODEL_EXTENSIONS = {
    ".safetensors", ".gguf", ".ckpt", ".pth", ".pt", ".bin",
    ".onnx", ".t5xxl", ".model", ".vae", ".sft", ".fp8", ".fp16",
    ".bf16", ".q8_0", ".q4_k_m", ".q4_k_s", ".q5_k_m", ".q5_k_s",
    ".pt2", ".pkl", ".gguf2", ".ot", ".mlmodel", ".engine",
}


def _resolve_folder(class_type, field):
    folder = MODEL_FIELD_FOLDER.get((class_type, field))
    if folder:
        return folder
    fl = field.lower()
    for fname, fld in FIELD_NAME_FOLDER:
        if fl == fname or fl.endswith("_" + fname) or fl.endswith(fname):
            return fld
    if fl == "model_name" or fl.endswith("_model_name"):
        ct = (class_type or "").lower()
        if any(x in ct for x in ("unet", "diffusion", "qwen", "ltx", "minimax", "h3")):
            return "diffusion_models"
        if "control" in ct:
            return "controlnet"
        if "upscale" in ct:
            return "upscale_models"
        if any(x in ct for x in ("llm", "qwen2vl", "text", "clip")):
            return "text_encoders"
        if "vae" in ct:
            return "vae"
        return "checkpoints"
    return None


def _guess_folder_by_class(class_type):
    ct = (class_type or "").lower()
    if any(x in ct for x in ("unet", "diffusion", "qwen", "ltx", "minimax", "h3")):
        return "diffusion_models"
    if "control" in ct:
        return "controlnet"
    if "upscale" in ct:
        return "upscale_models"
    if "lora" in ct:
        return "loras"
    if any(x in ct for x in ("llm", "qwen2vl", "text", "clip")):
        return "text_encoders"
    if "vae" in ct:
        return "vae"
    if "checkpoint" in ct or "ckpt" in ct:
        return "checkpoints"
    return "checkpoints"


def _split_subpath(value):
    """把含子目录的模型路径拆成 (subpath, basename)。
    subpath 用 / 分隔（前端/下载时再按系统拼接）。
    例: "subfolder/model.gguf" -> ("subfolder", "model.gguf")
        "model.gguf" -> ("", "model.gguf")
    """
    if not isinstance(value, str):
        return "", value
    norm = value.replace("\\", "/")
    if "/" not in norm:
        return "", value
    idx = norm.rfind("/")
    subpath = norm[:idx].strip("/")
    basename = norm[idx + 1:].strip()
    return subpath, basename


import re as _re
_PLACEHOLDER_RE = _re.compile(r"请把.*?放到.*?models?[/\\]([^\s/\\）)\]\s]+)", _re.IGNORECASE)
_PLACEHOLDER_RE2 = _re.compile(r"请放到.*?models?[/\\]([^\s/\\）)\]\s]+)", _re.IGNORECASE)
_PLACEHOLDER_RE3 = _re.compile(r"放到.*?models?[/\\]([^\s/\\）)\]\s]+)", _re.IGNORECASE)


def _parse_placeholder_folder(value):
    """识别 widget 值里的占位提示，如 '（请把模型放到 models/LLM）' -> 'LLM'。
    返回 folder 名；不匹配返回 None。
    """
    if not isinstance(value, str) or not value:
        return None
    if "请把" not in value and "请放到" not in value and "放到" not in value:
        return None
    for pat in (_PLACEHOLDER_RE, _PLACEHOLDER_RE2, _PLACEHOLDER_RE3):
        m = pat.search(value)
        if m:
            return m.group(1).strip()
    return None


def _list_folder(folder):
    try:
        import folder_paths as fp
        if folder not in fp.folder_names_and_paths:
            return None
        return list(fp.get_filename_list(folder))
    except Exception:
        return None


def _check(payload):
    from nodes import NODE_CLASS_MAPPINGS
    nodes_map = payload.get("nodes") or {}
    type_counter = {}
    required_models = []
    for node_id, node in nodes_map.items():
        if not isinstance(node, dict):
            continue
        class_type = node.get("class_type", "")
        if class_type:
            type_counter[class_type] = type_counter.get(class_type, 0) + 1
        inputs = node.get("inputs", {}) or {}
        field_hints = node.get("field_hints", {}) or {}
        node_hint_folder = None
        for _fn, _hints in field_hints.items():
            if not isinstance(_hints, list):
                continue
            for _h in _hints:
                _fh = _parse_placeholder_folder(_h)
                if _fh:
                    node_hint_folder = _fh
                    break
            if node_hint_folder:
                break
        for k, v in inputs.items():
            if not isinstance(v, str) or not v:
                continue
            ph_folder = _parse_placeholder_folder(v)
            if ph_folder:
                required_models.append({
                    "node_id": str(node_id),
                    "class_type": class_type,
                    "field": k,
                    "value": "",
                    "orig_value": v,
                    "subpath": "",
                    "folder": ph_folder,
                    "is_placeholder": True,
                })
                continue
            folder = _resolve_folder(class_type, k)
            if not folder and node_hint_folder:
                ext = os.path.splitext(v.lower())[1]
                if ext in MODEL_EXTENSIONS or "/" in v.replace("\\", "/"):
                    folder = node_hint_folder
            if not folder:
                ext = os.path.splitext(v.lower())[1]
                if ext in MODEL_EXTENSIONS:
                    folder = _guess_folder_by_class(class_type)
                else:
                    continue
            subpath, basename = _split_subpath(v)
            required_models.append({
                "node_id": str(node_id),
                "class_type": class_type,
                "field": k,
                "value": basename,
                "orig_value": v,
                "subpath": subpath,
                "folder": folder,
                "is_placeholder": False,
            })

    install_map = _load_node_install_map()
    required_nodes = []
    for ct, cnt in type_counter.items():
        registered = ct in NODE_CLASS_MAPPINGS
        entry = {
            "class_type": ct,
            "count": cnt,
            "registered": registered,
        }
        if not registered:
            entry["install_url"] = install_map.get(ct)
        required_nodes.append(entry)
    required_nodes.sort(key=lambda x: (x["registered"], x["class_type"].lower()))

    folder_cache = {}
    for ref in required_models:
        folder = ref["folder"]
        if folder not in folder_cache:
            folder_cache[folder] = _list_folder(folder)
        available = folder_cache[folder]
        ref["available"] = available or []
        if ref.get("is_placeholder"):
            ref["status"] = "placeholder"
            continue
        if available is None:
            ref["status"] = "folder_unknown"
        else:
            subpath = ref.get("subpath", "")
            basename = ref["value"]
            if subpath:
                rel_posix = subpath + "/" + basename
                rel_win = subpath.replace("/", "\\") + "\\" + basename
                present = (rel_posix in available) or (rel_win in available) or (basename in available)
            else:
                present = basename in available
            ref["status"] = "present" if present else "missing"

    missing_node_types = sorted({n["class_type"] for n in required_nodes if not n["registered"]})
    missing_models = [m for m in required_models if m["status"] != "present"]
    present_models = [m for m in required_models if m["status"] == "present"]

    return {
        "required_nodes": required_nodes,
        "required_models": required_models,
        "missing_node_types": missing_node_types,
        "missing_models": missing_models,
        "present_models": present_models,
        "received_node_count": len(nodes_map),
        "registered_node_count": len(NODE_CLASS_MAPPINGS),
    }


def register_server_routes():
    if not SERVER_AVAILABLE:
        return

    routes = PromptServer.instance.routes

    @routes.post("/qibo/workflow_check")
    async def qibo_workflow_check(request):
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        try:
            result = _check(payload)
        except Exception as e:
            result = {
                "error": str(e),
                "missing_nodes": [],
                "missing_models": [],
                "present_models": [],
            }
        return web.json_response(result)
    @routes.post("/qibo/install_missing_nodes")
    async def qibo_install_missing_nodes(request):
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        nodes = payload.get("nodes") or []
        if not isinstance(nodes, list) or len(nodes) == 0:
            return web.json_response({"error": "nodes 为空或格式错误"})
        st = _get_install_state()
        if st.get("status") == "running":
            return web.json_response({"error": "已有安装任务在运行，请等待完成", "status": "running"})
        clean = []
        for item in nodes:
            ct = item.get("class_type") if isinstance(item, dict) else None
            url = item.get("install_url") if isinstance(item, dict) else None
            if ct and url:
                clean.append({"class_type": ct, "install_url": url})
        if not clean:
            return web.json_response({"error": "无有效 (class_type + install_url) 项"})
        t = threading.Thread(target=_install_worker, args=(clean,), daemon=True)
        t.start()
        return web.json_response({"status": "started", "total": len(clean)})

    @routes.get("/qibo/install_progress")
    async def qibo_install_progress(request):
        return web.json_response(_get_install_state())
    @routes.post("/qibo/update_self")
    async def qibo_update_self(request):
        def _run_git(args, timeout=120):
            return subprocess.run(
                ["git"] + args, cwd=_HERE,
                capture_output=True, text=True, timeout=timeout,
            )
        def _force_sync(remote_name, remote_url, branch="master"):
            # 强制对齐到远程分支，等同重新 clone 但保留 .git；会丢弃本地未提交修改
            subprocess.run(["git", "merge", "--abort"], cwd=_HERE, capture_output=True, text=True)
            fetch_args = ["fetch", remote_name, branch]
            if remote_name not in ("origin", "github"):
                fetch_args = ["fetch", remote_url, branch]
            fproc = _run_git(fetch_args, timeout=180)
            if fproc.returncode != 0:
                return fproc, "fetch"
            rproc = _run_git(["reset", "--hard", f"FETCH_HEAD"])
            if rproc.returncode != 0:
                return rproc, "reset"
            _run_git(["clean", "-fd"])
            return rproc, "ok"
        def _clone_fallback(remote_url, branch="master"):
            # 最后兜底：clone 到临时目录，复制全部内容（含 .git）覆盖当前目录
            import tempfile, shutil
            tmp = tempfile.mkdtemp(prefix="qibo_clone_")
            try:
                cproc = subprocess.run(
                    ["git", "clone", "--depth", "1", "-b", branch, remote_url, tmp],
                    capture_output=True, text=True, timeout=300,
                )
                if cproc.returncode != 0:
                    return cproc
                # 删除临时目录的 .git 配置中可能残留的临时路径引用无影响，直接整体复制
                for entry in os.listdir(_HERE):
                    if entry == ".git":
                        continue
                    p = os.path.join(_HERE, entry)
                    try:
                        if os.path.isdir(p):
                            shutil.rmtree(p, ignore_errors=True)
                        else:
                            os.remove(p)
                    except Exception:
                        pass
                for entry in os.listdir(tmp):
                    src = os.path.join(tmp, entry)
                    dst = os.path.join(_HERE, entry)
                    try:
                        if os.path.isdir(src):
                            shutil.copytree(src, dst, dirs_exist_ok=True)
                        else:
                            shutil.copy2(src, dst)
                    except Exception:
                        pass
                cproc.stdout = (cproc.stdout or "") + "\n[已通过 git clone 兜底重新同步]"
                return cproc
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        _QIBO_GITEE_URL = "https://gitee.com/qq719703856/ComfyUI-qibo.git"
        _QIBO_GITHUB_URL = "https://github.com/QIBO2026/ComfyUI-qibo.git"
        def _ensure_git_repo():
            # 自愈：下载解压安装时无 .git，或 origin 指向错误仓库（如 ComfyUI 主仓库），自动修复为可用 git pull
            # 返回 (ok: bool, message: str, already_synced: bool)
            #   already_synced=True 表示已 fetch+reset 对齐远程，无需再 pull（无 .git 初始化场景）
            subprocess.run(
                ["git", "config", "--global", "--add", "safe.directory", _HERE],
                capture_output=True,
            )
            git_dir = os.path.join(_HERE, ".git")
            if not os.path.exists(git_dir):
                # 下载解压安装：初始化 git 仓库 + 添加 remote + 对齐到 Gitee master
                init = _run_git(["init"])
                if init.returncode != 0:
                    return False, f"git init 失败: {(init.stderr or '').strip()}", False
                _run_git(["symbolic-ref", "HEAD", "refs/heads/master"])
                _run_git(["remote", "remove", "origin"], timeout=30)
                add = _run_git(["remote", "add", "origin", _QIBO_GITEE_URL])
                if add.returncode != 0:
                    return False, f"git remote add 失败: {(add.stderr or '').strip()}", False
                fetch = _run_git(["fetch", "origin", "master"], timeout=180)
                if fetch.returncode != 0:
                    # Gitee fetch 失败试 GitHub
                    _run_git(["remote", "remove", "origin"], timeout=30)
                    _run_git(["remote", "add", "origin", _QIBO_GITHUB_URL])
                    fetch = _run_git(["fetch", "origin", "master"], timeout=180)
                    if fetch.returncode != 0:
                        return False, f"git fetch 失败: {(fetch.stderr or '').strip()}", False
                _run_git(["reset", "--hard", "FETCH_HEAD"])
                _run_git(["clean", "-fd"])
                return True, "检测到下载解压安装（无 .git），已自动初始化 git 仓库并同步到远程 master", True
            # .git 存在：检查 origin 是否指向 ComfyUI-qibo 仓库
            remote_proc = _run_git(["remote", "get-url", "origin"])
            origin_url = (remote_proc.stdout or "").strip()
            if remote_proc.returncode != 0 or "ComfyUI-qibo" not in origin_url:
                _run_git(["remote", "remove", "origin"], timeout=30)
                _run_git(["remote", "add", "origin", _QIBO_GITEE_URL])
                return True, f"已修复 origin remote（原: {origin_url or '无/不存在'} → Gitee ComfyUI-qibo）", False
            return True, "", False
        def _git_pull():
            # 前置自愈：检查 .git 目录与 origin 配置，下载解压安装或 origin 指错时自动修复
            ok, heal_msg, already_synced = _ensure_git_repo()
            if not ok:
                class _FailProc:
                    returncode = 1
                    stdout = ""
                    stderr = heal_msg
                return _FailProc()
            if already_synced:
                # 无 .git 场景已 fetch+reset 对齐远程，无需再 pull
                class _HealedProc:
                    returncode = 0
                    stdout = f"[{heal_msg}]\nAlready up to date."
                    stderr = ""
                return _HealedProc()
            # detached HEAD 时先切回 master，否则 pull 无分支可合并
            cur = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=_HERE, capture_output=True, text=True,
            )
            if (cur.stdout or "").strip() == "HEAD":
                subprocess.run(
                    ["git", "checkout", "master"],
                    cwd=_HERE, capture_output=True, text=True,
                )
            # 主源 Gitee，明确 origin master 不依赖 upstream tracking；失败切备源 GitHub
            proc = subprocess.run(
                ["git", "pull", "origin", "master"],
                cwd=_HERE, capture_output=True, text=True, timeout=120,
            )
            if proc.returncode == 0:
                if heal_msg:
                    proc.stdout = f"[{heal_msg}]\n" + (proc.stdout or "")
                return proc
            gh_proc = subprocess.run(
                ["git", "pull", "https://github.com/QIBO2026/ComfyUI-qibo.git", "master"],
                cwd=_HERE, capture_output=True, text=True, timeout=120,
            )
            if gh_proc.returncode == 0:
                proc.stdout = f"[{'; '.join(filter(None, [heal_msg, 'Gitee 拉取失败，已从 GitHub 备源更新成功']))}]\n原 Gitee 错误: {(proc.stderr or '').strip()}\n" + (gh_proc.stdout or "")
                proc.stderr = gh_proc.stderr
                proc.returncode = 0
                return proc
            # 双源 pull 均失败：先清理合并冲突状态，再尝试强制对齐（等同重新 clone）
            err_msg = (proc.stderr or "") + "\n[GitHub 备源也失败]: " + (gh_proc.stderr or "")
            sync_proc, sync_stage = _force_sync("origin", "https://gitee.com/qq719703856/ComfyUI-qibo.git")
            if sync_stage == "ok" and sync_proc.returncode == 0:
                sync_proc.stdout = f"[双源 pull 均失败，已强制对齐 Gitee origin/master]\n{err_msg}\n" + (sync_proc.stdout or "")
                sync_proc.stderr = ""
                sync_proc.returncode = 0
                return sync_proc
            # Gitee fetch 失败，尝试 GitHub 强制对齐
            gh_sync_proc, gh_sync_stage = _force_sync("github", "https://github.com/QIBO2026/ComfyUI-qibo.git")
            if gh_sync_stage == "ok" and gh_sync_proc.returncode == 0:
                gh_sync_proc.stdout = f"[双源 pull 均失败，已强制对齐 GitHub master]\n{err_msg}\n" + (gh_sync_proc.stdout or "")
                gh_sync_proc.stderr = ""
                gh_sync_proc.returncode = 0
                return gh_sync_proc
            # 强制对齐也失败：最后兜底用 git clone 重新克隆覆盖
            clone_proc = _clone_fallback("https://gitee.com/qq719703856/ComfyUI-qibo.git")
            if clone_proc.returncode == 0:
                clone_proc.stdout = f"[双源 pull + 强制对齐均失败，已通过 git clone 重新同步]\n{err_msg}\n" + (clone_proc.stdout or "")
                clone_proc.stderr = ""
                clone_proc.returncode = 0
                return clone_proc
            clone_proc.stderr = err_msg + "\n[git clone 兜底也失败]: " + (clone_proc.stderr or "")
            return clone_proc
        try:
            proc = await asyncio.get_running_loop().run_in_executor(None, _git_pull)
            return web.json_response({
                "returncode": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            })
        except subprocess.TimeoutExpired:
            return web.json_response({"error": "git pull 超时 (>120s)"})
        except Exception as e:
            return web.json_response({"error": str(e)})
    @routes.post("/qibo/save_model_manifest")
    async def qibo_save_model_manifest(request):
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        try:
            manifest_path = os.path.join(_HERE, "qibo_model_manifest.json")
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            return web.json_response({"status": "ok", "path": manifest_path, "count": len(payload.get("models", []))})
        except Exception as e:
            return web.json_response({"error": str(e)})

    @routes.get("/qibo/load_model_manifest")
    async def qibo_load_model_manifest(request):
        try:
            manifest_path = os.path.join(_HERE, "qibo_model_manifest.json")
            if not os.path.exists(manifest_path):
                return web.json_response({"models": []})
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return web.json_response(data)
        except Exception as e:
            return web.json_response({"error": str(e), "models": []})
    @routes.post("/qibo/print_manifest")
    async def qibo_print_manifest(request):
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        print("\n[QIBO] 模型下载清单 JSON:")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        sys.stdout.flush()
        return web.json_response({"status": "ok", "count": len(payload.get("models") or [])})