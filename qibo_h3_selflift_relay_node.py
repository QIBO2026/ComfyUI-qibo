# -*- coding: utf-8 -*-
"""QIBO H3 SelfLift 两段接力采样：一采低清预览 → 二采高清成片（同一去噪轨迹接力）。

背景：comfyui-SelfLift 的 SelfLiftH3Sampler 把"前 transition_step 步在低分辨率画布
去噪 → 干净端点 latent 放大（lift）→ 全分辨率收尾"焊在一个节点里，中间状态拿不出来。
本模块把它在交接点精确拆成两个节点，实现"先预览一采低清结果，满意后再用同一 latent
二采"的工作流，预览与成片严格同轨迹（不是两次独立生成的近似复现）：

- QIBO_H3_SELFLIFT_PASS1（一采·低清接力预览）
  按原版跑低清前缀 + lift（含 re-noise 与 Euler 边界重建），输出：
  ① preview_latent：lift 后的干净端点（视频流 + 音频流，空间约定与原版输出一致），
     直接接 VAEDecode / VAEDecodeAudio → VHS_VideoCombine 即得预览视频；
  ② relay_latent：半程接力状态（samples 为 inverse_noise_scaling + process_latent_out
     后的 resume latent，dict 内携带剩余 sigma 调度、seed、总步数等元数据）。
- QIBO_H3_SELFLIFT_PASS2（二采·高清成片）
  从 relay_latent 以零噪声按剩余 sigma 在全分辨率继续 Euler 收尾，
  输出与原版 SelfLiftH3Sampler 同 seed 下逐位一致的成片 latent。

接力数学与原版逐位一致（同 seed 确定性）：
- 低清前缀噪声 = prepare_noise(低清latent, seed)；
- lift 后按 sigma_k 用 (seed+1) 重加噪，Euler 重建跨边界的最后一步（NFE 不变）；
- 二采零噪声从 sigmas[transition_step:] 继续（latent 经 process_latent_in 往返还原）。

注意：同 seed 重跑一采是确定性的，因此"先跑一采预览 → 开启二采再排队"两次队列
之间无需缓存，接力状态自然一致。若换了模型/LoRA 等不可哈希输入，请重跑确认。

核心去噪与 lift 算法 vendored 自 comfyui-SelfLift（facok）master 分支，
见 qibo_h3_selflift_core/，本文件不依赖外部安装的 SelfLift 包。
"""

import logging

import torch

import comfy.k_diffusion.sampling
import comfy.model_management
import comfy.model_patcher
import comfy.model_sampling
import comfy.nested_tensor
import comfy.sample
import comfy.samplers
import comfy.utils
import latent_preview

from .qibo_h3_selflift_core import selflift
from .qibo_h3_selflift_core import h3_upscaler
from .qibo_h3_selflift_core import h3_tiling
from .qibo_h3_selflift_core.diagnostics import log_memory

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

_CATEGORY = "QIBO"

_RELAY_KEY = "qibo_selflift_relay"
_RELAY_VERSION = 1


# --------------------------------------------------------------------------
# 与 comfyui-SelfLift nodes.py 同源的校验/工具函数（保持逐位一致的语义）
# --------------------------------------------------------------------------
def _streams(samples):
    if samples.is_nested:
        return list(samples.unbind()), True
    return [samples], False


def _pack(streams, nested):
    if nested:
        return comfy.nested_tensor.NestedTensor(streams)
    return streams[0]


def _validate_sampling(model_sampling, sampler):
    if not isinstance(model_sampling, comfy.model_sampling.CONST):
        raise ValueError("QIBO H3 接力采样要求 rectified-flow 模型（SelfLift 同源约束）")
    if not isinstance(sampler, comfy.samplers.KSAMPLER) or sampler.sampler_function is not comfy.k_diffusion.sampling.sample_euler:
        raise ValueError("QIBO H3 接力采样要求标准 Euler 采样器（KSamplerSelect 选 euler）")
    if sampler.extra_options.get("s_churn", 0.0) != 0.0:
        raise ValueError("QIBO H3 接力采样要求 Euler 且 s_churn=0")


def _validate_schedule(sigmas, transition_step):
    if sigmas.ndim != 1 or not sigmas.is_floating_point():
        raise ValueError("QIBO H3 接力: sigmas 必须是一维浮点张量")
    if not torch.isfinite(sigmas).all() or (sigmas < 0).any():
        raise ValueError("QIBO H3 接力: sigmas 必须有限且非负")
    if sigmas.numel() < 2:
        return
    if not isinstance(transition_step, int) or not 1 <= transition_step <= sigmas.numel() - 2:
        raise ValueError(
            "QIBO H3 接力: transition_step={} 超出范围（{} 步调度下需 1~{}）".format(
                transition_step, sigmas.numel() - 1, sigmas.numel() - 2))
    if (sigmas[1:] > sigmas[:-1]).any():
        raise ValueError("QIBO H3 接力: sigmas 必须非递增")
    if (sigmas[:-1] <= 0).any():
        raise ValueError("QIBO H3 接力: 只有最后一个 sigma 可以为 0")
    if sigmas[transition_step] >= 1:
        raise ValueError("QIBO H3 接力: 高清段起始 sigma 必须小于 1")


def _validate_relay_schedule(sigmas):
    """二采侧对剩余调度的轻量校验（不再按 transition_step 语义检查）。"""
    if sigmas.ndim != 1 or not sigmas.is_floating_point():
        raise ValueError("QIBO H3 二采: 接力包内剩余 sigmas 非法（需一维浮点）")
    if sigmas.numel() < 2:
        raise ValueError("QIBO H3 二采: 接力包内剩余 sigmas 至少 2 个元素（1 步）")
    if not torch.isfinite(sigmas).all() or (sigmas < 0).any():
        raise ValueError("QIBO H3 二采: 接力包内剩余 sigmas 必须有限且非负")
    if (sigmas[1:] > sigmas[:-1]).any():
        raise ValueError("QIBO H3 二采: 接力包内剩余 sigmas 必须非递增")


def _validate_latent_input(latent_image):
    """校验 latent 模板；返回归一化的 noise_mask 或 None（与原版一致）。"""
    streams, _ = _streams(latent_image["samples"])
    if not streams or streams[0].ndim not in (4, 5):
        raise ValueError("QIBO H3 接力: 需要 4D 图像或 5D 视频 latent 尺寸模板")
    for stream in streams:
        if stream.ndim == 0 or any(size == 0 for size in stream.shape) or stream.shape[0] != streams[0].shape[0]:
            raise ValueError("QIBO H3 接力: latent 流必须非空且 batch 一致")
    mask = latent_image.get("noise_mask")
    if mask is None:
        return None
    video = streams[0].ndim == 5
    b, H, W = streams[0].shape[0], streams[0].shape[-2], streams[0].shape[-1]
    if mask.ndim == 3:
        mask = mask[:, None]
    if video and mask.ndim == 4:
        mask = mask[:, :, None]
    if mask.ndim != (5 if video else 4) or mask.shape[1] != 1:
        raise ValueError("QIBO H3 接力: noise_mask 形状需为 [B,H,W]/[B,1,H,W]/[B,1,T,H,W]")
    if mask.shape[0] != b:
        raise ValueError("QIBO H3 接力: noise_mask batch 与 latent batch 不一致")
    if tuple(mask.shape[-2:]) != (H, W):
        lead = mask.shape[:-2]
        mask = torch.nn.functional.interpolate(
            mask.reshape(-1, 1, *mask.shape[-2:]).float(), size=(H, W), mode="bilinear", align_corners=False
        ).reshape(*lead, H, W)
    if video and mask.shape[2] not in (1, streams[0].shape[2]):
        raise ValueError("QIBO H3 接力: noise_mask 时间长度与 latent 帧数不一致")
    if not torch.isfinite(mask).all():
        raise ValueError("QIBO H3 接力: noise_mask 必须有限")
    return mask.float().clamp(0.0, 1.0)


def _mask_blend_fn(anchor, mask):
    def fn(args):
        d = args["denoised"]
        m = mask.to(device=d.device, dtype=d.dtype)
        return d * m + anchor.to(device=d.device, dtype=d.dtype) * (1.0 - m)
    return fn


def _euler_step(state, denoised, sigma, sigma_next):
    step = ((sigma_next - sigma) / sigma).to(device=state.device, dtype=state.dtype)
    return state + (state - denoised.to(state)) * step


def _resize_keyframes(cond, h, w):
    """关键帧 cond latent 与生成网格共享；缩到低清网格（与原版一致）。"""
    out = []
    for tensor, d in cond:
        kfs = d.get("minimax_keyframes")
        if kfs is None:
            out.append((tensor, d))
            continue
        d = d.copy()
        resized = []
        for kf in kfs:
            kf = dict(kf)
            lat = kf.get("latent")
            if lat is not None and (lat.shape[-2] != h or lat.shape[-1] != w):
                if lat.ndim == 5:
                    batch, channels, frames = lat.shape[:3]
                    resized_latent = torch.nn.functional.interpolate(
                        lat.float().permute(0, 2, 1, 3, 4).reshape(batch * frames, channels, lat.shape[-2], lat.shape[-1]),
                        size=(h, w), mode="bilinear", align_corners=False
                    )
                    resized_latent = resized_latent.reshape(batch, frames, channels, h, w).permute(0, 2, 1, 3, 4)
                else:
                    resized_latent = torch.nn.functional.interpolate(
                        lat.float(), size=(h, w), mode="bilinear", align_corners=False
                    )
                source_mean = lat.float().mean(dim=(-2, -1), keepdim=True)
                resized_mean = resized_latent.mean(dim=(-2, -1), keepdim=True)
                kf["latent"] = (resized_latent + (source_mean - resized_mean)).to(lat)
            resized.append(kf)
        d["minimax_keyframes"] = resized
        out.append((tensor, d))
    return out


def _upscaler_input():
    models = ["none"] + h3_upscaler.list_upscaler_models()
    h3_models = [name for name in models[1:] if "h3" in name.lower()]
    default = h3_models[0] if h3_models else "none"
    return (models, {"default": default,
                     "tooltip": "外部 H3 latent 放大器（models/latent_upscale_models）。默认选第一个检测到的 H3 模型；'none' 用最近邻提升。"})


def _final_result(out, template):
    result = dict(template)
    result.pop(_RELAY_KEY, None)
    result["qibo_selflift_pass2_done"] = True
    result["samples"] = out.to(device=comfy.model_management.intermediate_device(),
                               dtype=comfy.model_management.intermediate_dtype())
    return result


# --------------------------------------------------------------------------
# 一采：低清前缀 + lift + 交接（原版 progressive_sample 在交接点切开的精确复刻）
# --------------------------------------------------------------------------
def relay_stage1(model, positive, negative, vae, latent_image, sampler, sigmas, seed, cfg,
                 transition_step, lowres_scale, rho, w_min, w_max, latent_upsample="nearest",
                 latent_lifter=None, highres_tiling=False, model_hires=None):
    _validate_schedule(sigmas, transition_step)
    if sigmas.numel() < 2:
        raise ValueError("QIBO H3 一采: sigmas 至少需要 2 个元素（1 步）")
    if not 0.25 <= lowres_scale <= 1.0:
        raise ValueError("QIBO H3 一采: lowres_scale 必须在 0.25~1.0")
    if not 0.0 <= rho <= 1.0:
        raise ValueError("QIBO H3 一采: rho 必须在 0~1")
    if not 0.0 <= w_min <= w_max <= 1.0:
        raise ValueError("QIBO H3 一采: 权重需满足 0 <= w_min <= w_max <= 1")
    noise_mask = _validate_latent_input(latent_image)
    if highres_tiling and noise_mask is not None:
        raise ValueError("QIBO H3 一采: noise_mask 与 highres_tiling 不兼容")

    model_sampling = model.get_model_object("model_sampling")
    _validate_sampling(model_sampling, sampler)

    streams, nested = _streams(comfy.sample.fix_empty_latent_channels(
        model, latent_image["samples"], latent_image.get("downscale_ratio_spacial", None),
        latent_image.get("downscale_ratio_temporal", None)))
    hires_base = model_hires if model_hires is not None else model
    high_model = h3_tiling.tiled_model(hires_base, [tuple(stream.shape) for stream in streams]) if highres_tiling else hires_base
    video = streams[0].ndim == 5
    if video:
        b, c, t, H, W = streams[0].shape
    else:
        b, c, H, W = streams[0].shape
        t = None
    h = max(2, round(H * lowres_scale / 2) * 2)
    w = max(2, round(W * lowres_scale / 2) * 2)
    low_shape = (b, c, t, h, w) if video else (b, c, h, w)
    logging.info("[QIBO H3 一采] low_latent=%s target_latent=%s low_nfe=%d high_nfe(留给二采)=%d "
                 "sigma_低清末步=%.8g sigma_交接=%.8g rho=%.4f weights=(%.4f, %.4f) cfg=%.4f mask=%s hires_model=%s",
                 low_shape, tuple(streams[0].shape), transition_step, sigmas.numel() - 1 - transition_step,
                 sigmas[transition_step - 1].item(), sigmas[transition_step].item(),
                 rho, w_min, w_max, cfg,
                 "无" if noise_mask is None else str(tuple(noise_mask.shape)),
                 "自定义" if model_hires is not None else "同模型")

    device = comfy.model_management.intermediate_device()
    source_video = streams[0].to(device)
    audio_streams = [s.to(device) for s in streams[1:]]

    def masked_model(base, video_anchor, m):
        if m is None:
            return base
        patched = base.clone()
        if nested:
            flat_mask = m.reshape(b, 1, -1).repeat(1, 1, c).to(video_anchor.device)
            flat_anchor = video_anchor.reshape(b, 1, -1)
            for s in audio_streams:
                flat_mask = torch.cat([flat_mask, torch.ones_like(s.reshape(b, 1, -1))], dim=-1)
                flat_anchor = torch.cat([flat_anchor, s.reshape(b, 1, -1)], dim=-1)
            hook = _mask_blend_fn(flat_anchor, flat_mask)
        else:
            hook = _mask_blend_fn(video_anchor, m)
        patched.model_options = comfy.model_patcher.set_model_options_post_cfg_function(patched.model_options, hook)
        return patched

    if video:
        low_video = torch.nn.functional.interpolate(
            source_video.float(), size=(t, h, w), mode="trilinear", align_corners=False
        ).to(dtype=source_video.dtype)
    else:
        low_video = torch.nn.functional.interpolate(
            source_video.float(), size=(h, w), mode="bilinear", align_corners=False
        ).to(dtype=source_video.dtype)
    m_full = m_low = None
    if noise_mask is not None:
        if video and noise_mask.shape[2] == 1 and t > 1:
            m_full = noise_mask.expand(b, 1, t, H, W)
        else:
            m_full = noise_mask
        if video:
            m_low = torch.nn.functional.interpolate(
                m_full.reshape(b * t, 1, H, W).float(), size=(h, w), mode="bilinear", align_corners=False
            ).reshape(b, 1, t, h, w)
        else:
            m_low = torch.nn.functional.interpolate(
                m_full.float(), size=(h, w), mode="bilinear", align_corners=False)
        m_low = m_low.clamp(0.0, 1.0)
    low_anchor = low_video
    video_anchor = source_video
    low_latent = _pack([low_video] + audio_streams, nested)
    low_model = masked_model(model, low_anchor, m_low)
    high_model = masked_model(high_model, video_anchor, m_full)
    del source_video, low_video
    del streams
    noise_low = comfy.sample.prepare_noise(low_latent, seed, latent_image.get("batch_index", None))

    total_steps = sigmas.shape[-1] - 1
    callback = latent_preview.prepare_callback(model, total_steps)
    disable_pbar = not comfy.utils.PROGRESS_BAR_ENABLED
    if video:
        positive_low = _resize_keyframes(positive, h, w)
        negative_low = _resize_keyframes(negative, h, w)
    else:
        positive_low, negative_low = positive, negative

    transition = {}
    low_evaluations = 0

    def callback_low(step, x0, x, total):
        nonlocal low_evaluations
        step = low_evaluations
        low_evaluations += 1
        if low_evaluations > transition_step:
            raise RuntimeError("QIBO H3 一采: 低分辨率回调次数超出 Euler 调度预期")
        if step == transition_step - 1:
            transition["state"] = x
            transition["x0"] = x0
        preview_x0 = x0
        if video:
            preview_streams_, preview_nested_ = _streams(x0)
            preview_video_ = torch.nn.functional.interpolate(
                preview_streams_[0].float(), size=(t, H, W), mode="trilinear", align_corners=False
            ).to(preview_streams_[0].dtype)
            preview_x0 = _pack([preview_video_] + preview_streams_[1:], preview_nested_)
            del preview_video_, preview_streams_
        elif x0.ndim == 4:
            preview_x0 = torch.nn.functional.interpolate(
                x0.float(), size=(H, W), mode="bilinear", align_corners=False
            ).to(x0.dtype)
        result = callback(step, preview_x0, preview_x0, total_steps)
        del preview_x0
        return result

    resolution_scale = (getattr(model.get_model_object("latent_format"), "spacial_downscale_ratio", 1)
                        if video else getattr(model.get_model_object("latent_format"), "spacial_downscale_ratio", 1))
    low_timer = _StageTimer("qibo_low_resolution", low_model.load_device, (h, w), resolution_scale)
    log_memory("qibo low_resolution start", low_model.load_device)
    comfy.samplers.sample(low_model, noise_low, positive_low, negative_low, cfg, low_model.load_device,
                          sampler, sigmas[:transition_step + 1], low_model.model_options,
                          latent_image=low_latent, callback=callback_low,
                          disable_pbar=disable_pbar, seed=seed)
    if low_evaluations != transition_step:
        raise RuntimeError("QIBO H3 一采: 低分辨率评估数 {} != transition_step {}；请检查采样器包装".format(
            low_evaluations, transition_step))
    low_timer.finish()
    log_memory("qibo low_resolution end", model.load_device)

    low_streams, nested = _streams(transition.pop("state"))
    x0_streams, _ = _streams(transition.pop("x0"))
    sigma_k = sigmas[transition_step - 1]
    sigma_next = sigmas[transition_step]
    auxiliary_next = [_euler_step(state.to(device), denoised.to(device), sigma_k, sigma_next)
                      for state, denoised in zip(low_streams[1:], x0_streams[1:])]
    latent_format = model.get_model_object("latent_format")
    z0_low_vae = latent_format.process_out(x0_streams[0].float()).to(device)
    del low_latent, noise_low, low_streams, positive_low, negative_low
    # 注意：x0_streams 保留（音频流要进预览 latent）

    need_pix = rho > 0.0 and w_max > 0.0
    need_lat = not (rho >= 1.0 and w_min >= 1.0 and w_max >= 1.0)
    z_lat_vae, z_pix_vae = selflift.paired_lifts(
        z0_low_vae, vae, (H, W), latent_upsample, latent_lifter,
        need_lat=need_lat, need_pix=need_pix)
    z_lat = latent_format.process_in(z_lat_vae) if z_lat_vae is not None else None
    z_pix = latent_format.process_in(z_pix_vae) if z_pix_vae is not None else None
    z0_high = selflift.artifact_aware_consistency_lift(z_lat, z_pix, rho, w_min, w_max, mask=m_full)
    if m_full is not None:
        m_cast = m_full.to(device=z0_high.device, dtype=z0_high.dtype)
        z0_high = z0_high * m_cast + video_anchor * (1.0 - m_cast)
    z0_high = z0_high.to(device)
    del z0_low_vae, z_lat_vae, z_pix_vae, z_lat, z_pix

    # 预览 latent：lift 后的干净端点（视频流）+ 一采的干净音频流。
    # 空间约定与原版节点输出一致（sigma=0 状态空间），VAEDecode/VAEDecodeAudio 直接解码。
    audio_x0 = [s.to(device) for s in x0_streams[1:]]
    del x0_streams
    preview_samples = _pack([z0_high] + audio_x0, nested).to(
        device=comfy.model_management.intermediate_device(),
        dtype=comfy.model_management.intermediate_dtype())

    # 接力状态：与原版完全相同的 re-noise（seed+1）+ Euler 边界重建
    transition_timer = _StageTimer("qibo_transition", model.load_device, (H, W), resolution_scale)
    video_noise = comfy.sample.prepare_noise(z0_high, (seed + 1) % (1 << 64),
                                             latent_image.get("batch_index", None)).to(z0_high)
    video_state = model_sampling.noise_scaling(sigma_k, video_noise, z0_high)
    next_streams = [_euler_step(video_state, z0_high, sigma_k, sigma_next)] + auxiliary_next
    del z0_high, video_noise, video_state, auxiliary_next
    resume_streams = [model_sampling.inverse_noise_scaling(sigma_next, s) for s in next_streams]
    resume_latent = model.model.process_latent_out(_pack(resume_streams, nested))
    del next_streams, resume_streams
    transition_timer.finish()

    preview_latent = latent_image.copy()
    preview_latent["samples"] = preview_samples

    relay = latent_image.copy()
    relay["samples"] = resume_latent
    relay[_RELAY_KEY] = {
        "version": _RELAY_VERSION,
        "sigmas_rest": sigmas[transition_step:].detach().to("cpu").clone(),
        "seed": int(seed),
        "cfg": float(cfg),
        "transition_step": int(transition_step),
        "total_steps": int(total_steps),
        "nested": bool(nested),
        "lowres_scale": float(lowres_scale),
        "sigma_k": float(sigma_k.item()),
        "sigma_next": float(sigma_next.item()),
    }
    log_memory("qibo relay ready", model.load_device)
    return preview_latent, relay


# --------------------------------------------------------------------------
# 二采：全分辨率剩余调度收尾（原版 high_resolution 段的精确复刻）
# --------------------------------------------------------------------------
def relay_stage2(model, positive, negative, relay, sampler, cfg,
                 model_hires=None, highres_tiling=False):
    meta = relay.get(_RELAY_KEY)
    if not isinstance(meta, dict) or meta.get("version") != _RELAY_VERSION or "sigmas_rest" not in meta:
        raise ValueError(
            "QIBO H3 二采: 输入 latent 缺少接力元数据。relay_latent 输入必须连到"
            "「QIBO H3 一采·低清接力预览」的 relay_latent 输出（直连即可，中间不要经过会"
            "重建 latent dict 的节点）。若要跑原版单节点流程请直接用 SelfLiftH3Sampler。")

    sigmas_rest = meta["sigmas_rest"]
    _validate_relay_schedule(sigmas_rest)
    seed = int(meta["seed"])
    transition_step = int(meta["transition_step"])
    total_steps = int(meta["total_steps"])

    model_sampling = model.get_model_object("model_sampling")
    _validate_sampling(model_sampling, sampler)

    streams, nested = _streams(relay["samples"])
    hires_base = model_hires if model_hires is not None else model
    high_model = h3_tiling.tiled_model(hires_base, [tuple(stream.shape) for stream in streams]) if highres_tiling else hires_base

    logging.info("[QIBO H3 二采] resume_latent=%s 剩余步数=%d 总步数=%d transition_step=%d "
                 "seed=%d cfg=%.4f tiling=%s hires_model=%s",
                 tuple(streams[0].shape), sigmas_rest.numel() - 1, total_steps,
                 transition_step, seed, cfg, highres_tiling,
                 "自定义" if model_hires is not None else "同模型")

    resume_noise = _pack([torch.zeros_like(s) for s in streams], nested)
    callback = latent_preview.prepare_callback(model, total_steps)
    disable_pbar = not comfy.utils.PROGRESS_BAR_ENABLED

    high_evaluations = 0

    def callback_high(step, x0, x, total):
        nonlocal high_evaluations
        step = high_evaluations
        high_evaluations += 1
        if high_evaluations > sigmas_rest.numel() - 1:
            raise RuntimeError("QIBO H3 二采: 高分辨率回调次数超出剩余调度预期")
        return callback(step + transition_step, x0, x, total_steps)

    out = comfy.samplers.sample(high_model, resume_noise, positive, negative, cfg, model.load_device,
                                sampler, sigmas_rest, high_model.model_options,
                                latent_image=relay["samples"], callback=callback_high,
                                disable_pbar=disable_pbar, seed=seed)
    if high_evaluations != sigmas_rest.numel() - 1:
        raise RuntimeError("QIBO H3 二采: 高分辨率评估数 {} != 剩余步数 {}".format(
            high_evaluations, sigmas_rest.numel() - 1))

    try:
        import gc
        gc.collect()
        comfy.model_management.soft_empty_cache()
    except Exception:
        pass

    return _final_result(out, relay)


class _StageTimer:
    """轻量计时（仅日志，不影响执行）。"""

    def __init__(self, stage, device, resolution=None, pixel_scale=1):
        self.stage = stage
        self.previous = self.started = None
        self.device = torch.device(device)
        self.synchronize = False
        import time
        self._time = time.perf_counter
        self.started = self.previous = self._now()
        logging.info("[QIBO H3 timing] %s start", stage)

    def _now(self):
        if self.synchronize:
            torch.cuda.synchronize(self.device)
        return self._time()

    def mark(self, label):
        current = self._now()
        logging.info("[QIBO H3 timing] %s %s: %.3fs", self.stage, label, current - self.previous)
        self.previous = current

    def finish(self):
        current = self._now()
        logging.info("[QIBO H3 timing] %s total: %.3fs", self.stage, current - self.started)


# --------------------------------------------------------------------------
# 节点定义
# --------------------------------------------------------------------------
class QBH3SelfLiftPass1:
    """一采：低清去噪前缀 + latent 放大，输出预览 latent 与接力 latent。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "model": ("MODEL", {"tooltip": "H3 模型（与原版 SelfLiftH3Sampler 相同的 model 输入）"}),
            "positive": ("CONDITIONING", {"tooltip": "正向条件（ReferenceToVideo 输出）"}),
            "negative": ("CONDITIONING", {"tooltip": "负向条件"}),
            "vae": ("VAE", {"tooltip": "视频 VAE（lift 与预览解码用）"}),
            "latent_image": ("LATENT", {"tooltip": "目标分辨率 H3 AV latent（ReferenceToVideo 构建），定义尺寸与时长"}),
            "sampler": ("SAMPLER", {"tooltip": "仅支持标准 Euler（KSamplerSelect 选 euler）"}),
            "sigmas": ("SIGMAS", {"tooltip": "完整 sigma 调度（BasicScheduler 输出，与原版一致）"}),
            "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff, "control_after_generate": True,
                             "tooltip": "种子。一采/二采共用：固定 seed 后「预览满意 → 开启二采再排队」得到的就是预览这条"}),
            "cfg": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 100.0, "step": 0.1, "round": 0.01}),
            "transition_step": ("INT", {"default": 6, "min": 1, "max": 10000,
                                        "tooltip": "低分辨率去噪评估步数（与原版一致）"}),
            "lowres_scale": ("FLOAT", {"default": 0.6, "min": 0.25, "max": 1.0, "step": 0.05,
                                       "tooltip": "低清前缀相对目标分辨率的空间缩放"}),
            "rho": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.05,
                              "tooltip": "像素锚点修正比例。0=纯外部 latent 放大器（原工作流默认）"}),
            "w_min": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.05}),
            "w_max": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.05}),
            "upscaler_model": _upscaler_input(),
        }, "optional": {
            "model_hires": ("MODEL", {"tooltip": "可选：高清段用不同模型/LoRA（一采始终用 model）"}),
            "highres_tiling": ("BOOLEAN", {"default": False, "label_on": "高分辨率分块：开启", "label_off": "高分辨率分块：关闭"}),
            "upscaler_unload": ("BOOLEAN", {"default": True, "label_on": "放大后卸载：开启", "label_off": "放大后卸载：关闭"}),
        }}

    RETURN_TYPES = ("LATENT", "LATENT")
    RETURN_NAMES = ("preview_latent(一采预览)", "relay_latent(接力)")
    FUNCTION = "sample"
    CATEGORY = _CATEGORY
    DESCRIPTION = (
        "QIBO H3 一采（SelfLift 接力版）：先在低分辨率画布完成前 transition_step 步去噪，"
        "再把干净端点 latent 放大到目标分辨率。输出 preview_latent（可解码出预览视频，"
        "画面逻辑/人物已定）与 relay_latent（半程接力状态）。"
        "预览满意后，把 relay_latent 接「QIBO H3 二采·高清成片」即可得到与预览同轨迹的成片。"
        "与原版 SelfLiftH3Sampler 同 seed 逐位一致。"
    )

    def sample(self, model, positive, negative, vae, latent_image, sampler, sigmas, seed, cfg,
               transition_step, lowres_scale, rho, w_min, w_max, upscaler_model,
               model_hires=None, highres_tiling=False, upscaler_unload=True):
        if rho == 0.0 and upscaler_model == "none":
            raise ValueError(
                "QIBO H3 一采: rho=0 且 upscaler_model=none 时既无 SelfLift-zero 修正也无外部放大，"
                "请选择 rho>0 或指定外部 H3 放大器。")
        lifter = None
        if upscaler_model != "none":
            if rho > 0.0 and w_max > 0.0:
                logging.warning("QIBO H3 一采: rho>0 且使用外部放大器为混合实验；upscaler_model=none 才是论文的 SelfLift-zero 路线")
            lifter = lambda z, hw: h3_upscaler.learned_latent_lift(z, hw, upscaler_model, force_unload=upscaler_unload)
        preview, relay = relay_stage1(model, positive, negative, vae, latent_image, sampler, sigmas, seed, cfg,
                                      int(transition_step), float(lowres_scale), float(rho),
                                      float(w_min), float(w_max), "nearest",
                                      latent_lifter=lifter, highres_tiling=highres_tiling,
                                      model_hires=model_hires)
        return (preview, relay)


class QBH3SelfLiftPass2:
    """二采：从一采接力 latent 以零噪声按剩余 sigma 在全分辨率收尾。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "model": ("MODEL", {"tooltip": "H3 模型（与一采相同；如一采用了 model_hires 则这里接同一个 hires 模型）"}),
            "positive": ("CONDITIONING", {"tooltip": "正向条件（与一采同源，目标分辨率原样条件）"}),
            "negative": ("CONDITIONING", {"tooltip": "负向条件"}),
            "vae": ("VAE", {"tooltip": "视频 VAE（tiling 时需要；一般仍接同一 VAE）"}),
            "sampler": ("SAMPLER", {"tooltip": "仅支持标准 Euler（与一采同一个 KSamplerSelect）"}),
            "relay_latent": ("LATENT", {"tooltip": "必须连「QIBO H3 一采·低清接力预览」的 relay_latent 输出"}),
            "cfg": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 100.0, "step": 0.1, "round": 0.01,
                              "tooltip": "与一采保持一致（接力包内记录了一采 cfg，可对照）"}),
        }, "optional": {
            "model_hires": ("MODEL", {"tooltip": "可选：与一采的 model_hires 保持一致"}),
            "highres_tiling": ("BOOLEAN", {"default": False, "label_on": "高分辨率分块：开启", "label_off": "高分辨率分块：关闭"}),
        }}

    RETURN_TYPES = ("LATENT",)
    RETURN_NAMES = ("final_latent(成片)",)
    FUNCTION = "sample"
    CATEGORY = _CATEGORY
    DESCRIPTION = (
        "QIBO H3 二采（SelfLift 接力版）：输入一采的 relay_latent，以零噪声按剩余 sigma "
        "调度在全分辨率继续 Euler 收尾，输出成片 latent。与原版 SelfLiftH3Sampler "
        "（同 seed）逐位一致——预览与成片是同一条去噪轨迹。"
    )

    def sample(self, model, positive, negative, vae, sampler, relay_latent, cfg,
               model_hires=None, highres_tiling=False):
        result = relay_stage2(model, positive, negative, relay_latent, sampler, float(cfg),
                              model_hires=model_hires, highres_tiling=highres_tiling)
        return (result,)


# --------------------------------------------------------------------------
# 接力存档：一采结果（relay/preview latent + 条件 token）打包存盘 / 加载离线二采
# --------------------------------------------------------------------------
import os
import time

import folder_paths

_RELAY_DIR_NAME = "qibo_h3"


def _relay_dir():
    base = folder_paths.get_output_directory()
    d = os.path.join(base, _RELAY_DIR_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def _archive_names():
    d = _relay_dir()
    try:
        return sorted(fn for fn in os.listdir(d) if fn.endswith(".pt"))
    except OSError:
        return []


def _resolve_relay_path(filename):
    filename = (filename or "").strip().strip('"').strip("'")
    if not filename:
        raise ValueError("QIBO H3 接力存档: 文件名不能为空")
    if not filename.endswith(".pt"):
        filename += ".pt"
    if os.path.isabs(filename):
        return filename
    return os.path.join(_relay_dir(), filename)


def _split_cpu(latent):
    """latent dict 的 samples 拆流搬到 CPU（NestedTensor 不可直接 pickle）。"""
    d = dict(latent)
    streams, nested = _streams(d["samples"])
    d["samples"] = _pack([s.detach().to("cpu", copy=True) for s in streams], nested)
    return d


def _cpuize(obj):
    """递归把 dict/list/tuple 里的 tensor 搬到 CPU（其他对象原样保留）。"""
    if isinstance(obj, torch.Tensor):
        return obj.detach().to("cpu", copy=True)
    if isinstance(obj, dict):
        return {k: _cpuize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_cpuize(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_cpuize(v) for v in obj)
    return obj


def _restore_device(latent):
    """加载后的 latent samples 搬回计算设备（保持 dtype 不变）。"""
    d = dict(latent)
    device = comfy.model_management.intermediate_device()
    streams, nested = _streams(d["samples"])
    d["samples"] = _pack([s.to(device) for s in streams], nested)
    return d


def _cond_to_device(cond):
    device = comfy.model_management.intermediate_device()

    def rec(x):
        if isinstance(x, torch.Tensor):
            return x.to(device)
        if isinstance(x, dict):
            return {k: rec(v) for k, v in x.items()}
        if isinstance(x, list):
            return [rec(v) for v in x]
        if isinstance(x, tuple):
            return tuple(rec(v) for v in x)
        return x

    return rec(cond)


class QBH3SelfLiftRelaySave:
    """接力存档·保存：把一采的接力/预览 latent 与条件 token 打包存为一个 .pt 文件。

    relay_latent 输出为直通（同一个 dict 原样返回），可串在一采与二采之间，
    不影响原有连线拓扑。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "relay_latent": ("LATENT", {"tooltip": "「QIBO H3 一采」的 relay_latent 输出（直通到输出）"}),
            "filename": ("STRING", {"default": "qibo_h3",
                                    "tooltip": "手动命名模式下的存档文件名（自动补 .pt）。批量自动命名开启时忽略"}),
        }, "optional": {
            "auto_name": ("BOOLEAN", {"default": True, "label_on": "批量自动命名：开启", "label_off": "批量自动命名：关闭",
                                      "tooltip": "开启：每次执行按时间戳生成新存档（批量存档互不覆盖）；关闭：用 filename 覆盖保存"}),
            "preview_latent": ("LATENT", {"tooltip": "可选：一采预览 latent，一并存入（供离线直接解码预览）"}),
            "positive": ("CONDITIONING", {"tooltip": "可选：正向条件 token（与一采同源，二采免重算参考编码）"}),
            "negative": ("CONDITIONING", {"tooltip": "可选：负向条件 token"}),
            "include_cond": ("BOOLEAN", {"default": True, "label_on": "保存条件 token：开启", "label_off": "保存条件 token：关闭",
                                         "tooltip": "开启后条件一并打包；若条件里含不可序列化对象导致保存失败，可关闭只存 latent"}),
        }}

    RETURN_TYPES = ("LATENT",)
    RETURN_NAMES = ("relay_latent(接力)",)
    FUNCTION = "save"
    CATEGORY = _CATEGORY
    OUTPUT_NODE = True
    DESCRIPTION = (
        "QIBO H3 接力存档（保存）：把一采的 relay_latent（含剩余 sigma 调度、seed 等接力元数据）、"
        "预览 latent 和条件 token 一起存成 .pt 文件。二采时用「QIBO H3 接力存档·加载」"
        "直接读回，前面的参考图/视频/音频编码与一采计算全部不用重跑。"
    )

    def save(self, relay_latent, filename, auto_name=True, preview_latent=None,
             positive=None, negative=None, include_cond=True):
        if auto_name:
            filename = time.strftime("auto_%Y%m%d_%H%M%S")
        payload = {
            "format": "qibo_h3_relay_bundle",
            "version": _RELAY_VERSION,
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "relay": _cpuize(_split_cpu(relay_latent)),
            "preview": _cpuize(_split_cpu(preview_latent)) if preview_latent is not None else None,
            "positive": _cpuize(positive) if (include_cond and positive is not None) else None,
            "negative": _cpuize(negative) if (include_cond and negative is not None) else None,
        }
        path = _resolve_relay_path(filename)
        if auto_name:
            stem, ext = os.path.splitext(path)
            n = 1
            while os.path.exists(path):
                path = "{}_{}{}".format(stem, n, ext)
                n += 1
        tmp = path + ".tmp"
        try:
            torch.save(payload, tmp)
            os.replace(tmp, path)
        except Exception as e:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            raise ValueError(
                "QIBO H3 接力存档: 保存失败（{}）。若错误与条件序列化有关，"
                "可把 include_cond 关掉只存 latent（此时离线二采需接回原条件链）。".format(e))
        size_mb = os.path.getsize(path) / (1024 * 1024)
        logging.info("[QIBO H3 接力存档] 已保存 %s（%.1f MB，条件=%s）",
                     path, size_mb, "有" if payload["positive"] is not None else "无")
        return {"ui": {"text": ["已保存: {}\n大小: {:.1f} MB\n条件token: {}".format(
            path, size_mb, "有" if payload["positive"] is not None else "无")]},
            "result": (relay_latent,)}


class QBH3SelfLiftRelayLoad:
    """接力存档·加载：读回存档，输出 relay/preview latent 与条件 token，供离线二采。"""

    _EMPTY = "(无存档-先在存档工作流跑一采)"

    @classmethod
    def INPUT_TYPES(cls):
        names = _archive_names()
        if not names:
            names = [cls._EMPTY]
        return {"required": {
            "filename": (names, {"tooltip": "选择存档（output/qibo_h3/ 目录下的 .pt）。"
                                            "列表在页面刷新/按 R 后更新；也可用「QIBO H3 存档管理」节点弹窗查看/删除/直接选用"}),
        }}

    RETURN_TYPES = ("LATENT", "LATENT", "CONDITIONING", "CONDITIONING")
    RETURN_NAMES = ("relay_latent(接力)", "preview_latent(预览)", "positive(正向)", "negative(负向)")
    FUNCTION = "load"
    CATEGORY = _CATEGORY
    DESCRIPTION = (
        "QIBO H3 接力存档（加载）：从下拉列表选择一采生成的存档（output/qibo_h3/），"
        "输出接力 latent、预览 latent 和条件 token。接「QIBO H3 二采·高清成片」"
        "即可离线完成二采——模型加载外，前面全部计算都不用重跑。"
    )

    def load(self, filename):
        if filename.startswith("("):
            raise ValueError(
                "QIBO H3 接力存档: 当前还没有可选存档。请先在《接力二采_存档》工作流跑完一采，"
                "存档会自动保存到 ComfyUI 的 output/qibo_h3/ 目录，然后按 R 刷新列表。")
        path = _resolve_relay_path(filename)
        if not os.path.exists(path):
            raise ValueError(
                "QIBO H3 接力存档: 找不到存档文件 {}。存档默认在 ComfyUI 的 "
                "output/qibo_h3/ 目录下（保存节点会打印完整路径；列表按 R 刷新）。".format(path))
        try:
            payload = torch.load(path, map_location="cpu", weights_only=False)
        except TypeError:
            payload = torch.load(path, map_location="cpu")
        if not isinstance(payload, dict) or payload.get("format") != "qibo_h3_relay_bundle":
            raise ValueError("QIBO H3 接力存档: {} 不是本节点保存的存档文件".format(path))
        if payload.get("version") != _RELAY_VERSION:
            raise ValueError("QIBO H3 接力存档: 存档版本不兼容（存档 v{}，当前 v{}），请重跑一采重新存档".format(
                payload.get("version"), _RELAY_VERSION))

        relay = _restore_device(payload["relay"])
        if _RELAY_KEY not in relay:
            raise ValueError("QIBO H3 接力存档: 存档里的 relay latent 缺少接力元数据，文件可能损坏")
        preview = _restore_device(payload["preview"]) if payload.get("preview") is not None else relay
        positive = payload.get("positive")
        negative = payload.get("negative")
        if positive is None or negative is None:
            raise ValueError(
                "QIBO H3 接力存档: 该存档未包含条件 token（保存时 include_cond 关了，或保存时没接"
                " positive/negative）。离线二采需要条件，请在存档工作流里接上并重新保存。")
        positive = _cond_to_device(positive)
        negative = _cond_to_device(negative)
        logging.info("[QIBO H3 接力存档] 已加载 %s（保存于 %s）", path, payload.get("saved_at"))
        return (relay, preview, positive, negative)


class QBH3ArchiveManager:
    """存档管理（纯 UI 节点）：点节点上的按钮弹出存档管理面板。

    面板功能由 js/qibo_h3_archive_manager.js 实现：
    列出 output/qibo_h3/ 全部存档（名字/大小/时间）、勾选批量删除、
    一键把选中存档设为当前图里「QIBO H3 接力存档·加载」的二采来源。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {}}

    RETURN_TYPES = ()
    FUNCTION = "noop"
    CATEGORY = _CATEGORY
    OUTPUT_NODE = True
    DESCRIPTION = (
        "QIBO H3 存档管理器：点按钮打开管理面板——查看/删除存档（支持多选）、"
        "选择哪个存档用于二采。存档目录：output/qibo_h3/。"
    )

    def noop(self):
        return {"ui": {"text": ["点节点上的「存档管理」按钮打开面板"]}, "result": []}


NODE_CLASS_MAPPINGS["QIBO_H3_SELFLIFT_PASS1"] = QBH3SelfLiftPass1
NODE_CLASS_MAPPINGS["QIBO_H3_SELFLIFT_PASS2"] = QBH3SelfLiftPass2
NODE_CLASS_MAPPINGS["QIBO_H3_SELFLIFT_RELAY_SAVE"] = QBH3SelfLiftRelaySave
NODE_CLASS_MAPPINGS["QIBO_H3_SELFLIFT_RELAY_LOAD"] = QBH3SelfLiftRelayLoad
NODE_CLASS_MAPPINGS["QIBO_H3_ARCHIVE_MANAGER"] = QBH3ArchiveManager
NODE_DISPLAY_NAME_MAPPINGS["QIBO_H3_SELFLIFT_PASS1"] = "QIBO H3 一采·低清接力预览"
NODE_DISPLAY_NAME_MAPPINGS["QIBO_H3_SELFLIFT_PASS2"] = "QIBO H3 二采·高清成片"
NODE_DISPLAY_NAME_MAPPINGS["QIBO_H3_SELFLIFT_RELAY_SAVE"] = "QIBO H3 接力存档·保存"
NODE_DISPLAY_NAME_MAPPINGS["QIBO_H3_SELFLIFT_RELAY_LOAD"] = "QIBO H3 接力存档·加载"
NODE_DISPLAY_NAME_MAPPINGS["QIBO_H3_ARCHIVE_MANAGER"] = "QIBO H3 存档管理"

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "QBH3SelfLiftPass1",
    "QBH3SelfLiftPass2",
    "QBH3SelfLiftRelaySave",
    "QBH3SelfLiftRelayLoad",
    "QBH3ArchiveManager",
    "relay_stage1",
    "relay_stage2",
]
