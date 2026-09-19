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
    print("⚠️ 警告: 未安装openai库，图生文功能将不可用")
    print("请运行: pip install openai")
    OPENAI_AVAILABLE = False
    OpenAI = None

from .qibo_auth import (
    load_config, save_config,
    load_api_tokens, save_api_tokens,
    parse_api_tokens
)
from .qibo_image_node import tensor_to_base64_url


class ModelScopeVisionNode:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(cls):
        if not OPENAI_AVAILABLE:
            return {"required": {"error_message": ("STRING", {"default": "请先安装openai库: pip install openai", "multiline": True})}}
        config = load_config()
        saved_tokens = load_api_tokens()
        return {
            "required": {
                "image": ("IMAGE",),
                "prompt": ("STRING", {"multiline": True, "default": config.get("default_prompt", "描述这幅图")}),
                "api_tokens": ("STRING", {
                    "default": "***已保存{}个Token***".format(len(saved_tokens)) if saved_tokens else "",
                    "placeholder": "请输入API Token（支持多个，用逗号/换行分隔）" if not saved_tokens else "留空使用已保存的Token",
                    "multiline": True
                }),
            },
            "optional": {
                "model": (config.get("vision_models", ["stepfun-ai/step3"]), {"default": "stepfun-ai/step3"}),
                "max_tokens": ("INT", {"default": 1000, "min": 100, "max": 4000}),
                "temperature": ("FLOAT", {"default": 0.7, "min": 0.1, "max": 2.0, "step": 0.1}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("description",)
    FUNCTION = "analyze_image"
    CATEGORY = "ModelScopeAPI"

    def analyze_image(self, image=None, prompt="", api_tokens="", model="stepfun-ai/step3", max_tokens=1000, temperature=0.7, error_message=""):
        if not OPENAI_AVAILABLE:
            return ("请先安装openai库: pip install openai",)

        tokens = parse_api_tokens(api_tokens)
        if not tokens:
            raise Exception("请提供至少一个有效的API Token\n提示: 使用 ModelScope登录获取Token 节点自动获取Token")

        if api_tokens and api_tokens.strip() not in ["", "***已保存{}个Token***".format(len(load_api_tokens()))]:
            if save_api_tokens(tokens):
                print(f"✅ 已保存 {len(tokens)} 个API Token")

        print(f"🔍 开始分析图像... 模型: {model}")

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
                    continue
                else:
                    break

        return (f"所有Token均失败: {str(last_exception)}",)


if OPENAI_AVAILABLE:
    NODE_CLASS_MAPPINGS = {"QIBOVisionNode": ModelScopeVisionNode}
    NODE_DISPLAY_NAME_MAPPINGS = {"QIBOVisionNode": "QIBO-Vision 图生文节点"}
else:
    class OpenAINotInstalledNode:
        @classmethod
        def INPUT_TYPES(cls):
            return {"required": {"install_command": ("STRING", {"default": "pip install openai", "multiline": False})}}

        RETURN_TYPES = ("STRING",)
        RETURN_NAMES = ("message",)
        FUNCTION = "show_install_message"
        CATEGORY = "ModelScopeAPI"

        def show_install_message(self, install_command):
            return ("请先安装openai库才能使用图生文功能: " + install_command,)

    NODE_CLASS_MAPPINGS = {"QIBOVisionNode": OpenAINotInstalledNode}
    NODE_DISPLAY_NAME_MAPPINGS = {"QIBOVisionNode": "QIBO-Vision 图生文节点 (需要安装openai)"}