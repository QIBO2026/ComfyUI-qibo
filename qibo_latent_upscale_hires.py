"""QIBO 潜空间放大（Hires Fix）节点。

集成三段式高清修复：
1. 潜空间放大（common_upscale 按 scale_by 缩放 latent）
2. 可选像素放大：vae decode → model_hires (UPSCALE_MODEL) → vae encode
3. 可选重采样：model + positive + negative + sampler + sigmas 走 sample_custom

任一可选输入未连接则跳过对应阶段，灵活组合。
"""

import torch

import comfy
import comfy.model_management
import comfy.sample
import comfy.utils
import latent_preview


def _upscale_image_with_model(upscale_model, image):
    device = upscale_model.patcher.load_device
    memory_required = (512 * 512 * 3) * image.element_size() * max(upscale_model.scale, 1.0) * 384.0
    memory_required += image.nelement() * image.element_size()
    comfy.model_management.load_models_gpu([upscale_model.patcher], memory_required=memory_required, force_full_load=True)

    in_img = image.movedim(-1, -3).to(device)
    tile = 512
    overlap = 32
    output_device = comfy.model_management.intermediate_device()

    oom = True
    while oom:
        try:
            steps = in_img.shape[0] * comfy.utils.get_tiled_scale_steps(
                in_img.shape[3], in_img.shape[2], tile_x=tile, tile_y=tile, overlap=overlap)
            pbar = comfy.utils.ProgressBar(steps)
            s = comfy.utils.tiled_scale(
                in_img, lambda a: upscale_model(a.float()),
                tile_x=tile, tile_y=tile, overlap=overlap,
                upscale_amount=upscale_model.scale, pbar=pbar, output_device=output_device)
            oom = False
        except Exception as e:
            comfy.model_management.raise_non_oom(e)
            tile //= 2
            if tile < 128:
                raise

    return torch.clamp(s.movedim(-3, -1), min=0, max=1.0).to(comfy.model_management.intermediate_dtype())


class QIBOLatentUpscaleHires:
    CATEGORY = "QIBO"

    upscale_methods = ["nearest-exact", "bilinear", "area", "bicubic", "bislerp"]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "latent_image": ("LATENT",),
                "upscale_method": (cls.upscale_methods,),
                "scale_by": ("FLOAT", {"default": 1.5, "min": 0.01, "max": 8.0, "step": 0.01}),
            },
            "optional": {
                "model": ("MODEL",),
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "vae": ("VAE",),
                "model_hires": ("UPSCALE_MODEL",),
                "sampler": ("SAMPLER",),
                "sigmas": ("SIGMAS",),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff, "control_after_generate": True}),
                "cfg": ("FLOAT", {"default": 8.0, "min": 0.0, "max": 100.0, "step": 0.1, "round": 0.01}),
            },
        }

    RETURN_TYPES = ("LATENT",)
    FUNCTION = "upscale"

    def upscale(self, latent_image, upscale_method, scale_by,
                model=None, positive=None, negative=None, vae=None, model_hires=None,
                sampler=None, sigmas=None, seed=0, cfg=8.0):
        s = dict(latent_image)
        samples = s["samples"]

        width = max(64, round(samples.shape[-1] * scale_by))
        height = max(64, round(samples.shape[-2] * scale_by))
        s["samples"] = comfy.utils.common_upscale(samples, width, height, upscale_method, "disabled")

        if model_hires is not None and vae is not None:
            pixels = vae.decode(s["samples"])
            pixels = _upscale_image_with_model(model_hires, pixels)
            s["samples"] = vae.encode(pixels)

        if (model is not None and sampler is not None and sigmas is not None
                and positive is not None and negative is not None):
            latent = dict(s)
            li = comfy.sample.fix_empty_latent_channels(
                model, s["samples"],
                latent.get("downscale_ratio_spacial"),
                latent.get("downscale_ratio_temporal"))
            latent["samples"] = li
            noise = comfy.sample.prepare_noise(li, seed, latent.get("batch_index"))
            noise_mask = latent.get("noise_mask")
            x0_output = {}
            callback = latent_preview.prepare_callback(model, sigmas.shape[-1] - 1, x0_output)
            disable_pbar = not comfy.utils.PROGRESS_BAR_ENABLED
            out_samples = comfy.sample.sample_custom(
                model, noise, cfg, sampler, sigmas, positive, negative, li,
                noise_mask=noise_mask, callback=callback, disable_pbar=disable_pbar, seed=seed)
            out = dict(latent)
            out.pop("downscale_ratio_spacial", None)
            out.pop("downscale_ratio_temporal", None)
            out["samples"] = out_samples
            s = out

        return (s,)


NODE_CLASS_MAPPINGS = {
    "QIBOLatentUpscaleHires": QIBOLatentUpscaleHires,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBOLatentUpscaleHires": "qibo 潜空间放大",
}