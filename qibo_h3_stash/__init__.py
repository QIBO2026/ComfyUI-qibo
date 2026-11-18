"""QIBO H3 Stash — MiniMax H3 latent upscaler + package save/load nodes."""

from .nodes import (
    MiniMaxH3LatentBlur,
    MiniMaxH3LatentContrast,
    MiniMaxH3LatentSharpen,
    MiniMaxH3LatentUpscaleCombined,
)
from .schedulers import MiniMaxH3Pass2StaggeredScheduler
from .stash import MiniMaxH3LQPackageLoad, MiniMaxH3LQPackageSave
from .stash_collect import MiniMaxH3UpscaleCollect
from .stash_server import register_routes
from .vae_decode import MiniMaxH3VAEDecodeFast

NODE_CLASS_MAPPINGS = {
    "MiniMaxH3LatentUpscaleCombined": MiniMaxH3LatentUpscaleCombined,
    "MiniMaxH3LatentBlur": MiniMaxH3LatentBlur,
    "MiniMaxH3LatentSharpen": MiniMaxH3LatentSharpen,
    "MiniMaxH3LatentContrast": MiniMaxH3LatentContrast,
    "MiniMaxH3Pass2StaggeredScheduler": MiniMaxH3Pass2StaggeredScheduler,
    "MiniMaxH3VAEDecodeFast": MiniMaxH3VAEDecodeFast,
    "MiniMaxH3LQPackageSave": MiniMaxH3LQPackageSave,
    "MiniMaxH3LQPackageLoad": MiniMaxH3LQPackageLoad,
    "MiniMaxH3UpscaleCollect": MiniMaxH3UpscaleCollect,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MiniMaxH3LatentUpscaleCombined": "qibo H3 潜空间放大组合 2x",
    "MiniMaxH3LatentBlur": "qibo H3 潜空间模糊",
    "MiniMaxH3LatentSharpen": "qibo H3 潜空间锐化",
    "MiniMaxH3LatentContrast": "qibo H3 潜空间对比度",
    "MiniMaxH3Pass2StaggeredScheduler": "qibo H3 Pass-2 交错调度器",
    "MiniMaxH3VAEDecodeFast": "qibo H3 VAE 解码（快速）",
    "MiniMaxH3LQPackageSave": "qibo H3 保存包",
    "MiniMaxH3LQPackageLoad": "qibo H3 加载包",
    "MiniMaxH3UpscaleCollect": "qibo H3 放大收集",
}

try:
    register_routes()
except Exception as e:
    print(f"⚠️ QIBO H3 Stash 路由注册失败: {e}")

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]