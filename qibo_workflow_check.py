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
        for k, v in inputs.items():
            if not isinstance(v, str) or not v:
                continue
            folder = _resolve_folder(class_type, k)
            if not folder:
                continue
            required_models.append({
                "node_id": str(node_id),
                "class_type": class_type,
                "field": k,
                "value": v,
                "folder": folder,
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
        if available is None:
            ref["status"] = "folder_unknown"
        elif ref["value"] in available:
            ref["status"] = "present"
        else:
            ref["status"] = "missing"

    missing_node_types = sorted({n["class_type"] for n in required_nodes if not n["registered"]})
    missing_models = [m for m in required_models if m["status"] != "present"]

    return {
        "required_nodes": required_nodes,
        "required_models": required_models,
        "missing_node_types": missing_node_types,
        "missing_models": missing_models,
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
        def _git_pull():
            return subprocess.run(
                ["git", "pull"],
                cwd=_HERE,
                capture_output=True,
                text=True,
                timeout=120,
            )
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