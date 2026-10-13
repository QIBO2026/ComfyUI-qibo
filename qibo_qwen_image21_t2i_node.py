import math
import torch
import comfy.model_management
import node_helpers


class QIBOQwenImage21T2INode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "clip": ("CLIP",),
                "prompt": ("STRING", {"multiline": True, "dynamicPrompts": True}),
                "negative_prompt": ("STRING", {"multiline": True, "dynamicPrompts": True, "default": ""}),
                "width": ("INT", {"default": 1024, "min": 64, "max": 4096, "step": 32,
                                   "tooltip": "生成图宽度（32 倍数）"}),
                "height": ("INT", {"default": 1024, "min": 64, "max": 4096, "step": 32,
                                    "tooltip": "生成图高度（32 倍数）"}),
            },
        }

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "LATENT")
    RETURN_NAMES = ("positive", "negative", "latent")
    FUNCTION = "encode"
    CATEGORY = "QIBO/Qwen Image"

    def encode(self, clip, prompt, negative_prompt, width=1024, height=1024):
        width = max(32, round(width / 32) * 32)
        height = max(32, round(height / 32) * 32)

        positive = clip.encode_from_tokens_scheduled(clip.tokenize(prompt, images=[], keep_vision=True, prevent_empty_text=True))
        negative = clip.encode_from_tokens_scheduled(clip.tokenize(negative_prompt, images=[], keep_vision=True, prevent_empty_text=True))

        latent = torch.zeros([1, 64, height // 16, width // 16], device=comfy.model_management.intermediate_device())
        return (positive, negative, {"samples": latent})


NODE_CLASS_MAPPINGS = {
    "QIBOQwenImage21T2I": QIBOQwenImage21T2INode,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBOQwenImage21T2I": "QIBO Qwen Image 2.1 文生图",
}