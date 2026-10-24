"""QIBO H3 潜空间放大节点。

复刻 comfyui-SelfLift/h3_upscaler.py 的 LatentResizer3D 架构（LBH-123-AI/Minimax_h3_latent_Upscaler），
做纯潜空间放大（不经过像素空间）：输入 H3 视频 latent [B,24,T,h,w] → 3D conv 网络 → [B,24,T,H,W]。
模型放 ComfyUI/models/latent_upscale_models/。
"""

import logging
import os
import re

import torch
import torch.nn as nn
import torch.nn.functional as F

import comfy.model_management
import comfy.model_patcher
import folder_paths

try:
    from comfy.ldm.minimax.vae import LATENTS_MEAN, LATENTS_STD
except ImportError:
    LATENTS_MEAN = [0.0] * 24
    LATENTS_STD = [1.0] * 24

_FOLDER = "latent_upscale_models"

if _FOLDER not in folder_paths.folder_names_and_paths:
    folder_paths.add_model_folder_path(_FOLDER, os.path.join(folder_paths.models_dir, _FOLDER))


def _normalization(channels):
    return nn.GroupNorm(32, channels)


def _zero_module(module):
    for p in module.parameters():
        p.detach().zero_()
    return module


def _temporal_windows(length, chunk, overlap):
    for start in range(0, length, chunk):
        end = min(length, start + chunk)
        yield start, end, max(0, start - overlap), min(length, end + overlap)


class AttnBlock3D(nn.Module):
    def __init__(self, in_channels):
        super().__init__()
        self.norm = _normalization(in_channels)
        self.q = nn.Conv3d(in_channels, in_channels, 1)
        self.k = nn.Conv3d(in_channels, in_channels, 1)
        self.v = nn.Conv3d(in_channels, in_channels, 1)
        self.proj_out = nn.Conv3d(in_channels, in_channels, 1)

    def forward(self, x):
        h = self.norm(x)
        q = self.q(h).flatten(2).movedim(-1, 1).unsqueeze(1)
        k = self.k(h).flatten(2).movedim(-1, 1).unsqueeze(1)
        v = self.v(h).flatten(2).movedim(-1, 1).unsqueeze(1)
        h = F.scaled_dot_product_attention(q, k, v)
        h = h.squeeze(1).movedim(1, -1).reshape(x.shape)
        return x + self.proj_out(h)


class ResBlockEmb3D(nn.Module):
    def __init__(self, channels, emb_channels, dropout=0, out_channels=None):
        super().__init__()
        self.out_channels = out_channels or channels
        self.in_layers = nn.Sequential(
            _normalization(channels), nn.SiLU(),
            nn.Conv3d(channels, self.out_channels, 3, padding=1),
        )
        self.emb_layers = nn.Sequential(
            nn.SiLU(), nn.Linear(emb_channels, 2 * self.out_channels),
        )
        self.out_norm = _normalization(self.out_channels)
        self.out_layers = nn.Sequential(
            nn.SiLU(), nn.Dropout(p=dropout),
            _zero_module(nn.Conv3d(self.out_channels, self.out_channels, 3, padding=1)),
        )
        self.skip = (
            nn.Conv3d(channels, self.out_channels, 1)
            if self.out_channels != channels else nn.Identity()
        )

    def forward(self, x, emb):
        h = self.in_layers(x)
        emb_out = self.emb_layers(emb).type(h.dtype)
        while len(emb_out.shape) < len(h.shape):
            emb_out = emb_out[..., None]
        scale, shift = torch.chunk(emb_out, 2, dim=1)
        h = self.out_norm(h) * (1 + scale) + shift
        h = self.out_layers(h)
        return self.skip(x) + h


class TemporalConv(nn.Module):
    def __init__(self, channels, kernel_size=5):
        super().__init__()
        padding = kernel_size // 2
        self.norm = _normalization(channels)
        self.dwconv = nn.Conv3d(channels, channels,
                                kernel_size=(kernel_size, 1, 1),
                                padding=(padding, 0, 0),
                                groups=channels)
        self.pwconv = nn.Conv3d(channels, channels, kernel_size=1)
        nn.init.zeros_(self.pwconv.weight)
        nn.init.zeros_(self.pwconv.bias)

    def forward(self, x):
        identity = x
        h = self.norm(x)
        h = F.silu(h)
        h = self.dwconv(h)
        h = self.pwconv(h)
        return identity + h


class LatentResizer3D(nn.Module):
    def __init__(self, in_channels=24, in_blocks=12, out_blocks=12,
                 channels=512, dropout=0.1, attn=False,
                 temporal_every=2, temporal_kernel=5):
        super().__init__()
        self.conv_in = nn.Conv3d(in_channels, channels, 3, padding=1)
        embed_dim = 64
        self.embed = nn.Sequential(
            nn.Linear(1, embed_dim), nn.SiLU(), nn.Linear(embed_dim, embed_dim))

        self.in_blocks = nn.ModuleList()
        for b in range(in_blocks):
            if (b == 1 or b == in_blocks - 1) and attn:
                self.in_blocks.append(AttnBlock3D(channels))
            self.in_blocks.append(ResBlockEmb3D(channels, embed_dim, dropout))
            if temporal_every > 0 and b % temporal_every == 0:
                self.in_blocks.append(TemporalConv(channels, temporal_kernel))

        self.out_blocks = nn.ModuleList()
        for b in range(out_blocks):
            if (b == 1 or b == out_blocks - 1) and attn:
                self.out_blocks.append(AttnBlock3D(channels))
            self.out_blocks.append(ResBlockEmb3D(channels, embed_dim, dropout))
            if temporal_every > 0 and b % temporal_every == 0:
                self.out_blocks.append(TemporalConv(channels, temporal_kernel))

        self.norm_out = _normalization(channels)
        self.conv_out = nn.Conv3d(channels, in_channels, 3, padding=1)

    def temporal_chunk_settings(self):
        for block in self.in_blocks:
            if isinstance(block, TemporalConv):
                return 32, block.dwconv.weight.shape[2]
        return 32, 0

    def temporal_window_budget(self, length):
        chunk, overlap = self.temporal_chunk_settings()
        return length if length <= chunk else min(length + 2 * overlap, chunk + 4 * overlap)

    def forward(self, x, scale=None, target_size=None, enable_chunking=True):
        if target_size is not None:
            size = target_size
        elif scale is not None:
            size = tuple(int(round(s * scale)) for s in x.shape[-3:])
        else:
            return x
        if size == x.shape[-3:]:
            return x

        B, C, T, H, W = x.shape
        chunk, overlap = self.temporal_chunk_settings()

        if not enable_chunking or T <= chunk:
            return self._forward_seg(x, scale, size)

        x_padded = F.pad(x, (0, 0, 0, 0, overlap, overlap), mode='replicate')
        out_full = torch.zeros(B, C, T, size[-2], size[-1], device=x.device, dtype=x.dtype)
        weight_full = torch.zeros(1, 1, T, 1, 1, device=x.device, dtype=x.dtype)

        for seg_start, seg_end, out_start, out_end in _temporal_windows(T, chunk, overlap):
            lo = out_start
            hi = out_end + 2 * overlap
            seg = x_padded[:, :, lo:hi].contiguous()
            seg_size = (hi - lo, size[-2], size[-1])
            seg_out = self._forward_seg(seg, scale, seg_size)
            s0 = (out_start + overlap) - lo
            s1 = s0 + (out_end - out_start)
            valid_out = seg_out[:, :, s0:s1]
            n_valid = out_end - out_start

            weight = torch.ones(n_valid, device=x.device, dtype=x.dtype)
            if seg_start > out_start:
                blend_len = seg_start - out_start
                weight[:blend_len] = torch.arange(1, blend_len + 1, device=x.device, dtype=x.dtype) / (blend_len + 1)
            if out_end > seg_end:
                blend_len = out_end - seg_end
                weight[-blend_len:] = torch.arange(blend_len, 0, -1, device=x.device, dtype=x.dtype) / (blend_len + 1)

            out_full[:, :, out_start:out_end] += valid_out * weight.view(1, 1, n_valid, 1, 1)
            weight_full[:, :, out_start:out_end] += weight.view(1, 1, n_valid, 1, 1)
            del seg, seg_out, valid_out

        return out_full / weight_full.clamp(min=1e-8)

    def _forward_seg(self, x, scale, size):
        scale_emb = torch.tensor(
            [scale - 1 if scale is not None else 0.0],
            dtype=x.dtype, device=x.device).unsqueeze(0)
        emb = self.embed(scale_emb)

        x = self.conv_in(x)
        for b in self.in_blocks:
            if isinstance(b, ResBlockEmb3D):
                x = b(x, emb.expand(x.shape[0], -1))
            else:
                x = b(x)

        x = F.interpolate(x, size=size, mode="trilinear", align_corners=False)

        for b in self.out_blocks:
            if isinstance(b, ResBlockEmb3D):
                x = b(x, emb.expand(x.shape[0], -1))
            else:
                x = b(x)

        x = self.norm_out(x)
        x = F.silu(x)
        return self.conv_out(x)


_model_cache = {}


def list_upscaler_models():
    try:
        paths = folder_paths.get_folder_paths(_FOLDER)
    except KeyError:
        return []
    names = []
    for p in paths:
        for root, _, files in os.walk(p):
            for f in files:
                if os.path.splitext(f)[1].lower() in (".pth", ".safetensors"):
                    names.append(os.path.relpath(os.path.join(root, f), p))
    return sorted(names)


def _detect_arch(sd):
    cfg = {"in_channels": 24, "in_blocks": 12, "out_blocks": 12, "channels": 512,
           "dropout": 0.1, "attn": False, "temporal_every": 2, "temporal_kernel": 5}
    if 'conv_in.weight' in sd:
        cfg["in_channels"] = sd['conv_in.weight'].shape[1]
        cfg["channels"] = sd['conv_in.weight'].shape[0]
    in_ids, out_ids, tin, tout = set(), set(), set(), set()
    for k in sd:
        m = re.match(r'in_blocks\.(\d+)\.in_layers\.', k)
        if m: in_ids.add(int(m.group(1)))
        m = re.match(r'out_blocks\.(\d+)\.in_layers\.', k)
        if m: out_ids.add(int(m.group(1)))
        m = re.match(r'in_blocks\.(\d+)\.dwconv\.weight', k)
        if m: tin.add(int(m.group(1)))
        m = re.match(r'out_blocks\.(\d+)\.dwconv\.weight', k)
        if m: tout.add(int(m.group(1)))
    if in_ids: cfg["in_blocks"] = len(in_ids)
    if out_ids: cfg["out_blocks"] = len(out_ids)
    if tin or tout:
        cfg["temporal_every"] = 2
        for k in sd:
            if k.endswith('dwconv.weight'):
                cfg["temporal_kernel"] = sd[k].shape[2]
                break
    else:
        cfg["temporal_every"] = 0
    cfg["attn"] = False
    return cfg


def _normalize_checkpoint_dtype(state_dict):
    weight = state_dict.get("conv_in.weight")
    if weight is None:
        raise ValueError("upscaler checkpoint 缺少 conv_in.weight")
    dtype = weight.dtype
    if str(dtype).startswith("torch.float8_"):
        dtype = torch.bfloat16 if any(value.dtype == torch.bfloat16 for value in state_dict.values()) else torch.float16
    if dtype not in (torch.float16, torch.bfloat16, torch.float32, torch.float64):
        raise ValueError(f"不支持的权重 dtype {dtype}")
    return {name: value.to(dtype=dtype) if value.is_floating_point() else value
            for name, value in state_dict.items()}


def _load_model(model_name, device):
    key = (model_name, str(device))
    if key in _model_cache:
        return _model_cache[key]

    path = None
    for p in folder_paths.get_folder_paths(_FOLDER):
        candidate = os.path.join(p, model_name)
        if os.path.isfile(candidate):
            path = candidate
            break
    if path is None:
        raise FileNotFoundError(f"潜空间放大模型未找到: {model_name}（放到 ComfyUI/models/{_FOLDER}/）")

    import comfy.utils
    sd = comfy.utils.load_torch_file(path)
    if isinstance(sd, dict) and 'model' in sd:
        sd = sd['model']
    if any(k.startswith("upscaler.") for k in sd):
        sd = {k[len("upscaler."):]: v for k, v in sd.items() if k.startswith("upscaler.")}
    sd = _normalize_checkpoint_dtype(sd)

    cfg = _detect_arch(sd)
    with torch.device("meta"):
        model = LatentResizer3D(
            in_channels=cfg["in_channels"], in_blocks=cfg["in_blocks"], out_blocks=cfg["out_blocks"],
            channels=cfg["channels"], dropout=cfg["dropout"], attn=cfg["attn"],
            temporal_every=cfg["temporal_every"], temporal_kernel=cfg["temporal_kernel"],
        )
    model.load_state_dict(sd, strict=True, assign=True)
    model = model.eval().requires_grad_(False)
    patcher = comfy.model_patcher.CoreModelPatcher(
        model, load_device=device,
        offload_device=comfy.model_management.unet_offload_device())
    _model_cache[key] = patcher
    return patcher


class QIBOH3LatentUpscaler:
    """H3 潜空间放大：加载 latent_upscale_models 里的 3D conv 放大模型，对 H3 视频 latent 做纯潜空间放大。"""

    CATEGORY = "QIBO"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "latent": ("LATENT",),
                "upscaler_model": (list_upscaler_models(),),
                "scale": ("FLOAT", {"default": 2.0, "min": 1.0, "max": 4.0, "step": 0.25}),
            },
            "optional": {
                "force_unload": ("BOOLEAN", {"default": True}),
            },
        }

    RETURN_TYPES = ("LATENT",)
    FUNCTION = "upscale"

    def upscale(self, latent, upscaler_model, scale, force_unload=True):
        samples = latent["samples"]
        if samples.dim() != 5:
            raise ValueError(f"仅支持 5D 视频 latent [B,C,T,H,W]，收到 shape={tuple(samples.shape)}（图像 latent 请用 2D 放大节点）")

        device = comfy.model_management.get_torch_device()
        B, C, T, h, w = samples.shape
        H = max(int(round(h * scale)), 1)
        W = max(int(round(w * scale)), 1)
        actual_scale = (H / h + W / w) / 2.0
        logging.info("[QIBO H3 upscaler] input=%s target=%s scale=%.4f model=%s", tuple(samples.shape), (T, H, W), actual_scale, upscaler_model)

        patcher = _load_model(upscaler_model, device)
        model = patcher.model
        try:
            comfy.model_management.load_models_gpu([patcher])
            dtype = model.conv_in.weight.dtype
            mean = torch.tensor(LATENTS_MEAN, dtype=dtype, device=device).view(1, -1, 1, 1, 1)
            std = torch.tensor(LATENTS_STD, dtype=dtype, device=device).view(1, -1, 1, 1, 1)

            x = samples.to(device=device, dtype=dtype)
            with torch.no_grad():
                x = (x - mean) / std
                out = model(x, scale=actual_scale, target_size=(T, H, W))
                out = (out * std + mean).float().to(comfy.model_management.intermediate_device())
        finally:
            if force_unload:
                comfy.model_management.unload_model_and_clones(patcher, unload_additional_models=False)
                comfy.model_management.soft_empty_cache()

        out_latent = dict(latent)
        out_latent["samples"] = out
        return (out_latent,)


NODE_CLASS_MAPPINGS = {
    "QIBOH3LatentUpscaler": QIBOH3LatentUpscaler,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBOH3LatentUpscaler": "qibo H3 潜空间放大",
}