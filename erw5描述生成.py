# -*- coding: utf-8 -*-
"""
循环读取 D:\\视频\\comy\\mac苹果\\erw5_split 里的图片，按 BATCH_SIZE 张一批
批量提交 ModelScope Qwen3.8-Flash-Next 视觉接口（一次请求上传多张图，
模型一次返回 JSON 数组，每个元素对应一张图的描述），逐张追加保存到
图像描述_erw5.json（支持中断续跑，已处理的图自动跳过）。

参考 qibo_image_caption_node.py 的多图上传推理流程：把多张图各自转成
data:image/...;base64,... 数据 URL，一起放进 messages content 的 image_url
列表，一次 chat.completions.create 调用完成批量推理。

运行：
    python erw5描述生成.py
"""

import base64
import json
import os
import re
import sys
import time

from openai import OpenAI

try:
    from qibo_auth import load_api_tokens
    QIBO_AUTH_AVAILABLE = True
except ImportError:
    QIBO_AUTH_AVAILABLE = False

# ================== 配置 ==================
IMAGE_DIR = r"D:\视频\comy\mac苹果\erw5_split"
OUTPUT_JSON = r"D:\视频\comy\mac苹果\图像描述_erw5.json"
MODEL = "Qwen/Qwen3.8-Flash-Next"
# ModelScope Token：留空则自动从 qibo_auth 读取 ComfyUI 里已保存的 token；
# 支持多个 token 用逗号/换行分隔，会逐个尝试直到成功
API_TOKENS = ""
RETRY_TIMES = 3        # 单批失败重试次数
RETRY_WAIT = 5         # 重试等待秒数
START_ID = 1           # 输出条目的起始 id
IS_STYLE_SOURCE = False  # 第一张是否作为风格源，可改 True
BATCH_SIZE = 3         # 一次批量推理的图片数量（Qwen 视觉模型多图上限 10，过大易掉描述）

# 统一配色与光效说明（写入每条的 color 槽位，与长卷其他页保持一致）
UNIFIED_COLOR = (
    "作为整幅未来AI科技长卷的组成区域，保持统一未来AI空间背景。"
    "采用明亮的浅蓝紫渐变、银白金属、通透科技色调，背景偏亮偏通透，不要深色不要暗黑。"
    "背景连接中央AI核心数据流，包含全息投影、玻璃材质、悬浮UI、柔和体积光、霓虹光晕，"
    "画面元素边缘带蓝青霓虹轮廓光，整体科技感强、明亮通透。"
    "所有页面切割后必须像同一部科幻电影中的连续镜头，"
    "保持统一光源方向、统一材质、统一色彩体系、统一空间结构。"
)

SYSTEM_PROMPT = """你是一名专业的海报/图像结构分析师。用户会按顺序给你 N 张图片，请对每一张图片分别详细描述它的：
1. 整体结构组成（从上到下/从左到右按区域拆解，每个区域里的元素、图标、卡片、按钮等）；
2. 字体（标题/正文的字体风格、颜色、渐变、描边、字号大小对比、排版方式，并抄录图中出现的所有文字）；
3. 光影（光源方向、发光元素、光晕、阴影、虚化等）；
4. 背景（背景类型、颜色、纹理、装饰元素）。

必须严格按照下面的 JSON 格式输出，只输出一个 JSON 数组，不要输出任何其他文字、解释或 markdown 代码块标记：
[
  {
    "id": 1,
    "title": "给这张图起一个简短的中文标题（概括主题）",
    "slots": {
      "structure": [
        "一句话概括这张图的整体类型、主色调和构图（例如：这是一张XX宣传海报，整体采用XX风格，布局为XX）"
      ],
      "body": [
        "一、顶部标题区\\n（详细描述）",
        "二、中部XX区\\n（详细描述）",
        "三、……"
      ],
      "color": [
        "统一配色与光效说明（本区域如何延续蓝紫渐变科技长卷的统一风格）"
      ]
    },
    "is_style_source": false
  },
  { "id": 2, ... },
  { "id": 3, ... }
]

要求：
- 输出数组长度必须等于用户输入的图片数量 N，顺序与输入图片顺序一一对应；
- body 数组按区域分条，每条以「一、二、三、」等中文序号开头，条数根据图实际区域数定（一般 4~8 条）；
- 每条描述要足够详细具体（颜色、形状、图标、文字内容全部写出来），供后续文生图复现使用；
- 用户的 color 槽位内容由系统给定，你只需在 color 中写一段说明本区域与统一蓝紫科技长卷风格的衔接。
"""

MODELSCOPE_BASE_URL = "https://api-inference.modelscope.cn/v1"


def natural_key(name: str):
    """按数字自然排序，保证 r1c1 -> r1c2 -> ... -> r2c3 顺序"""
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]


def list_images():
    exts = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
    files = [f for f in os.listdir(IMAGE_DIR) if f.lower().endswith(exts)]
    files.sort(key=natural_key)
    return [os.path.join(IMAGE_DIR, f) for f in files]


def image_to_data_url(path: str) -> str:
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    if ext == "jpg":
        ext = "jpeg"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:image/{ext};base64,{b64}"


def load_output():
    """读取已有输出，返回 (条目列表, 已处理文件名集合)"""
    items, done = [], set()
    if os.path.exists(OUTPUT_JSON):
        try:
            with open(OUTPUT_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            for it in data:
                items.append(it)
                if it.get("_file"):
                    done.add(it["_file"])
        except Exception as e:
            print(f"[警告] 已有输出文件解析失败，将重新开始：{e}")
    return items, done


def save_output(items):
    # 保留 _file 方便续跑识别，最终导出时再批量删除该字段
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def strip_internal(items):
    """导出时去掉 _file 内部字段，输出干净的统一格式"""
    clean = []
    for it in items:
        c = {k: v for k, v in it.items() if k != "_file"}
        clean.append(c)
    return clean


def extract_json_array(text: str):
    """从模型输出中提取 JSON 数组（容忍 ```json 代码块、前后杂文字）。
    批大小为 1 时模型可能仍输出单对象，此时包装成单元素数组返回。"""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.S)
    if m:
        text = m.group(1)
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start:end + 1])
    s2, e2 = text.find("{"), text.rfind("}")
    if s2 != -1 and e2 != -1 and e2 > s2:
        return [json.loads(text[s2:e2 + 1])]
    raise ValueError("输出中未找到 JSON 数组或对象")


def describe_batch(paths, tokens):
    """一次把多张图一起上传并完成推理，返回模型输出的 JSON 数组
    （每个元素描述对应位置的图片）。参考 qibo_image_caption_node.py 的
    多图 content 构造 + 多 token 轮询：text 在前，多张 image_url 依次追加，
    token 逐个尝试直到成功。"""
    content = [
        {
            "type": "text",
            "text": (
                f"下面按顺序给出 {len(paths)} 张图片，请对每张图分别按系统要求的 "
                f"JSON 格式输出，最终输出一个长度为 {len(paths)} 的 JSON 数组，"
                f"数组第 i 个元素描述第 i 张图。"
            ),
        }
    ]
    for p in paths:
        content.append({
            "type": "image_url",
            "image_url": {"url": image_to_data_url(p)},
        })
    print(f"  🖼️ {len(paths)} 张图已转 base64，开始流式推理...", flush=True)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]
    last_exc = None
    for i, token in enumerate(tokens):
        try:
            print(f"  🔄 尝试第 {i+1}/{len(tokens)} 个 Token（{token[:12]}...）...")
            client = OpenAI(base_url=MODELSCOPE_BASE_URL, api_key=token)
            response = client.chat.completions.create(
                model=MODEL, messages=messages, stream=True,
            )
            text = ""
            print("  📝 流式输出: ", end="", flush=True)
            for chunk in response:
                if chunk.choices:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        text += delta.content
                        print(delta.content, end="", flush=True)
            print()
            return extract_json_array(text)
        except Exception as e:
            last_exc = e
            print(f"  ❌ 第 {i+1} 个 Token 失败: {type(e).__name__}: {e}")
    raise last_exc


def normalize_entry(entry: dict, idx: int, filename: str) -> dict:
    """补齐/规范字段，保证和 图像描述_统一风格.json 单条格式一致"""
    slots = entry.get("slots", {})
    return {
        "id": idx,
        "title": entry.get("title") or os.path.splitext(filename)[0],
        "slots": {
            "structure": slots.get("structure") or [],
            "body": slots.get("body") or [],
            "color": [UNIFIED_COLOR],
        },
        "is_style_source": IS_STYLE_SOURCE if idx == START_ID else False,
        "_file": filename,
    }


def export_final(items):
    final_path = OUTPUT_JSON.replace(".json", "_final.json")
    with open(final_path, "w", encoding="utf-8") as f:
        json.dump(strip_internal(items), f, ensure_ascii=False, indent=2)
    print(f"\n全部完成！共 {len(items)} 条")
    print(f"过程文件（含 _file 字段，支持续跑）：{OUTPUT_JSON}")
    print(f"最终干净格式：{final_path}")


def resolve_tokens():
    """优先用脚本顶部 API_TOKENS，留空则从 qibo_auth 读已保存的 token"""
    if API_TOKENS.strip():
        tokens = [t.strip() for t in re.split(r"[,;\n]+", API_TOKENS) if t.strip()]
    elif QIBO_AUTH_AVAILABLE:
        tokens = load_api_tokens()
    else:
        tokens = []
    if not tokens:
        print("[错误] 没有可用的 ModelScope Token。")
        print("  方式1: 在脚本顶部设置 API_TOKENS（多个用逗号分隔）")
        print("  方式2: 在 ComfyUI 里用 QIBO 登录节点保存 token 后再运行本脚本")
        sys.exit(1)
    return tokens


def main():
    tokens = resolve_tokens()
    print(f"🔑 已加载 {len(tokens)} 个 ModelScope Token\n")

    images = list_images()
    if not images:
        print(f"[错误] {IMAGE_DIR} 里没有图片")
        sys.exit(1)

    items, done = load_output()
    print(f"共 {len(images)} 张图片，已完成 {len(done)} 张，本次开始批量处理...\n")

    pending = [p for p in images if os.path.basename(p) not in done]
    if not pending:
        print("全部已处理，无需重复推理。")
        export_final(items)
        return

    idx = START_ID + len(items)
    total_batches = (len(pending) + BATCH_SIZE - 1) // BATCH_SIZE
    for bi in range(total_batches):
        batch = pending[bi * BATCH_SIZE:(bi + 1) * BATCH_SIZE]
        batch_names = [os.path.basename(p) for p in batch]
        print(f"=== 批 {bi + 1}/{total_batches}  共 {len(batch)} 张：{batch_names} ===")

        ok = False
        for attempt in range(1, RETRY_TIMES + 1):
            try:
                print(f"  第 {attempt} 次请求中...")
                entries = describe_batch(batch, tokens)
                if len(entries) != len(batch):
                    raise ValueError(
                        f"模型返回 {len(entries)} 条，期望 {len(batch)} 条，数量不一致"
                    )
                for j, entry in enumerate(entries):
                    item = normalize_entry(entry, idx, batch_names[j])
                    items.append(item)
                    idx += 1
                    print(f"  [完成] id={item['id']} title={item['title']}")
                save_output(items)
                ok = True
                break
            except json.JSONDecodeError as e:
                print(f"  [失败] JSON 解析错误：{e}")
            except Exception as e:
                print(f"  [失败] {type(e).__name__}: {e}")
            if attempt < RETRY_TIMES:
                time.sleep(RETRY_WAIT)

        if not ok:
            print(f"  [放弃] 本批重试 {RETRY_TIMES} 次仍失败，继续下一批")
        print()

    export_final(items)


if __name__ == "__main__":
    main()
