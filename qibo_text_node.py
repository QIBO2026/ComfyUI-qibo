import json
import time
import os
import numpy as np

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    print("⚠️ 警告: 未安装openai库，文本生成功能将不可用")
    print("请运行: pip install openai")
    OPENAI_AVAILABLE = False
    OpenAI = None

from .qibo_auth import (
    load_config, save_config,
    load_api_tokens, save_api_tokens,
    parse_api_tokens
)


class ModelScopeTextNode:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(cls):
        if not OPENAI_AVAILABLE:
            return {
                "required": {
                    "error_message": ("STRING", {"default": "请先安装openai库: pip install openai", "multiline": True}),
                }
            }
        config = load_config()
        saved_tokens = load_api_tokens()
        return {
            "required": {
                "user_prompt": ("STRING", {"multiline": True, "default": config.get("default_user_prompt", "你好")}),
                "api_tokens": ("STRING", {
                    "default": "***已保存{}个Token***".format(len(saved_tokens)) if saved_tokens else "",
                    "placeholder": "请输入API Token（支持多个，用逗号/换行分隔）" if not saved_tokens else "留空使用已保存的Token",
                    "multiline": True
                }),
            },
            "optional": {
                "system_prompt": ("STRING", {"multiline": True, "default": config.get("default_system_prompt", "You are a helpful assistant.")}),
                "model": (config.get("text_models", ["Qwen/Qwen3-Coder-480B-A35B-Instruct"]) + config.get("vision_models", []), {
                    "default": config.get("default_text_model", "Qwen/Qwen3-Coder-480B-A35B-Instruct")
                }),
                "max_tokens": ("INT", {"default": 2000, "min": 100, "max": 8000}),
                "temperature": ("FLOAT", {"default": 0.7, "min": 0.1, "max": 2.0, "step": 0.1}),
                "stream": ("BOOLEAN", {"default": True}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 2147483647}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("response",)
    FUNCTION = "generate_text"
    CATEGORY = "ModelScopeAPI"

    def generate_text(self, user_prompt="", api_tokens="", system_prompt="You are a helpful assistant.", model="Qwen/Qwen3-Coder-480B-A35B-Instruct", max_tokens=2000, temperature=0.7, stream=True, seed=-1, error_message=""):
        if not OPENAI_AVAILABLE:
            return ("请先安装openai库: pip install openai",)

        if seed == -1:
            seed = np.random.randint(0, 2147483647)
        np.random.seed(seed % (2**32 - 1))

        tokens = parse_api_tokens(api_tokens)
        if not tokens:
            raise Exception("请提供至少一个有效的API Token\n提示: 使用 ModelScope登录获取Token 节点自动获取Token")

        if api_tokens and api_tokens.strip() not in ["", "***已保存{}个Token***".format(len(load_api_tokens()))]:
            if save_api_tokens(tokens):
                print(f"✅ 已保存 {len(tokens)} 个API Token")

        print(f"💬 开始文本生成... 模型: {model} 温度: {temperature} 种子: {seed}")

        last_exception = None
        for i, token in enumerate(tokens):
            try:
                print(f"🔄 尝试使用第 {i+1}/{len(tokens)} 个Token...")

                client = OpenAI(base_url='https://api-inference.modelscope.cn/v1', api_key=token)

                messages = [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_prompt}
                ]

                response = client.chat.completions.create(
                    model=model, messages=messages, max_tokens=max_tokens, temperature=temperature, stream=stream
                )

                if stream:
                    print("📡 接收流式响应...")
                    full_response = ""
                    for chunk in response:
                        if chunk.choices[0].delta.content:
                            content = chunk.choices[0].delta.content
                            full_response += content
                            print(content, end='', flush=True)
                    print(f"\n✅ 流式生成完成! 总长度: {len(full_response)} 字符")
                    return (full_response,)
                else:
                    result = response.choices[0].message.content
                    print(f"✅ 文本生成完成! 结果长度: {len(result)} 字符")
                    return (result,)

            except Exception as e:
                last_exception = e
                print(f"❌ 第 {i+1} 个Token调用失败: {str(e)}")
                if i < len(tokens) - 1:
                    continue
                else:
                    break

        return (f"所有Token均失败: {str(last_exception)}",)


if OPENAI_AVAILABLE:
    NODE_CLASS_MAPPINGS = {"QIBOTextNode": ModelScopeTextNode}
    NODE_DISPLAY_NAME_MAPPINGS = {"QIBOTextNode": "QIBO-Text 文本生成节点"}
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
            return ("请先安装openai库才能使用文本生成功能: " + install_command,)

    NODE_CLASS_MAPPINGS = {"QIBOTextNode": OpenAINotInstalledNode}
    NODE_DISPLAY_NAME_MAPPINGS = {"QIBOTextNode": "QIBO-Text 文本生成节点 (需要安装openai)"}