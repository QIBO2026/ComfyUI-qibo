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
            "OpenGVLab/InternVL3_5-241B-A28B",
            "PaddlePaddle/ERNIE-4.5-VL-28B-A3B-PT"
        ])
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
                "prompt1": ("STRING", {"multiline": True, "default": "详细描述这张图片的内容，包括主体、背景、颜色、风格等信息"}),
                "prompt2": ("STRING", {"multiline": True, "default": ""}),
                "model": (supported_models, {"default": supported_models[0] if supported_models else "OpenGVLab/InternVL3_5-241B-A28B"}),
                "max_tokens": ("INT", {"default": 1000, "min": 100, "max": 4000}),
                "temperature": ("FLOAT", {"default": 0.7, "min": 0.1, "max": 2.0, "step": 0.1}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 2147483647})
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("description",)
    FUNCTION = "generate_caption"
    CATEGORY = "ModelScopeAPI"

    def create_blank_image(self, width=64, height=64):
        blank_np = np.ones((height, width, 3), dtype=np.uint8) * 255
        blank_tensor = torch.from_numpy(blank_np).unsqueeze(0).float() / 255.0
        return blank_tensor

    def generate_caption(self, image=None, api_tokens="", prompt1="详细描述这张图片的内容", prompt2="", model="OpenGVLab/InternVL3_5-241B-A28B", max_tokens=1000, temperature=0.7, seed=-1):
        if not OPENAI_AVAILABLE:
            return ("请先安装openai库: pip install openai",)

        if seed == -1:
            seed = np.random.randint(0, 2147483647)
        np.random.seed(seed % (2**32 - 1))

        if image is None:
            print("⚠️ 未输入图像，自动生成空白图像作为输入")
            image = self.create_blank_image()

        prompt_parts = []
        if prompt1.strip(): prompt_parts.append(prompt1.strip())
        if prompt2.strip(): prompt_parts.append(prompt2.strip())
        prompt = ", ".join(prompt_parts) if prompt_parts else "详细描述这张图片的内容，包括主体、背景、颜色、风格等信息"

        tokens = parse_api_tokens(api_tokens)
        if not tokens:
            raise Exception("请提供至少一个有效的API Token\n提示: 使用 ModelScope登录获取Token 节点自动获取Token")

        if api_tokens.strip() not in ["", f"***已保存{len(load_api_tokens())}个Token***"]:
            if save_api_tokens(tokens):
                print(f"✅ 已保存 {len(tokens)} 个API Token")

        print(f"🔍 开始生成图像描述... 模型: {model} 种子: {seed}")

        image_url = tensor_to_base64_url(image)
        print(f"🖼️ 图像已转换为base64格式")

        messages = [{
            'role': 'user',
            'content': [{'type': 'text', 'text': prompt}, {'type': 'image_url', 'image_url': {'url': image_url}}],
        }]

        last_exception = None
        for i, token in enumerate(tokens):
            try:
                print(f"🔄 尝试使用第 {i+1}/{len(tokens)} 个Token...")
                client = OpenAI(base_url='https://api-inference.modelscope.cn/v1', api_key=token)
                response = client.chat.completions.create(
                    model=model, messages=messages, max_tokens=max_tokens, temperature=temperature, stream=False
                )
                description = response.choices[0].message.content
                print(f"✅ 第 {i+1} 个Token调用成功! 结果预览: {description[:100]}...")
                return (description,)
            except Exception as e:
                last_exception = e
                print(f"❌ 第 {i+1} 个Token调用失败: {str(e)}")
                if i < len(tokens) - 1:
                    print(f"⏳ 准备尝试下一个Token...")

        return (f"所有Token均失败: {str(last_exception)}",)


NODE_CLASS_MAPPINGS = {"QIBOImageCaptionNode": ModelScopeImageCaptionNode}
NODE_DISPLAY_NAME_MAPPINGS = {"QIBOImageCaptionNode": "QIBO 图像描述生成"}