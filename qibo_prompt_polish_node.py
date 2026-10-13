import os
import re
import json
import numpy as np

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    OpenAI = None

from .qibo_auth import (
    load_config,
    load_api_tokens,
    save_api_tokens,
    parse_api_tokens,
)


DEFAULT_SKILL_DIR = r"C:\Users\Administrator\Desktop\qwen-image-2.1-skill-main\skills\qwen-image-2-1-prompter"

ASPECT_RATIOS = ["自适应", "3:2", "2:3", "1:1", "16:9", "9:16", "4:3", "3:4", "2:1", "21:9", "1:2", "5:4", "4:5"]

MODES = ["文生图 (T2I)", "图像编辑 (Edit)"]

SAMPLE_SEPARATOR = "==="


def _read_text_safe(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"⚠️ 读取文件失败 {path}: {e}")
        return ""


def _strip_frontmatter(text):
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            return text[end + 3:].lstrip("\n")
    return text


def _load_skill_rules(skill_dir, mode):
    if not os.path.isdir(skill_dir):
        return ""
    skill_md = _read_text_safe(os.path.join(skill_dir, "SKILL.md"))
    skill_md = _strip_frontmatter(skill_md)
    refs_dir = os.path.join(skill_dir, "references")
    if mode.startswith("文生图") or "T2I" in mode:
        rules_md = _read_text_safe(os.path.join(refs_dir, "t2i_rules.md"))
    else:
        rules_md = _read_text_safe(os.path.join(refs_dir, "edit_rules.md"))
    cheat_md = _read_text_safe(os.path.join(refs_dir, "cheat_sheet.md"))
    parts = []
    if skill_md.strip():
        parts.append("=== 技能总纲 (SKILL.md) ===\n" + skill_md.strip())
    if rules_md.strip():
        parts.append("=== 详细规则 ===\n" + rules_md.strip())
    if cheat_md.strip():
        parts.append("=== 词汇速查表 ===\n" + cheat_md.strip())
    return "\n\n".join(parts)


def _split_samples(text):
    if not text or not text.strip():
        return []
    chunks = re.split(r"(?m)^\s*===+\s*$", text)
    samples = []
    for ch in chunks:
        ch = ch.strip()
        if ch:
            samples.append(ch)
    return samples


def _load_reference_file(path):
    if not path or not path.strip():
        return []
    path = path.strip().strip('"').strip("'")
    if not os.path.isfile(path):
        print(f"⚠️ 参考样本文件不存在: {path}")
        return []
    ext = os.path.splitext(path)[1].lower()
    content = _read_text_safe(path)
    if not content.strip():
        return []
    if ext == ".json":
        try:
            data = json.loads(content)
            if isinstance(data, list):
                return [str(x).strip() for x in data if str(x).strip()]
            if isinstance(data, dict):
                for key in ("samples", "prompts", "reference_prompts", "data"):
                    if key in data and isinstance(data[key], list):
                        return [str(x).strip() for x in data[key] if str(x).strip()]
        except Exception as e:
            print(f"⚠️ JSON 解析失败，按文本分隔处理: {e}")
    return _split_samples(content)


def _build_system_prompt(skill_rules, mode, wh_ratio):
    parts = []
    if skill_rules.strip():
        parts.append(skill_rules.strip())
    parts.append(
        "\n\n=== 本次任务指令 ===\n"
        "你是一位专精于 Qwen-Image-2.1 的提示词工程师。请严格遵循上述技能总纲与详细规则，"
        "把用户给出的简短意图润色为一段高质量、可直接用于生图模型的最终提示词。\n"
        "硬性要求：\n"
        "1) 严格遵循规则中的语言约定、结构要求、词汇规范；\n"
        "2) 不要输出任何解释、分点说明、前后缀语，只输出提示词正文；\n"
        "3) 不要输出 JSON 包装，不要输出 markdown 代码块标记；\n"
        "4) 若用户提供了参考样本，请模仿其风格、细节密度与结构，但不要照抄；\n"
        "5) 提示词正文一气呵成，单段连续，不要换行。"
    )
    if wh_ratio and wh_ratio != "自适应":
        parts.append(f"\n6) 目标宽高比为 {wh_ratio}，但不要把比例或像素数写进提示词正文。")
    mode_hint = "文生图（T2I）" if mode.startswith("文生图") or "T2I" in mode else "图像编辑（Edit）"
    parts.append(f"\n当前任务模式：{mode_hint}。")
    return "\n".join(parts)


def _build_user_prompt(user_intent, samples, wh_ratio, image_description=""):
    blocks = []
    if image_description and image_description.strip():
        blocks.append("=== 图片反推描述（请将其作为重要参考素材融入最终提示词） ===")
        blocks.append(image_description.strip())
        blocks.append("")
    if samples:
        blocks.append("以下是一组高质量提示词样本，请参考其风格、结构、细节密度与词汇用法：")
        for i, s in enumerate(samples, 1):
            blocks.append(f"\n【样本 {i}】\n{s}")
        blocks.append("\n\n=== 请基于上述样本风格，润色下方用户意图 ===")
    blocks.append(f"\n用户意图：{user_intent.strip()}")
    if wh_ratio and wh_ratio != "自适应":
        blocks.append(f"\n目标宽高比：{wh_ratio}")
    blocks.append("\n请输出最终提示词正文：")
    return "\n".join(blocks)


def _extract_prompt(raw):
    if not raw:
        return ""
    text = raw.strip()
    fence_match = re.search(r"```(?:\w+)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if json_match:
        try:
            obj = json.loads(json_match.group(0))
            for key in ("rewritten_prompt", "prompt", "description", "result"):
                if key in obj and isinstance(obj[key], str) and obj[key].strip():
                    return obj[key].strip()
        except Exception:
            pass
    text = re.sub(r"^#{1,6}\s*.*$", "", text, flags=re.MULTILINE).strip()
    text = re.sub(r"^\s*(📋\s*提示词|提示词[：:].*|可直接复制.*)$", "", text, flags=re.MULTILINE).strip()
    return text


class QIBOPromptPolishNode:
    """提示词融合节点（第二步）。

    纯文本输入输出，不依赖图片。接收可选的图片反推描述（来自 QIBOImageCaptionNode
    或其他反推节点的输出），结合用户意图、参考样本、skill 规则，融合出最终提示词。
    """

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
        text_models = config.get("text_models", ["deepseek-ai/DeepSeek-V4.1-Flash"])
        default_model = config.get("default_text_model", text_models[0] if text_models else "deepseek-ai/DeepSeek-V4.1-Flash")
        return {
            "required": {
                "user_intent": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "输入你想要的效果（简短描述即可，例如：雪山日落下的苹果笔记本海报）",
                }),
                "api_tokens": ("STRING", {
                    "default": f"***已保存{len(saved_tokens)}个Token***" if saved_tokens else "",
                    "placeholder": "请输入API Token（支持多个，用逗号/换行分隔）",
                    "multiline": True,
                }),
            },
            "optional": {
                "image_description": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "可选：连接图片反推节点的 description 输出，作为参考素材融入融合",
                    "tooltip": "来自第一步图片反推的描述文本，与用户意图、参考样本一起融合",
                }),
                "reference_prompts": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": f"粘贴参考提示词样本，多个样本用 {SAMPLE_SEPARATOR} 分隔",
                }),
                "reference_file": ("STRING", {
                    "default": "",
                    "placeholder": "参考样本文件路径（.txt 用 === 分隔，或 .json 数组）",
                }),
                "skill_dir": ("STRING", {"default": DEFAULT_SKILL_DIR}),
                "enable_skill": ("BOOLEAN", {"default": True, "tooltip": "关闭后不加载 skill 目录规则，仅用内置默认指令融合"}),
                "mode": (MODES, {"default": MODES[0]}),
                "wh_ratio": (ASPECT_RATIOS, {"default": "自适应"}),
                "model": (text_models, {"default": default_model}),
                "max_tokens": ("INT", {"default": 4000, "min": 100, "max": 16000}),
                "temperature": ("FLOAT", {"default": 0.7, "min": 0.1, "max": 2.0, "step": 0.1}),
                "stream": ("BOOLEAN", {"default": True}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 2147483647}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("polished_prompt", "raw_response")
    FUNCTION = "polish_prompt"
    CATEGORY = "QIBO_API"

    def polish_prompt(
        self,
        user_intent="",
        api_tokens="",
        image_description="",
        reference_prompts="",
        reference_file="",
        skill_dir=DEFAULT_SKILL_DIR,
        enable_skill=True,
        mode=MODES[0],
        wh_ratio="自适应",
        model="deepseek-ai/DeepSeek-V4.1-Flash",
        max_tokens=4000,
        temperature=0.7,
        stream=True,
        seed=-1,
        error_message="",
    ):
        if not OPENAI_AVAILABLE:
            return ("请先安装openai库: pip install openai", "")

        if not user_intent or not user_intent.strip():
            raise Exception("请输入用户意图（user_intent）")

        if seed == -1:
            seed = np.random.randint(0, 2147483647)
        np.random.seed(seed % (2**32 - 1))

        tokens = parse_api_tokens(api_tokens)
        if not tokens:
            raise Exception("请提供至少一个有效的API Token\n提示: 使用 ModelScope登录获取Token 节点自动获取Token")

        if api_tokens and api_tokens.strip() not in ["", f"***已保存{len(load_api_tokens())}个Token***"]:
            if save_api_tokens(tokens):
                print(f"✅ 已保存 {len(tokens)} 个API Token")

        if image_description and image_description.strip():
            print(f"👁️ 收到图片反推描述 ({len(image_description)} 字符): {image_description[:150]}...")

        inline_samples = _split_samples(reference_prompts)
        file_samples = _load_reference_file(reference_file)
        samples = inline_samples + file_samples
        print(f"📚 参考样本: 文本框 {len(inline_samples)} 条 + 文件 {len(file_samples)} 条 = {len(samples)} 条")

        skill_rules = ""
        if enable_skill:
            skill_rules = _load_skill_rules(skill_dir, mode)
            if not skill_rules.strip():
                print(f"⚠️ 未从技能目录加载到规则: {skill_dir}，将仅用默认指令")
            else:
                print(f"✅ 已加载技能规则 ({len(skill_rules)} 字符): {skill_dir}")
        else:
            print("⏭️ 已关闭 skill 参考，仅用内置默认指令融合")

        system_prompt = _build_system_prompt(skill_rules, mode, wh_ratio)
        user_prompt = _build_user_prompt(user_intent, samples, wh_ratio, image_description)

        print(f"✨ 开始提示词融合... 模型: {model} 模式: {mode} 宽高比: {wh_ratio} 种子: {seed}")

        last_exception = None
        for i, token in enumerate(tokens):
            try:
                print(f"🔄 尝试使用第 {i+1}/{len(tokens)} 个Token...")
                client = OpenAI(base_url="https://api-inference.modelscope.cn/v1", api_key=token)
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]
                response = client.chat.completions.create(
                    model=model, messages=messages, max_tokens=max_tokens,
                    temperature=temperature, stream=stream,
                )
                if stream:
                    full_response = ""
                    print("📝 流式输出: ", end="", flush=True)
                    for chunk in response:
                        if not chunk.choices:
                            continue
                        delta = chunk.choices[0].delta
                        content = getattr(delta, "content", None)
                        if content:
                            full_response += content
                            print(content, end="", flush=True)
                    print()
                else:
                    msg = response.choices[0].message
                    full_response = getattr(msg, "content", None) or ""

                full_response = full_response.strip()
                polished = _extract_prompt(full_response)
                if not polished:
                    polished = full_response
                print(f"\n✅ 融合完成! 提示词长度: {len(polished)} 字符")
                print(f"📋 预览: {polished[:200]}...")
                return (polished, full_response)
            except Exception as e:
                last_exception = e
                print(f"❌ 第 {i+1} 个Token调用失败: {str(e)}")
                if i < len(tokens) - 1:
                    continue
                break

        return (f"所有Token均失败: {str(last_exception)}", "")


if OPENAI_AVAILABLE:
    NODE_CLASS_MAPPINGS = {"QIBOPromptPolishNode": QIBOPromptPolishNode}
    NODE_DISPLAY_NAME_MAPPINGS = {"QIBOPromptPolishNode": "QIBO 提示词融合"}
else:
    class OpenAINotInstalledNode:
        @classmethod
        def INPUT_TYPES(cls):
            return {"required": {"install_command": ("STRING", {"default": "pip install openai", "multiline": False})}}

        RETURN_TYPES = ("STRING", "STRING")
        RETURN_NAMES = ("polished_prompt", "raw_response")
        FUNCTION = "show_install_message"
        CATEGORY = "QIBO_API"

        def show_install_message(self, install_command):
            return ("请先安装openai库: " + install_command, "")

    NODE_CLASS_MAPPINGS = {"QIBOPromptPolishNode": OpenAINotInstalledNode}
    NODE_DISPLAY_NAME_MAPPINGS = {"QIBOPromptPolishNode": "QIBO 提示词融合 (需要安装openai)"}
