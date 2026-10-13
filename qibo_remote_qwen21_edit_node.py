import os
import io
import json
import time
import copy
import random
import requests
import numpy as np
import torch
from PIL import Image

from .qibo_auth import get_remote_comfyui_config

try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

_SAMPLERS = ["euler", "euler_ancestral", "dpmpp_2m", "dpmpp_2m_sde", "dpmpp_fast", "ddim", "uni_pc"]
_SCHEDULERS = ["simple", "normal", "karras", "exponential", "sgm_uniform"]


class QIBORemoteQwen21EditNode:
    """调用远程 ComfyUI 的本地 Qwen-Image-2.1 模型做图片编辑。

    支持两种入图方式（每个端口二选一）：
    1. 连线本地 IMAGE tensor → 节点自动上传到远程 ComfyUI 的 input 目录（/upload/image）；
    2. 填远程 input 目录已有图片文件名（imageN_name）→ 直接引用，不上传。
    内部流程：上传(若传 tensor) → 改写 image_qwen_image_2_1_api.json 工作流 → POST /prompt → 轮询 /history → 下载结果 → 转 IMAGE tensor 返回。
    """

    @classmethod
    def INPUT_TYPES(cls):
        optional = {}
        for i in range(1, 11):
            optional[f"image{i}"] = ("IMAGE", {"tooltip": f"本地图片 {i}，自动上传到远程 ComfyUI input 目录（image_{i}）"})
        for i in range(1, 11):
            optional[f"image{i}_name"] = ("STRING", {"default": "", "tooltip": f"远程 input 目录已有图片文件名（image_{i}）；当 image{i} 端口未连线时使用"})
        optional.update({
            "negative_prompt": ("STRING", {"multiline": True, "default": ""}),
            "seed": ("INT", {"default": -1, "min": -1, "max": 9007199254740991}),
            "steps": ("INT", {"default": 25, "min": 1, "max": 100}),
            "cfg": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 20.0, "step": 0.1}),
            "sampler_name": (_SAMPLERS, {"default": "euler"}),
            "scheduler": (_SCHEDULERS, {"default": "simple"}),
            "aspect_ratio": ("STRING", {"default": "1:1 (Square)"}),
            "megapixels": ("FLOAT", {"default": 1.0, "min": 0.25, "max": 16.0, "step": 0.25}),
            "denoise": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.05}),
            "remote_url": ("STRING", {"default": "", "placeholder": "留空使用 qibo_config.json 里 remote_comfyui.base_url"}),
            "filename_prefix": ("STRING", {"default": "Qwen21_remote_edit"}),
        })
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": "把 <image2> 的动物放到 <image1> 里面，跟随着任务跑"}),
            },
            "optional": optional,
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "edit_image"
    CATEGORY = "QIBO_API"
    OUTPUT_NODE = True
    DESCRIPTION = "调用远程 ComfyUI 的 Qwen-Image-2.1 本地模型做图片编辑；支持本地 IMAGE tensor 上传或远程文件名，最多 10 张图"

    def _upload_tensor(self, tensor, base_url, verify, idx):
        img = tensor
        if hasattr(img, "shape") and len(img.shape) == 4:
            img = img[0]
        arr = (img.cpu().numpy() * 255.0).clip(0, 255).astype("uint8")
        pil = Image.fromarray(arr)
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        buf.seek(0)
        fname = f"qibo_upload_{idx}_{random.randint(0, 999999)}.png"
        r = requests.post(
            f"{base_url}/upload/image",
            files={"image": (fname, buf, "image/png")},
            verify=verify, timeout=120,
        )
        if r.status_code != 200:
            diag = ""
            try:
                sr = requests.get(f"{base_url}/system_stats", verify=verify, timeout=8)
                diag = f"（/system_stats 返回 {sr.status_code}）"
            except Exception as e:
                diag = f"（/system_stats 不可达: {type(e).__name__}）"
            if r.status_code == 404:
                raise Exception(f"上传图片 {idx} 失败 404：远程 ComfyUI 实例可能已下线或 /upload/image 端点未开放{diag}。请确认实例在线且地址正确：{base_url}")
            if r.status_code == 413:
                raise Exception(f"上传图片 {idx} 失败 413：图片过大({pil.size[0]}x{pil.size[1]})，请缩小尺寸后重试")
            raise Exception(f"上传图片 {idx} 失败: {r.status_code} {r.text[:200]} {diag}")
        remote_name = r.json().get("name", fname)
        print(f"📤 图片 {idx} 已上传远程: {remote_name} ({pil.size[0]}x{pil.size[1]})")
        return remote_name

    def edit_image(self, prompt, **kwargs):
        negative_prompt = kwargs.get("negative_prompt", "")
        seed = kwargs.get("seed", -1)
        steps = kwargs.get("steps", 25)
        cfg = kwargs.get("cfg", 1.0)
        sampler_name = kwargs.get("sampler_name", "euler")
        scheduler = kwargs.get("scheduler", "simple")
        aspect_ratio = kwargs.get("aspect_ratio", "1:1 (Square)")
        megapixels = kwargs.get("megapixels", 1.0)
        denoise = kwargs.get("denoise", 1.0)
        remote_url = kwargs.get("remote_url", "")
        filename_prefix = kwargs.get("filename_prefix", "Qwen21_remote_edit")

        rc = get_remote_comfyui_config()
        base_url = (remote_url.strip() or rc.get("base_url", "")).rstrip("/")
        if not base_url:
            raise Exception("未配置远程 ComfyUI 地址：请在 qibo_config.json 的 remote_comfyui.base_url 设置，或在节点 remote_url 参数填写")
        verify = rc.get("verify_ssl", False)

        try:
            sr = requests.get(f"{base_url}/system_stats", verify=verify, timeout=10)
            if sr.status_code != 200:
                raise Exception(f"远程 ComfyUI 不可达（/system_stats 返回 {sr.status_code}），请确认实例在线：{base_url}")
        except requests.exceptions.RequestException as e:
            raise Exception(f"无法连接远程 ComfyUI：{type(e).__name__}: {e}。请确认实例在线且地址正确：{base_url}")

        remote_names = []
        for i in range(1, 11):
            tensor = kwargs.get(f"image{i}", None)
            name = kwargs.get(f"image{i}_name", "")
            if tensor is not None:
                remote_names.append(self._upload_tensor(tensor, base_url, verify, i))
            elif name and str(name).strip():
                remote_names.append(str(name).strip())
            else:
                break
        if not remote_names:
            raise Exception("请至少提供一张图片：连线 image1 端口上传本地图，或填 image1_name 引用远程已有图")
        print(f"🖼️ 共 {len(remote_names)} 张图：{remote_names}")

        wf_path = os.path.join(os.path.dirname(__file__), rc.get("workflow_file", "image_qwen_image_2_1_api.json"))
        with open(wf_path, encoding="utf-8") as f:
            wf = copy.deepcopy(json.load(f))

        load_image_nodes = []
        te_node_id = None
        for nid, node in wf.items():
            ct = node.get("class_type")
            if ct == "LoadImage":
                load_image_nodes.append(nid)
            elif ct == "TextEncodeQwenImage21":
                te_node_id = nid
                node["inputs"]["prompt"] = prompt
                if "negative_prompt" in node["inputs"]:
                    node["inputs"]["negative_prompt"] = negative_prompt
            elif ct == "KSampler":
                node["inputs"]["seed"] = seed if seed != -1 else random.randint(0, 9007199254740991)
                node["inputs"]["steps"] = steps
                node["inputs"]["cfg"] = cfg
                node["inputs"]["sampler_name"] = sampler_name
                node["inputs"]["scheduler"] = scheduler
                if "denoise" in node["inputs"]:
                    node["inputs"]["denoise"] = denoise
            elif ct == "ResolutionSelector":
                if "aspect_ratio" in node["inputs"]:
                    node["inputs"]["aspect_ratio"] = aspect_ratio
                if "megapixels" in node["inputs"]:
                    node["inputs"]["megapixels"] = megapixels
            elif ct == "SaveImageAdvanced":
                node["inputs"]["filename_prefix"] = filename_prefix

        max_ports = max(len(remote_names), 10)
        for port in range(1, max_ports + 1):
            key = f"images.image_{port}"
            if port <= len(remote_names):
                fname = remote_names[port - 1]
                if port - 1 < len(load_image_nodes):
                    lid = load_image_nodes[port - 1]
                else:
                    lid = f"qibo_extra_img_{port}"
                    wf[lid] = {"inputs": {"image": fname}, "class_type": "LoadImage", "_meta": {"title": f"加载图像 {port}"}}
                wf[lid]["inputs"]["image"] = fname
                if te_node_id:
                    wf[te_node_id]["inputs"][key] = [lid, 0]
            else:
                if te_node_id and key in wf[te_node_id]["inputs"]:
                    del wf[te_node_id]["inputs"][key]

        print(f"📡 提交工作流到远程 ComfyUI: {base_url}")
        resp = requests.post(f"{base_url}/prompt", json={"prompt": wf, "client_id": "qibo-remote-edit"}, verify=verify, timeout=30)
        if resp.status_code != 200:
            raise Exception(f"远程提交失败: {resp.status_code} {resp.text[:500]}")
        pid = resp.json().get("prompt_id")
        if not pid:
            raise Exception(f"远程未返回 prompt_id: {resp.text[:300]}")
        print(f"📌 prompt_id={pid}")

        poll_interval = rc.get("poll_interval", 3)
        max_wait = rc.get("max_wait_seconds", 600)
        start = time.time()
        while time.time() - start < max_wait:
            time.sleep(poll_interval)
            try:
                r = requests.get(f"{base_url}/history/{pid}", verify=verify, timeout=15)
            except Exception:
                continue
            if r.status_code != 200:
                continue
            hist = r.json()
            if pid not in hist:
                print(f"⌛ 远程编辑中... {int(time.time() - start)}s")
                continue
            h = hist[pid]
            status = h.get("status", {})
            outputs = h.get("outputs", {})
            ss = status.get("status_str")
            if ss == "error":
                raise Exception(f"远程执行出错: {json.dumps(status, ensure_ascii=False)[:500]}")
            if ss == "success" or outputs:
                for _nid, out in outputs.items():
                    for img in out.get("images", []):
                        q = {"filename": img["filename"], "subfolder": img.get("subfolder", ""), "type": img.get("type", "output")}
                        ir = requests.get(f"{base_url}/view", params=q, verify=verify, timeout=60)
                        if ir.status_code == 200:
                            pil = Image.open(io.BytesIO(ir.content)).convert("RGB")
                            arr = np.array(pil).astype(np.float32) / 255.0
                            tensor = torch.from_numpy(arr)[None,]
                            print(f"✅ 远程编辑完成，耗时 {int(time.time() - start)}s，尺寸 {pil.size}")
                            return (tensor,)
                raise Exception("远程完成但未找到图片输出")
        raise Exception(f"远程执行超时 ({max_wait}s)")


NODE_CLASS_MAPPINGS = {
    "QIBORemoteQwen21Edit": QIBORemoteQwen21EditNode,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBORemoteQwen21Edit": "QIBO 远程 Qwen2.1 图片编辑",
}
