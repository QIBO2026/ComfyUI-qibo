import requests
import json
import time
import torch
import numpy as np
from PIL import Image
from io import BytesIO
import os
import base64
import re

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


def _format_token_header(usage, text, label=""):
    if usage is not None:
        prompt_t = getattr(usage, "prompt_tokens", None) or 0
        completion_t = getattr(usage, "completion_tokens", None) or 0
        total_t = getattr(usage, "total_tokens", None) or (prompt_t + completion_t)
    else:
        char_count = len(text)
        cn_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        en_count = char_count - cn_count
        prompt_t = 0
        completion_t = int(cn_count * 1.5 + en_count * 0.25)
        total_t = completion_t
    prefix = f"[{label} Token] " if label else "[Token] "
    return f"{prefix}输入:{prompt_t} 输出:{completion_t} 总计:{total_t}\n\n"

from .qibo_auth import (
    load_config, save_config,
    load_api_tokens, save_api_tokens,
    parse_api_tokens
)
from .qibo_image_node import tensor_to_base64_url


class ModelScopeImageCaptionNode:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(cls):
        if not OPENAI_AVAILABLE:
            return {"required": {"error_message": ("STRING", {"default": "请先安装openai库: pip install openai", "multiline": True})}}
        saved_tokens = load_api_tokens()
        config = load_config()
        supported_models = config.get("caption_models", [
            "Qwen/Qwen3.8-Flash-Next",
            "OpenGVLab/InternVL3_5-241B-A28B",
            "PaddlePaddle/ERNIE-4.5-VL-28B-A3B-PT"
        ])
        text_models = config.get("text_models", ["deepseek-ai/DeepSeek-V4.1-Flash"])
        default_polish_system = (
            "你是一位生图提示词专家。把用户给出的图片描述改写成一段适合 Qwen-Image 文生图模型使用的中文提示词，"
            "要求：1) 保留原描述中的主体、场景、风格、细节；2) 补充画面构图、光影、色调、画质等关键词；"
            "3) 输出纯提示词正文，不要解释、不要分点、不要 JSON。"
        )
        return {
            "required": {
                "api_tokens": ("STRING", {
                    "default": f"***已保存{len(saved_tokens)}个Token***" if saved_tokens else "",
                    "placeholder": "请输入API Token（支持多个，用逗号/换行分隔）",
                    "multiline": True
                }),
            },
            "optional": {
                "image": ("IMAGE", {"optional": True}),
                "image2": ("IMAGE", {"optional": True}),
                "image3": ("IMAGE", {"optional": True}),
                "image4": ("IMAGE", {"optional": True}),
                "image5": ("IMAGE", {"optional": True}),
                "image6": ("IMAGE", {"optional": True}),
                "image7": ("IMAGE", {"optional": True}),
                "image8": ("IMAGE", {"optional": True}),
                "image9": ("IMAGE", {"optional": True}),
                "image10": ("IMAGE", {"optional": True}),
                "prompt1": ("STRING", {"multiline": True, "default": "描述这幅图"}),
                "prompt2": ("STRING", {"multiline": True, "default": ""}),
                "model": (supported_models, {"default": supported_models[0] if supported_models else "Qwen/Qwen3.8-Flash-Next"}),
                "max_tokens": ("INT", {"default": 1000, "min": 100, "max": 4000}),
                "temperature": ("FLOAT", {"default": 0.7, "min": 0.1, "max": 2.0, "step": 0.1}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 2147483647}),
                "enable_polish": ("BOOLEAN", {"default": False}),
                "polish_model": (text_models, {"default": text_models[0] if text_models else "deepseek-ai/DeepSeek-V4.1-Flash"}),
                "polish_system_prompt": ("STRING", {"multiline": True, "default": default_polish_system}),
                "polish_max_tokens": ("INT", {"default": 2000, "min": 100, "max": 8000}),
                "polish_temperature": ("FLOAT", {"default": 0.7, "min": 0.1, "max": 2.0, "step": 0.1}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("description", "polished_prompt")
    FUNCTION = "generate_caption"
    CATEGORY = "QIBO_API"

    def create_blank_image(self, width=64, height=64):
        blank_np = np.ones((height, width, 3), dtype=np.uint8) * 255
        blank_tensor = torch.from_numpy(blank_np).unsqueeze(0).float() / 255.0
        return blank_tensor

    def generate_caption(self, image=None, image2=None, image3=None, image4=None, image5=None, image6=None, image7=None, image8=None, image9=None, image10=None, api_tokens="", prompt1="描述这幅图", prompt2="", model="Qwen/Qwen3.8-Flash-Next", max_tokens=1000, temperature=0.7, seed=-1, enable_polish=False, polish_model="deepseek-ai/DeepSeek-V4.1-Flash", polish_system_prompt="", polish_max_tokens=2000, polish_temperature=0.7):
        if not OPENAI_AVAILABLE:
            return ("请先安装openai库: pip install openai", "")

        if seed == -1:
            seed = np.random.randint(0, 2147483647)
        np.random.seed(seed % (2**32 - 1))

        all_images = [img for img in [image, image2, image3, image4, image5, image6, image7, image8, image9, image10] if img is not None]
        if not all_images:
            print("⚠️ 未输入任何图像，自动生成空白图像作为输入")
            all_images = [self.create_blank_image()]

        prompt_parts = []
        if prompt1.strip(): prompt_parts.append(prompt1.strip())
        if prompt2.strip(): prompt_parts.append(prompt2.strip())
        prompt = ", ".join(prompt_parts) if prompt_parts else "描述这幅图"

        tokens = parse_api_tokens(api_tokens)
        if not tokens:
            raise Exception("请提供至少一个有效的API Token\n提示: 使用 ModelScope登录获取Token 节点自动获取Token")

        if api_tokens.strip() not in ["", f"***已保存{len(load_api_tokens())}个Token***"]:
            if save_api_tokens(tokens):
                print(f"✅ 已保存 {len(tokens)} 个API Token")

        print(f"🔍 开始生成图像描述... 模型: {model} 种子: {seed} 图片数: {len(all_images)}")

        content = [{'type': 'text', 'text': prompt}]
        for idx, img in enumerate(all_images):
            url = tensor_to_base64_url(img)
            content.append({'type': 'image_url', 'image_url': {'url': url}})
        print(f"🖼️ {len(all_images)} 张图像已转换为base64格式")
        messages = [{'role': 'user', 'content': content}]

        last_exception = None
        description = None
        caption_usage = None
        for i, token in enumerate(tokens):
            try:
                print(f"🔄 尝试使用第 {i+1}/{len(tokens)} 个Token...")
                client = OpenAI(base_url='https://api-inference.modelscope.cn/v1', api_key=token)
                response = client.chat.completions.create(
                    model=model, messages=messages, max_tokens=max_tokens, temperature=temperature, stream=True,
                    stream_options={"include_usage": True},
                )
                description_parts = []
                print("📝 流式输出: ", end="", flush=True)
                for chunk in response:
                    if chunk.choices:
                        delta = chunk.choices[0].delta
                        content = getattr(delta, "content", None)
                        if content:
                            description_parts.append(content)
                            print(content, end="", flush=True)
                    chunk_usage = getattr(chunk, "usage", None)
                    if chunk_usage is not None:
                        caption_usage = chunk_usage
                print()
                description = "".join(description_parts)
                print(f"\n✅ 第 {i+1} 个Token调用成功! 结果预览: {description[:100]}...")
                break
            except Exception as e:
                last_exception = e
                print(f"❌ 第 {i+1} 个Token调用失败: {str(e)}")
                if i < len(tokens) - 1:
                    print(f"⏳ 准备尝试下一个Token...")

        if description is None:
            return (f"所有Token均失败: {str(last_exception)}", "")

        token_header = _format_token_header(caption_usage, description, "反推")

        if not enable_polish:
            return (token_header + description, "")

        polished = self._polish_prompt(
            description, tokens, polish_model, polish_system_prompt,
            polish_max_tokens, polish_temperature
        )
        return (token_header + description, polished)

    def _polish_prompt(self, description, tokens, polish_model, polish_system_prompt, max_tokens, temperature):
        if not description.strip():
            print("⚠️ 反推描述为空，跳过润色")
            return ""
        system_prompt = polish_system_prompt.strip() or (
            "你是一位生图提示词专家。把用户给出的图片描述改写成一段适合 Qwen-Image 文生图模型使用的中文提示词，"
            "要求：1) 保留原描述中的主体、场景、风格、细节；2) 补充画面构图、光影、色调、画质等关键词；"
            "3) 输出纯提示词正文，不要解释、不要分点、不要 JSON。"
        )
        print(f"✨ 开始润色提示词... 模型: {polish_model}")
        messages = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': description},
        ]
        last_exception = None
        for i, token in enumerate(tokens):
            try:
                print(f"🔄 润色: 尝试使用第 {i+1}/{len(tokens)} 个Token...")
                client = OpenAI(base_url='https://api-inference.modelscope.cn/v1', api_key=token)
                response = client.chat.completions.create(
                    model=polish_model, messages=messages, max_tokens=max_tokens,
                    temperature=temperature, stream=True
                )
                parts = []
                print("📝 润色输出: ", end="", flush=True)
                for chunk in response:
                    if chunk.choices:
                        delta = chunk.choices[0].delta
                        content = getattr(delta, "content", None)
                        if content:
                            parts.append(content)
                            print(content, end="", flush=True)
                print()
                result = "".join(parts).strip()
                print(f"\n✅ 润色完成! 结果预览: {result[:100]}...")
                return result
            except Exception as e:
                last_exception = e
                print(f"❌ 润色第 {i+1} 个Token失败: {str(e)}")
                if i < len(tokens) - 1:
                    print(f"⏳ 准备尝试下一个Token...")
        print(f"⚠️ 润色全部失败: {str(last_exception)}")
        return ""


NODE_CLASS_MAPPINGS = {"QIBOImageCaptionNode": ModelScopeImageCaptionNode}
NODE_DISPLAY_NAME_MAPPINGS = {"QIBOImageCaptionNode": "QIBO 图像描述生成"}