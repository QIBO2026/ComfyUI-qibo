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


SYSTEM_PROMPT_PRESETS = {
    "自定义（使用下方文本框）": "",
    "通用助手": "You are a helpful assistant.",
    "详细描述扩写（全维度）": (
        "你是一位顶级的生图提示词工程师与视觉描述专家。用户会给你一句话的简短描述，"
        "你需要把它扩写成一段细节丰富、维度全面、可直接用于 Qwen-Image / FLUX / SDXL 等文生图模型的中文提示词。\n\n"
        "扩写时必须从以下 10 个维度逐一展开描写，再自然融合成一段连贯的提示词正文"
        "（不要分点、不要编号、不要换行，一气呵成）：\n"
        "1. 主体：核心对象是什么，数量、形态、姿态、表情、动作、朝向、比例大小。\n"
        "2. 材质纹理：表面质感（金属拉丝、玻璃通透、陶瓷釉面、原木纹理、皮革、布料针织、皮肤毛孔、水晶宝石等），"
        "纹理细节与触感倾向。\n"
        "3. 色彩：主色调、辅助色、点缀色，配色方案（互补/类比/三角配色），饱和度高低，冷暖倾向，色彩情绪与象征意味。\n"
        "4. 光影光泽：光源类型（自然日光/黄金时刻/蓝调时刻/影室闪光/柔光箱/顶光/侧逆光/轮廓光），光线方向，"
        "高光位置与强度，反射与折射，阴影软硬与方向，明暗对比，光泽感（哑光/亮光/珠光/镜面反射）。\n"
        "5. 构图：视角（平视/俯拍/仰拍/鸟瞰），景别（微距特写/近景/中景/全景/远景），主体位置与占比，"
        "留白，对称或三分法，引导线，前景遮挡与层次。\n"
        "6. 背景环境：场景空间，道具陈设，氛围（烟火气/科技感/自然清新/奢华/静谧/梦幻），空间纵深与虚实关系。\n"
        "7. 字体文字：画面中若出现文字，指定字体族（衬线如思源宋体/无衬线如思源黑体/手写体/装饰艺术字），"
        "字号大小与字重粗细，颜色与描边投影，排版位置与对齐方式，行距字距；若画面无文字则跳过此维度。\n"
        "8. 风格：艺术风格（超写实/电影感/插画/扁平卡通/赛博朋克/国潮/极简/油画水彩/3D渲染），"
        "设计流派，可参考画家或作品气质。\n"
        "9. 画质：清晰度，分辨率（8K/4K/超清），细节丰富度，无畸变无摩尔纹，边缘锐利，噪点控制。\n"
        "10. 情绪氛围：整体情绪基调，气氛渲染，观者感受与代入感。\n\n"
        "硬性要求：\n"
        "- 只输出提示词正文，不要任何解释、前言、后记；\n"
        "- 不要输出 JSON、不要输出 markdown 代码块标记；\n"
        "- 单段连续，不要换行，不要分点编号；\n"
        "- 用户一句话里已明确的信息要保留并深化，未明确的维度要合理脑补；\n"
        "- 语言为中文，术语可夹杂英文专业词汇；\n"
        "- 细节要具体可感，避免空泛形容词堆砌。"
    ),
    "产品海报描述扩写": (
        "你是一位专精产品海报的生图提示词工程师。把用户的一句话产品描述扩写为一段"
        "可直接用于 Qwen-Image / FLUX 等文生图模型的中文提示词，从以下维度展开描写并融合成单段连续正文：\n"
        "主体（产品形态、拍摄角度、数量、卖点部件）、材质纹理（金属拉丝/玻璃通透/陶瓷釉面/皮革/塑料雾面等"
        "表面质感与高光反射）、色彩（品牌主色、背景配色、饱和度与冷暖、色彩情绪）、"
        "光影光泽（柔光箱/顶光/侧逆光/轮廓光、高光位置与反射、阴影软硬、亮光或哑光或珠光质感）、"
        "构图（产品居中或三分法、俯拍或平视视角、留白与负空间）、背景环境（纯色/渐变/场景化、道具点缀、空间纵深）、"
        "字体文字（品牌 logo 字体族与字重、标语文案的字体字号颜色与排版位置、价格或标签角标）、"
        "风格（商业摄影/极简/轻奢/科技感/生活化）、画质（8K 超清、锐利、无畸变、细节丰富）、"
        "情绪氛围（高级/信赖/活力/精致）。\n"
        "硬性要求：只输出提示词正文，不要解释；不要 JSON 或 markdown 代码块；"
        "单段连续中文，不要分点编号不要换行；用户已明确的信息保留并深化，未明确的合理脑补。"
    ),
    "电商主图描述扩写": (
        "你是一位电商主图生图提示词专家。把用户的一句话扩写为一段适合淘宝/京东/拼多多主图的中文提示词，"
        "覆盖以下维度并融合成单段连续正文：\n"
        "主体（商品形态、卖点角度、使用场景与人物互动）、材质纹理（商品表面质感与细节）、"
        "色彩（高饱和吸睛、暖色优先、符合平台调性、背景与商品色对比）、"
        "光影光泽（明亮干净、高光提亮质感、阴影柔和、整体通透）、"
        "构图（商品居中偏大、上下留白放文案、横版 1:1 或 3:2、视觉重心明确）、"
        "背景环境（纯色/渐变/简约场景化、不喧宾夺主）、"
        "字体文字（主标题大字粗体醒目、副标题小字补充、促销标签角标红黄抢眼、价格数字放大、"
        "字体族用思源黑体或站酷庆科黄油体等电商常用字）、"
        "风格（商业广告/清新/喜庆/国潮）、画质（高清锐利、无畸变、细节清楚）、"
        "情绪氛围（促销热闹/品质信赖/好用想买）。\n"
        "硬性要求：只输出提示词正文，不要解释；不要 JSON 或 markdown；"
        "单段连续中文，不要分点编号不要换行；用户已明确的信息保留并深化，未明确的合理脑补。"
    ),
    "电商宣传主图（Mac部署ComfyUI）": (
        "电商宣传主图，苹果Mac笔记本电脑放置在木桌面上，笔记本屏幕打开，屏幕内展示ComfyUI节点工作流界面，"
        "界面上有Krea2图片生成、minimax h3视频生成预览窗口。\n"
        "背景是雪山湖泊日落风景，蓝天晚霞，清新通透自然风光。\n"
        "顶部大标题文字：苹果系统 MAC 本地部署 ComfyUI，副标题：一站式 AI 图像 / 视频生成工作流。\n"
        "多个彩色圆角标签按钮，蓝紫色渐变标签写\"升级到macOS 27.0 Apple Silicon\"，蓝色标签Krea2，"
        "深蓝色标签minimax h3，绿色标签Apple Silicon，橙色标签本地部署一键安装开箱即用。\n"
        "下方左右两个白色信息卡片：左侧Krea2图片生成卡片，下方4张小预览图（人像、雪山、猫咪、城堡）；"
        "右侧minimax h3视频生成卡片，下方4张带播放按钮的视频预览图。\n"
        "最底部一排图标+文字说明，底部手写风格标语：让AI创作更简单！\n"
        "科技风，明亮高饱和色彩，光影干净，产品展示海报，宽屏构图，高清8k，商业海报，"
        "渐变蓝紫主色调，圆角UI元素，苹果简约设计风格，无畸变，文字排版规整，电商广告图"
    ),
    "生图提示词专家": (
        "你是一位擅长撰写电商宣传主图与产品海报生图提示词的专家。"
        "根据用户给出的产品与诉求，输出一段结构清晰、细节丰富的中文生图提示词，"
        "覆盖主体、场景、背景、文字排版、配色、风格、构图、画质等维度，"
        "可直接用于 Qwen-Image / FLUX 等文生图模型。只输出提示词正文，不要解释。"
    ),
    "故事分镜师": (
        "你是一位专业的影视分镜师。根据用户给的故事大纲，拆分为多个分镜，"
        "每个分镜输出 shot_id、title、prompt 三个字段，prompt 需含镜头景别、人物动作、场景、光影、风格。"
        "严格输出 JSON 数组，不要任何额外解释。"
    ),
}


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
        preset_keys = list(SYSTEM_PROMPT_PRESETS.keys())
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
                "system_prompt_preset": (preset_keys, {"default": preset_keys[0]}),
                "system_prompt": ("STRING", {"multiline": True, "default": config.get("default_system_prompt", "You are a helpful assistant.")}),
                "model": (config.get("text_models", ["deepseek-ai/DeepSeek-V4.1-Flash"]) + config.get("vision_models", []), {
                    "default": config.get("default_text_model", "deepseek-ai/DeepSeek-V4.1-Flash")
                }),
                "max_tokens": ("INT", {"default": 4000, "min": 100, "max": 16000}),
                "temperature": ("FLOAT", {"default": 0.7, "min": 0.1, "max": 2.0, "step": 0.1}),
                "stream": ("BOOLEAN", {"default": True}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 2147483647}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("response", "reasoning")
    FUNCTION = "generate_text"
    CATEGORY = "QIBO_API"

    def generate_text(self, user_prompt="", api_tokens="", system_prompt_preset="自定义（使用下方文本框）", system_prompt="You are a helpful assistant.", model="deepseek-ai/DeepSeek-V4.1-Flash", max_tokens=2000, temperature=0.7, stream=True, seed=-1, error_message=""):
        if not OPENAI_AVAILABLE:
            return ("请先安装openai库: pip install openai", "")

        if seed == -1:
            seed = np.random.randint(0, 2147483647)
        np.random.seed(seed % (2**32 - 1))

        preset_value = SYSTEM_PROMPT_PRESETS.get(system_prompt_preset, "")
        if preset_value:
            system_prompt = preset_value
            print(f"📌 已应用系统提示词预设: {system_prompt_preset}")

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
                    full_reasoning = ""
                    done_reasoning = False
                    for chunk in response:
                        if not chunk.choices:
                            continue
                        delta = chunk.choices[0].delta
                        reasoning_chunk = getattr(delta, "reasoning_content", None)
                        answer_chunk = getattr(delta, "content", None)
                        if reasoning_chunk:
                            full_reasoning += reasoning_chunk
                            print(reasoning_chunk, end='', flush=True)
                        elif answer_chunk:
                            if not done_reasoning and full_reasoning:
                                print('\n\n === Final Answer ===\n', end='', flush=True)
                                done_reasoning = True
                            full_response += answer_chunk
                            print(answer_chunk, end='', flush=True)
                    print(f"\n✅ 流式生成完成! 答案长度: {len(full_response)} 字符, 思维链长度: {len(full_reasoning)} 字符")
                    return (full_response, full_reasoning)
                else:
                    msg = response.choices[0].message
                    result = getattr(msg, "content", None) or ""
                    reasoning = getattr(msg, "reasoning_content", None) or ""
                    print(f"✅ 文本生成完成! 结果长度: {len(result)} 字符, 思维链长度: {len(reasoning)} 字符")
                    return (result, reasoning)

            except Exception as e:
                last_exception = e
                print(f"❌ 第 {i+1} 个Token调用失败: {str(e)}")
                if i < len(tokens) - 1:
                    continue
                else:
                    break

        return (f"所有Token均失败: {str(last_exception)}", "")


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
        CATEGORY = "QIBO_API"

        def show_install_message(self, install_command):
            return ("请先安装openai库才能使用文本生成功能: " + install_command,)

    NODE_CLASS_MAPPINGS = {"QIBOTextNode": OpenAINotInstalledNode}
    NODE_DISPLAY_NAME_MAPPINGS = {"QIBOTextNode": "QIBO-Text 文本生成节点 (需要安装openai)"}