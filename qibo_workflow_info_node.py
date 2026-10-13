import json


MODEL_LOADER_FIELDS = {
    "CheckpointLoaderSimple": ["ckpt_name"],
    "CheckpointLoader": ["ckpt_name"],
    "CheckpointLoaderGGUF": ["ckpt_name"],
    "UNETLoader": ["unet_name"],
    "UNETLoaderGGUF": ["unet_name"],
    "UnetLoaderGGUF": ["unet_name"],
    "LoraLoader": ["lora_name"],
    "LoraLoaderModelOnly": ["lora_name"],
    "LoraLoaderGGUF": ["lora_name"],
    "CLIPLoader": ["clip_name"],
    "CLIPLoaderGGUF": ["clip_name"],
    "DualCLIPLoader": ["clip_name1", "clip_name2"],
    "VAELoader": ["vae_name"],
    "VAELoaderFile": ["vae_name"],
    "ControlNetLoader": ["control_net_name"],
    "ControlNetLoadSimple": ["control_net_name"],
    "ControlNetLoadSimpleAdvanced": ["control_net_name"],
    "ControlNetLoaderAdvanced": ["control_net_name"],
    "DiffControlNetLoader": ["model_name"],
    "UpscaleModelLoader": ["model_name"],
    "UpscaleModelLoaderUrl": ["model_name"],
    "GLIGENLoader": ["gligen_name"],
    "HypernetworkLoader": ["hypernetwork_name"],
    "StyleModelLoader": ["style_model_name"],
    "InstructPixToPixConditioning": [],
    "ModelSamplingDiscrete": [],
    "ModelSamplingContinuousEDM": [],
    "QwenImage21Cache": ["model_name"],
    "QwenImage21CacheFP8": ["model_name"],
    "QwenImage21CacheINT8": ["model_name"],
    "QwenImage21VAELoader": ["vae_name"],
    "Qwen2VLLoader": ["model_name"],
    "Qwen2VLGGUFLoader": ["model_name"],
    "MiniMaxH3Loader": ["model_name"],
    "LTXVLoader": ["model_name"],
    "LTXVModelLoader": ["model_name"],
}

_LOADER_HINTS = ("Loader", "Load", "Cache", "LoaderGGUF", "ModelLoader")


def _is_link_value(v):
    return isinstance(v, (list, tuple)) and len(v) == 2 and isinstance(v[0], str)


def _extract_model_entries(prompt):
    entries = []
    if not isinstance(prompt, dict):
        return entries
    for node_id, node in prompt.items():
        if not isinstance(node, dict):
            continue
        class_type = node.get("class_type", "")
        inputs = node.get("inputs", {}) or {}
        fields = MODEL_LOADER_FIELDS.get(class_type)
        if fields is None:
            looks_like_loader = any(h in class_type for h in _LOADER_HINTS)
            if not looks_like_loader:
                continue
            fields = []
            for k, v in inputs.items():
                if isinstance(v, str) and not _is_link_value(v):
                    kl = k.lower()
                    if kl.endswith("_name") or kl.endswith("_file") or kl.endswith("model_name") or kl.endswith("ckpt") or kl.endswith("unet") or kl.endswith("lora") or kl.endswith("vae") or kl.endswith("clip") or "control_net" in kl or "upscaler" in kl:
                        fields.append(k)
        for f in fields:
            v = inputs.get(f)
            if isinstance(v, str) and v:
                entries.append({"node_id": str(node_id), "class_type": class_type, "field": f, "value": v})
    return entries


def _build_models_text(entries, unique_id):
    lines = []
    lines.append("=== 工作流模型加载清单 ===")
    if not entries:
        lines.append("(未识别到模型加载节点)")
    for e in entries:
        lines.append(f"[节点 {e['node_id']}] {e['class_type']}")
        lines.append(f"    {e['field']} = {e['value']}")
    lines.append(f"共识别 {len(entries)} 个模型加载节点")
    if unique_id is not None:
        lines.append(f"(本信息节点 id = {unique_id})")
    return "\n".join(lines)


class QIBOWorkflowInfoNode:
    """工作流信息提取节点。

    拖入任意工作流即可获取该工作流要加载的模型名称和全部节点内容。
    通过 ComfyUI 的 PROMPT / EXTRA_PNGINFO / UNIQUE_ID 隐藏输入拿到当前执行的完整工作流字典，
    不产生普通连线依赖，不会引入循环。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {},
            "optional": {},
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
                "unique_id": "UNIQUE_ID",
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("models_text", "workflow_json")
    FUNCTION = "get_workflow_info"
    CATEGORY = "QIBO_API"
    OUTPUT_NODE = True

    def get_workflow_info(self, prompt=None, extra_pnginfo=None, unique_id=None):
        prompt = prompt or {}
        try:
            entries = _extract_model_entries(prompt)
        except Exception as e:
            entries = []
            _err = str(e)
        else:
            _err = None

        models_text = _build_models_text(entries, unique_id)
        if _err:
            models_text += f"\n(模型提取异常: {_err})"

        try:
            workflow_json = json.dumps(prompt, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            workflow_json = f"(序列化工作流失败: {e})"

        display = models_text + "\n\n" + "=== 完整工作流节点内容 (prompt) ===\n" + workflow_json
        if extra_pnginfo:
            try:
                display += "\n\n=== extra_pnginfo ===\n" + json.dumps(extra_pnginfo, ensure_ascii=False, indent=2, default=str)
            except Exception:
                pass

        return {
            "ui": {"text": [display]},
            "result": (models_text, workflow_json),
        }


NODE_CLASS_MAPPINGS = {
    "QIBOWorkflowInfoNode": QIBOWorkflowInfoNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBOWorkflowInfoNode": "QIBO 模型节点下载",
}