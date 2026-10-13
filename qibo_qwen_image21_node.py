import math
import torch
import comfy.utils
import comfy.model_management
import node_helpers


class QIBOQwenImage21EncodeNode:
    @classmethod
    def INPUT_TYPES(cls):
        optional = {
            "vae": ("VAE",),
            "resolution": ("INT", {
                "default": 0, "min": 0, "max": 4096, "step": 32,
                "tooltip": "每张参考图各自按 resolution 总面积缩放保持长宽比（32 倍数）。0=用原图尺寸但长边 cap 2048（QIBO 增强：2048 以内图不压缩保留小字细节，超过 2048 的大图等比缩到 2048 防止偏离训练分布）。>0 时按官方逻辑压缩到 resolution 总面积。"
            }),
        }
        for i in range(1, 11):
            optional[f"image_{i}"] = ("IMAGE", {"tooltip": f"参考图 {i}，按端口号顺序送入视觉塔与 VAE"})

        return {
            "required": {
                "clip": ("CLIP",),
                "prompt": ("STRING", {"multiline": True, "dynamicPrompts": True}),
                "negative_prompt": ("STRING", {"multiline": True, "dynamicPrompts": True, "default": ""}),
            },
            "optional": optional,
        }

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "LATENT")
    RETURN_NAMES = ("positive", "negative", "latent")
    FUNCTION = "encode"
    CATEGORY = "QIBO/Qwen Image"

    def encode(self, clip, prompt, negative_prompt, vae=None, resolution=1024,
               image_1=None, image_2=None, image_3=None, image_4=None, image_5=None,
               image_6=None, image_7=None, image_8=None, image_9=None, image_10=None):
        ref_latents = []
        images_vl = []
        latent_w = latent_h = resolution or 1024

        port_images = (image_1, image_2, image_3, image_4, image_5,
                       image_6, image_7, image_8, image_9, image_10)

        for image in port_images:
            if image is None:
                continue
            samples = image[:1].movedim(-1, 1)
            if resolution > 0:
                ratio = samples.shape[3] / samples.shape[2]
                width = round(math.sqrt(resolution * resolution * ratio) / 32) * 32
                height = round(math.sqrt(resolution * resolution / ratio) / 32) * 32
            else:
                width, height = round(samples.shape[3] / 32) * 32, round(samples.shape[2] / 32) * 32
                long_side = max(width, height)
                if long_side > 2048:
                    scale = 2048.0 / long_side
                    width = round(width * scale / 32) * 32
                    height = round(height * scale / 32) * 32
            width, height = max(32, width), max(32, height)
            if (width, height) == (samples.shape[3], samples.shape[2]):
                s = image[:1]
            else:
                s = comfy.utils.common_upscale(samples, width, height, "lanczos", "disabled").movedim(1, -1)
            if not images_vl:
                latent_w, latent_h = width, height
            rgb = s[:, :, :, :3]
            if s.shape[-1] > 3:
                rgb = rgb * s[:, :, :, 3:] + (1.0 - s[:, :, :, 3:])
            images_vl.append(rgb)
            if vae is not None:
                ref_latents.append(vae.encode(s))

        keep_vision = len(ref_latents) == 0
        positive = clip.encode_from_tokens_scheduled(clip.tokenize(prompt, images=images_vl, keep_vision=keep_vision, prevent_empty_text=True))
        negative = clip.encode_from_tokens_scheduled(clip.tokenize(negative_prompt, images=images_vl, keep_vision=keep_vision, prevent_empty_text=True))
        if len(ref_latents) > 0:
            positive = node_helpers.conditioning_set_values(positive, {"reference_latents": ref_latents}, append=True)
            negative = node_helpers.conditioning_set_values(negative, {"reference_latents": ref_latents}, append=True)
        latent = torch.zeros([1, 64, latent_h // 16, latent_w // 16], device=comfy.model_management.intermediate_device())
        return (positive, negative, {"samples": latent})


NODE_CLASS_MAPPINGS = {
    "QIBOQwenImage21Encode": QIBOQwenImage21EncodeNode,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBOQwenImage21Encode": "QIBO Qwen Image 2.1 编码 (10图)",
}
