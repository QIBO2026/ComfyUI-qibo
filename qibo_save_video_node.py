import os
import subprocess
import shutil
import tempfile
import gc
import typing

import torch
import einops

try:
    import folder_paths
except ImportError:
    folder_paths = None

try:
    from comfy.model_management import get_torch_device, soft_empty_cache
except ImportError:
    get_torch_device = lambda: torch.device("cuda" if torch.cuda.is_available() else "cpu")
    soft_empty_cache = lambda: None


def _ffmpeg_path():
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    raise RuntimeError("ffmpeg not found")


class QIBOSaveVideoNode:
    CATEGORY = "QIBO"
    FUNCTION = "save_video"
    OUTPUT_NODE = True
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("saved_path",)
    DESCRIPTION = "Receive IMAGE batch + optional AUDIO, encode to mp4 via ffmpeg, save to output."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "fps": ("FLOAT", {"default": 24, "min": 1, "max": 120, "step": 0.1}),
                "filename_prefix": ("STRING", {"default": "qibo_video"}),
            },
            "optional": {
                "audio": ("AUDIO",),
                "crf": ("INT", {"default": 18, "min": 0, "max": 51}),
                "preset": (["veryfast", "fast", "medium", "slow"],),
            },
        }

    @staticmethod
    def _encode_video(ffmpeg, frames, width, height, fps, pix_fmt_in, preset, crf, output_path):
        args = [
            ffmpeg, "-y", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", pix_fmt_in,
            "-s", f"{width}x{height}", "-r", str(fps), "-i", "-",
            "-an", "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", output_path,
        ]
        proc = subprocess.Popen(
            args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        try:
            for frame in frames:
                proc.stdin.write(frame.tobytes())
            proc.stdin.close()
            stderr = proc.stderr.read()
            ret = proc.wait()
            if ret != 0:
                raise RuntimeError(f"ffmpeg video encode failed (code {ret}): {stderr.decode('utf-8', errors='replace')}")
        except Exception:
            proc.kill()
            raise

    @staticmethod
    def _write_audio_pcm(audio, path):
        waveform = audio.get("waveform") if isinstance(audio, dict) else None
        if not isinstance(waveform, torch.Tensor):
            raise ValueError("audio has no waveform tensor")
        sample_rate = int(audio.get("sample_rate", 44100))
        if waveform.ndim == 3:
            waveform = waveform[0]
        if waveform.ndim != 2:
            raise ValueError(f"unexpected waveform ndim: {waveform.ndim}")
        channels = int(waveform.shape[0])
        pcm = waveform.detach().to(device="cpu", dtype=torch.float32).clamp(-1.0, 1.0)
        pcm = pcm.transpose(0, 1).contiguous().numpy()
        with open(path, "wb") as f:
            f.write(pcm.tobytes())
        return channels, sample_rate

    def save_video(self, images, fps, filename_prefix, crf=18, preset="veryfast", audio=None):
        if not isinstance(images, torch.Tensor):
            raise ValueError("images must be IMAGE tensor")

        frames = (images.clamp(0, 1) * 255).round().to(torch.uint8).cpu().numpy()
        if frames.ndim == 3:
            frames = frames[None, ...]

        batch, height, width, channels = frames.shape
        if channels == 3:
            pix_fmt_in = "rgb24"
        elif channels == 4:
            pix_fmt_in = "rgba"
        else:
            raise ValueError(f"unsupported channels: {channels}")

        if folder_paths:
            output_dir = folder_paths.get_output_directory()
            full_folder, name, counter, subfolder, _prefix = folder_paths.get_save_image_path(
                filename_prefix, output_dir, width, height
            )
        else:
            output_dir = "output"
            os.makedirs(output_dir, exist_ok=True)
            full_folder = output_dir
            name = filename_prefix
            counter = 0
            subfolder = ""

        os.makedirs(full_folder, exist_ok=True)
        file = f"{name}_{counter:05}_.mp4"
        output_path = os.path.join(full_folder, file)

        ffmpeg = _ffmpeg_path()
        has_audio = audio is not None and isinstance(audio, dict) and audio.get("waveform") is not None

        if has_audio:
            temp_dir = tempfile.mkdtemp(prefix="qibo_video_")
            video_tmp = os.path.join(temp_dir, "video.mp4")
            audio_tmp = os.path.join(temp_dir, "audio.f32le")
            try:
                self._encode_video(ffmpeg, frames, width, height, fps, pix_fmt_in, preset, crf, video_tmp)
                audio_channels, audio_sr = self._write_audio_pcm(audio, audio_tmp)
                duration = batch / float(fps)
                mux_args = [
                    ffmpeg, "-y", "-loglevel", "error",
                    "-i", video_tmp,
                    "-f", "f32le", "-ar", str(audio_sr), "-ac", str(audio_channels),
                    "-i", audio_tmp,
                    "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "copy", "-c:a", "aac",
                    "-t", f"{duration:.6f}",
                    "-movflags", "+faststart", output_path,
                ]
                mux = subprocess.run(mux_args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                if mux.returncode != 0:
                    raise RuntimeError(f"ffmpeg mux failed: {mux.stderr.decode('utf-8', errors='replace')}")
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)
        else:
            self._encode_video(ffmpeg, frames, width, height, fps, pix_fmt_in, preset, crf, output_path)

        saved_rel = os.path.join(subfolder, file) if subfolder else file
        audio_tag = " +audio" if has_audio else ""
        print(f"[QIBO] video saved: output/{saved_rel}  ({batch} frames, {width}x{height}, {fps} fps{audio_tag})")

        ui = {
            "images": [{
                "filename": file,
                "subfolder": subfolder,
                "type": "output",
            }],
            "animated": (True,),
        }
        return {"ui": ui, "result": (saved_rel,)}


_RIFE_CKPT_DIR = os.path.join(
    folder_paths.models_dir if folder_paths else os.path.join(os.path.dirname(__file__), "..", "..", "models"),
    "frame_interpolation",
)
os.makedirs(_RIFE_CKPT_DIR, exist_ok=True)

_RIFE_CKPT_VER = {
    "rife47.pth": "4.7",
    "rife49.pth": "4.7",
    "rife417.pth": "4.17",
    "rife426.pth": "4.26",
    "sudo_rife4_269.662_testV1_scale1.pth": "4.0",
}

_RIFE_BASE_URLS = [
    "https://github.com/styler00dollar/VSGAN-tensorrt-docker/releases/download/models/",
    "https://github.com/Fannovel16/ComfyUI-Frame-Interpolation/releases/download/models/",
    "https://github.com/dajes/frame-interpolation-pytorch/releases/download/v1.0.0/",
]

_RIFE_FALLBACK_URLS = {
    "rife47.pth": [
        "https://huggingface.co/marduk191/rife/resolve/main/rife47.pth",
        "https://huggingface.co/wavespeed/misc/resolve/main/rife/rife47.pth",
        "https://huggingface.co/MachineDelusions/RIFE/resolve/main/rife47.pth",
        "https://huggingface.co/jasonot/mycomfyui/resolve/main/rife47.pth",
    ],
    "rife49.pth": [
        "https://huggingface.co/marduk191/rife/resolve/main/rife49.pth",
        "https://huggingface.co/hfmaster/models-moved/resolve/main/rife/rife49.pth",
        "https://huggingface.co/MachineDelusions/RIFE/resolve/main/rife49.pth",
        "https://huggingface.co/Isi99999/Frame_Interpolation_Models/resolve/main/rife49.pth",
    ],
    "sudo_rife4_269.662_testV1_scale1.pth": [
        "https://huggingface.co/marduk191/rife/resolve/main/sudo_rife4_269.662_testV1_scale1.pth",
        "https://huggingface.co/uwg/upscaler/resolve/main/ESRGAN/sudo_rife4_269.662_testV1_scale1.pth",
        "https://huggingface.co/licyk/sd-upscaler-models/resolve/main/ESRGAN/sudo_rife4_269.662_testV1_scale1.pth",
    ],
}

_rife_model_cache: typing.Dict[typing.Tuple, torch.nn.Module] = {}


def _rife_download_ckpt(ckpt_name):
    dest = os.path.join(_RIFE_CKPT_DIR, ckpt_name)
    if os.path.exists(dest):
        return dest
    all_urls = [base + ckpt_name for base in _RIFE_BASE_URLS]
    all_urls += _RIFE_FALLBACK_URLS.get(ckpt_name, [])
    errors = []
    for raw_url in all_urls:
        try:
            from qibo_modelscope import _download_direct, _to_hf_mirror
            url = _to_hf_mirror(raw_url)
            print(f"[QIBO-RIFE] 下载 {ckpt_name} from {url}")
            _download_direct(url, dest)
            print(f"[QIBO-RIFE] 下载完成: {dest} ({os.path.getsize(dest)} bytes)")
            return dest
        except Exception as e:
            errors.append(f"{raw_url}: {e}")
            if os.path.exists(dest):
                os.remove(dest)
    raise RuntimeError(f"下载 {ckpt_name} 失败:\n" + "\n".join(errors))


def _rife_load_model(ckpt_name, dtype_str="float32"):
    dtype_map = {"float32": torch.float32, "float16": torch.float16, "bfloat16": torch.bfloat16}
    torch_dtype = dtype_map.get(dtype_str, torch.float32)
    cache_key = (ckpt_name, dtype_str)
    if cache_key in _rife_model_cache:
        return _rife_model_cache[cache_key], _RIFE_CKPT_VER[ckpt_name]

    try:
        from .qibo_rife_arch import IFNet
    except ImportError:
        from qibo_rife_arch import IFNet
    model_path = _rife_download_ckpt(ckpt_name)
    arch_ver = _RIFE_CKPT_VER[ckpt_name]
    model = IFNet(arch_ver=arch_ver)
    state = torch.load(model_path, weights_only=False, map_location="cpu")
    model.load_state_dict(state)
    if torch_dtype != torch.float32:
        model = model.to(torch_dtype)
    device = get_torch_device()
    model.eval().to(device)
    _rife_model_cache[cache_key] = model
    print(f"[QIBO-RIFE] 模型已加载: {ckpt_name} (arch {arch_ver}, {dtype_str})")
    return model, arch_ver


class QIBOFrameInterpolationNode:
    """RIFE 视频插帧节点。接收 IMAGE batch，在每两帧之间插入中间帧。"""

    @classmethod
    def INPUT_TYPES(cls):
        ckpts = sorted(_RIFE_CKPT_VER.keys())
        return {
            "required": {
                "frames": ("IMAGE",),
                "ckpt_name": (ckpts, {"default": "rife49.pth"}),
                "multiplier": ("INT", {"default": 2, "min": 1, "max": 10}),
                "fast_mode": ("BOOLEAN", {"default": True}),
                "ensemble": ("BOOLEAN", {"default": True}),
                "scale_factor": ([0.25, 0.5, 1.0, 2.0, 4.0], {"default": 1.0}),
                "dtype": (["float32", "float16", "bfloat16"], {"default": "float32"}),
                "clear_cache_after_n_frames": ("INT", {"default": 10, "min": 1, "max": 1000}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("frames",)
    FUNCTION = "interpolate"
    CATEGORY = "QIBO_API"
    OUTPUT_NODE = True

    def interpolate(
        self,
        frames: torch.Tensor,
        ckpt_name: str = "rife49.pth",
        multiplier: int = 2,
        fast_mode: bool = True,
        ensemble: bool = True,
        scale_factor: float = 1.0,
        dtype: str = "float32",
        clear_cache_after_n_frames: int = 10,
    ):
        if frames.shape[0] < 2:
            return (frames,)

        dtype_map = {"float32": torch.float32, "float16": torch.float16, "bfloat16": torch.bfloat16}
        torch_dtype = dtype_map.get(dtype, torch.float32)
        device = get_torch_device()

        model, arch_ver = _rife_load_model(ckpt_name, dtype)
        if arch_ver == "4.26":
            ensemble = False

        frames_nchw = einops.rearrange(frames[..., :3], "n h w c -> n c h w")
        n_pairs = len(frames_nchw) - 1

        if arch_ver == "4.26":
            scale_list = [16 / scale_factor, 8 / scale_factor, 4 / scale_factor, 2 / scale_factor, 1 / scale_factor]
        else:
            scale_list = [8 / scale_factor, 4 / scale_factor, 2 / scale_factor, 1 / scale_factor]

        results: typing.Dict[int, typing.List[torch.Tensor]] = {i: [] for i in range(n_pairs)}
        tasks = []
        for pair_idx in range(n_pairs):
            for step in range(1, multiplier):
                tasks.append((pair_idx, step / multiplier))

        frames_processed = 0
        with torch.inference_mode():
            for pair_idx, dt in tasks:
                frame0 = frames_nchw[pair_idx:pair_idx + 1].to(device, dtype=torch_dtype)
                frame1 = frames_nchw[pair_idx + 1:pair_idx + 2].to(device, dtype=torch_dtype)
                timestep = torch.tensor([dt], dtype=torch_dtype, device=device).view(-1, 1, 1, 1)

                mid = model(frame0, frame1, timestep, scale_list, fast_mode, ensemble)
                mid = mid.clamp(0, 1).detach().cpu().to(torch_dtype)
                results[pair_idx].append(mid)

                frames_processed += 1
                if frames_processed >= clear_cache_after_n_frames:
                    soft_empty_cache()
                    gc.collect()
                    frames_processed = 0

        output_frames = []
        for pair_idx in range(n_pairs):
            output_frames.append(frames_nchw[pair_idx:pair_idx + 1].to(torch_dtype))
            for mid in results[pair_idx]:
                output_frames.append(mid)
        output_frames.append(frames_nchw[-1:].to(torch_dtype))

        soft_empty_cache()
        out = torch.cat(output_frames, dim=0).to(torch.float32)
        total = out.shape[0]
        print(f"[QIBO-RIFE] 插帧完成: {frames.shape[0]} 帧 -> {total} 帧 (multiplier={multiplier})")
        return (einops.rearrange(out, "n c h w -> n h w c")[..., :3].cpu(),)


NODE_CLASS_MAPPINGS = {
    "QIBOSaveVideoNode": QIBOSaveVideoNode,
    "QIBOFrameInterpolationNode": QIBOFrameInterpolationNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBOSaveVideoNode": "QIBO 保存视频 (Image to MP4)",
    "QIBOFrameInterpolationNode": "QIBO 视频插帧 (RIFE)",
}