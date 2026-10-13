"""QIBO 显存清理节点：综合 ComfyUI 生态各方案优点，委托核心 API 保证后端兼容。

方案对比结论：
- 委托 comfy.model_management.soft_empty_cache 而非硬编码 torch.cuda（兼容 MPS/XPU/NPU/MLU/CUDA）
- 多开关粒度（gc_collect/unload_models/empty_cache/aggressive）参考 kjnodes VRAM_Debug
- 异常保护参考 MiniMaxH3 cleanup_segment_vram
- before/after 诊断输出参考 kjnodes VRAM_Debug
- cleanup_models_gc 检测死模型参考 MiniMaxH3
- 透传 anything 可插入任意链路参考 layerstyle PurgeVRAM
- aggressive 多轮清理参考 comfyui-easy-use cleanGPUUsedForce 的彻底清理思路

清理顺序：before → gc.collect → cleanup_models_gc → unload_all_models → soft_empty_cache → (aggressive 多轮) → after
"""


import gc
import logging

logger = logging.getLogger("ComfyUI-QIBO")


def _format_bytes(n):
    if n is None:
        return "N/A"
    n = float(n)
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.2f} GB"
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.2f} MB"
    if n >= 1024:
        return f"{n / 1024:.2f} KB"
    return f"{n:.0f} B"


def _get_free_vram():
    try:
        import comfy.model_management as mm
        return mm.get_free_memory()
    except Exception:
        return None


def _get_total_vram():
    try:
        import comfy.model_management as mm
        return mm.get_total_memory()
    except Exception:
        return None


def _safe_call(label, fn):
    try:
        fn()
        return True
    except Exception as e:
        logger.warning("QIBOFreeVRAM: %s failed: %s", label, e)
        return False


class QIBOFreeVRAMNode:
    """清理显存节点：可选 gc.collect / 卸载所有模型 / 清各后端缓存 / 激进多轮清理。

    委托 comfy.model_management 核心 API，自动兼容 CUDA/MPS/XPU/NPU/MLU 多后端。
    全程异常保护，清理失败仅 warning 不中断工作流。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "gc_collect": ("BOOLEAN", {"default": True,
                                           "tooltip": "调用 gc.collect() 回收 Python 循环引用"}),
                "unload_models": ("BOOLEAN", {"default": False,
                                              "tooltip": "卸载所有已加载模型（下次需重载）"}),
                "empty_cache": ("BOOLEAN", {"default": True,
                                            "tooltip": "调用 soft_empty_cache 清各后端缓存（CUDA/MPS/XPU/NPU/MLU）"}),
                "aggressive": ("BOOLEAN", {"default": False,
                                           "tooltip": "激进模式：多轮 gc+soft_empty_cache 确保彻底清理"}),
            },
            "optional": {
                "anything": ("*", {"tooltip": "可选透传任意输入，便于插入链路"}),
            },
        }

    RETURN_TYPES = ("*",)
    RETURN_NAMES = ("anything",)
    OUTPUT_NODE = True
    FUNCTION = "free_vram"
    CATEGORY = "QIBO_API"

    def free_vram(self, gc_collect, unload_models, empty_cache, aggressive, anything=None):
        before = _get_free_vram()
        total = _get_total_vram()
        actions = []

        def do_gc():
            gc.collect()

        def do_cleanup_models_gc():
            import comfy.model_management as mm
            if hasattr(mm, "cleanup_models_gc"):
                mm.cleanup_models_gc()

        def do_unload_all():
            import comfy.model_management as mm
            mm.unload_all_models()

        def do_soft_empty():
            import comfy.model_management as mm
            mm.soft_empty_cache()

        if gc_collect and _safe_call("gc.collect", do_gc):
            actions.append("gc.collect")
        _safe_call("cleanup_models_gc", do_cleanup_models_gc)
        actions.append("cleanup_models_gc*")
        if unload_models and _safe_call("unload_all_models", do_unload_all):
            actions.append("unload_all_models")
        if empty_cache and _safe_call("soft_empty_cache", do_soft_empty):
            actions.append("soft_empty_cache")

        if aggressive:
            for i in range(2):
                _safe_call(f"aggressive gc#{i+1}", do_gc)
                _safe_call(f"aggressive soft_empty#{i+1}", do_soft_empty)
            actions.append("aggressive(2轮)")

        after = _get_free_vram()
        freed = (after - before) if (before is not None and after is not None) else None

        logger.info(
            "QIBOFreeVRAM: actions=[%s] free before=%s after=%s freed=%s total=%s",
            ", ".join(actions) or "none",
            _format_bytes(before),
            _format_bytes(after),
            _format_bytes(freed),
            _format_bytes(total),
        )

        ui_text = [
            f"清理动作: {', '.join(actions) if actions else '无'}",
            f"清理前可用: {_format_bytes(before)}",
            f"清理后可用: {_format_bytes(after)}",
            f"释放量: {_format_bytes(freed)}",
            f"总显存: {_format_bytes(total)}",
        ]

        return {"ui": {"text": ui_text}, "result": (anything,)}


NODE_CLASS_MAPPINGS = {
    "QIBOFreeVRAMNode": QIBOFreeVRAMNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBOFreeVRAMNode": "QIBO 清理显存",
}
