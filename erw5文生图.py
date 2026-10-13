# -*- coding: utf-8 -*-
"""
读取 erw5描述生成.py 产出的 图像描述_erw5_final.json，按 id 升序排序后，
逐条把 slots 描述拼接成提示词，调用魔塔（ModelScope）文生图 API
（Qwen/Qwen-Image-2.1）生成图片，保存到 erw5_gen 目录。
支持中断续跑（已生成的图自动跳过）。

复用 qibo_image_node.py 的魔塔文生图调用流程：
  POST /v1/images/generations (异步) → 轮询 /v1/tasks/{task_id} → 下载图片

运行：
    python erw5文生图.py
"""

import json
import os
import random
import re
import sys
import time

import requests

try:
    from qibo_auth import load_api_tokens, get_api_endpoint
    QIBO_AVAILABLE = True
except ImportError:
    QIBO_AVAILABLE = False

# ================== 配置 ==================
INPUT_JSON = r"D:\视频\comy\mac苹果\图像描述_erw5_final.json"
OUTPUT_DIR = r"D:\视频\comy\mac苹果\erw5_gen"

MODEL = "Qwen/Qwen-Image-2.1"
# 1280×1920 = 64*20 × 64*30，严格 2:3 竖向，约 2.46MP，均在魔塔 [64,2048] 限制内
GEN_WIDTH = 1280
GEN_HEIGHT = 1920
STEPS = 25
GUIDANCE = 1.0     # Qwen-Image-2.1 Flow Matching，cfg=1（对齐远程不乱码基准）
NEGATIVE_PROMPT = ""

# 背景调整后缀：覆盖 JSON 里偏深的 color 描述，强调明亮通透科技感（不用重新描述即可生效）
BACKGROUND_SUFFIX = (
    "\n\n背景要求：采用明亮的浅蓝紫渐变背景，通透科技感强，"
    "带全息投影光效、蓝青霓虹光晕、悬浮玻璃质感、柔和体积光；"
    "背景色调偏亮偏通透，禁止深色暗黑背景，保持未来科技空间的明亮通透感。"
)

RETRY_TIMES = 2        # 单条失败重试次数
POLL_INTERVAL = 5      # 轮询间隔秒
MAX_WAIT = 900         # 单条最大等待秒
LOG_EVERY = 30         # 进度日志间隔秒


def extract_desc_from_obj(obj: dict) -> str:
    """从 JSON 提示词对象提取描述：slots 里 structure/body/color 顺序拼接，
    无 slots 时回退 content > title。"""
    slots = obj.get("slots")
    if isinstance(slots, dict):
        parts = []
        for key in ("structure", "body", "color"):
            v = slots.get(key)
            if isinstance(v, list):
                parts.extend(str(s).strip() for s in v if str(s).strip())
            elif isinstance(v, str) and v.strip():
                parts.append(v.strip())
        if parts:
            return "\n\n".join(parts)
    for key in ("content", "prompt"):
        v = str(obj.get(key, "")).strip()
        if v:
            return v
    return str(obj.get("title", "")).strip()


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name).strip()
    return name[:60] or "untitled"


def load_entries():
    if not os.path.exists(INPUT_JSON):
        print(f"[错误] 描述文件不存在：{INPUT_JSON}")
        print("  请先运行 erw5描述生成.py 生成描述")
        sys.exit(1)
    with open(INPUT_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    entries = sorted(data, key=lambda x: x.get("id", 0))
    print(f"📖 已加载 {len(entries)} 条描述（来自 {INPUT_JSON}）")
    return entries


def generate_one(prompt: str, token: str) -> bytes:
    """调魔塔文生图 API 生成单张图，返回图片字节。
    参考 qibo_image_node.py:660-755 的 submit→poll→download 流程。"""
    submit_url = get_api_endpoint('image_generation', 'submit_url')
    task_query_url = get_api_endpoint('image_generation', 'task_query_url')

    payload = {
        'model': MODEL,
        'prompt': prompt,
        'size': f"{GEN_WIDTH}x{GEN_HEIGHT}",
        'steps': STEPS,
        'guidance': GUIDANCE,
        'seed': random.randint(0, 2147483647),
    }
    if NEGATIVE_PROMPT.strip():
        payload['negative_prompt'] = NEGATIVE_PROMPT

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'X-ModelScope-Async-Mode': 'true',
        'X-ModelScope-Task-Type': 'text-to-image-generation',
    }

    resp = requests.post(submit_url, json=payload, headers=headers, timeout=60)
    # 标准参数失败时回退简化参数（参考 qibo_image_node.py:695-702）
    if resp.status_code in (400, 422):
        minimal = {'model': MODEL, 'prompt': prompt, 'size': f"{GEN_WIDTH}x{GEN_HEIGHT}"}
        resp = requests.post(submit_url, json=minimal, headers=headers, timeout=60)
    if resp.status_code != 200:
        raise Exception(f"提交失败: {resp.status_code} {resp.text[:500]}")

    data = resp.json()
    task_id = data.get('task_id')
    if not task_id:
        # 同步返回
        imgs = data.get('images') or []
        if imgs:
            url = imgs[0].get('url') if isinstance(imgs[0], dict) else imgs[0]
            return requests.get(url, timeout=120).content
        raise Exception(f"未识别返回: {json.dumps(data, ensure_ascii=False)[:300]}")

    print(f"  📌 任务ID: {task_id}，轮询中...")
    poll_headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'X-ModelScope-Task-Type': 'image_generation',
    }
    start = time.time()
    last_log = 0
    while time.time() - start < MAX_WAIT:
        time.sleep(POLL_INTERVAL)
        r = requests.get(
            task_query_url.replace('{task_id}', task_id),
            headers=poll_headers, timeout=30,
        )
        if r.status_code != 200:
            continue
        td = r.json()
        status = td.get('task_status')
        if status == 'SUCCEED':
            urls = td.get('output_images') or []
            if not urls:
                raise Exception("任务成功但无图片URL")
            return requests.get(urls[0], timeout=120).content
        if status == 'FAILED':
            raise Exception(f"任务失败: {json.dumps(td, ensure_ascii=False)[:300]}")
        elapsed = int(time.time() - start)
        if elapsed - last_log >= LOG_EVERY:
            print(f"  ⌛ 状态: {status} ({elapsed}s)", flush=True)
            last_log = elapsed
    raise Exception(f"轮询超时 ({MAX_WAIT}s)")


def main():
    if not QIBO_AVAILABLE:
        print("[错误] 需在 ComfyUI-qibo 目录下运行，以便导入 qibo_auth")
        sys.exit(1)

    tokens = load_api_tokens()
    if not tokens:
        print("[错误] 无可用 ModelScope Token")
        print("  请先在 ComfyUI 用 QIBO 登录节点保存 Token，或运行 erw5描述生成.py 触发保存")
        sys.exit(1)

    print(f"🔑 已加载 {len(tokens)} 个 ModelScope Token")
    print(f"🎨 模型: {MODEL}  尺寸: {GEN_WIDTH}×{GEN_HEIGHT} (2:3 竖向)\n")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    entries = load_entries()

    success, failed, skipped = 0, 0, 0
    for entry in entries:
        eid = entry.get("id")
        title = entry.get("title") or f"id{eid}"
        fname = f"{eid:02d}_{sanitize_filename(title)}.png"
        out_path = os.path.join(OUTPUT_DIR, fname)
        if os.path.exists(out_path):
            print(f"[跳过] id={eid} {title}（已存在）")
            skipped += 1
            continue

        prompt = extract_desc_from_obj(entry)
        if not prompt.strip():
            print(f"[跳过] id={eid} 描述为空")
            continue
        prompt = prompt + BACKGROUND_SUFFIX

        print(f"\n=== id={eid}  {title} ===")
        print(f"  提示词预览: {prompt[:80].replace(chr(10), ' ')}...")

        ok = False
        for attempt in range(1, RETRY_TIMES + 1):
            for ti, token in enumerate(tokens):
                try:
                    print(f"  第 {attempt} 次提交（Token {ti+1}/{len(tokens)}）...")
                    content = generate_one(prompt, token)
                    with open(out_path, "wb") as f:
                        f.write(content)
                    print(f"  [完成] 保存: {out_path}")
                    ok = True
                    success += 1
                    break
                except Exception as e:
                    print(f"  [失败] {type(e).__name__}: {e}")
            if ok:
                break
            if attempt < RETRY_TIMES:
                time.sleep(3)
        if not ok:
            failed += 1
            print(f"  [放弃] id={eid}")

    print(f"\n全部结束。成功 {success}，跳过 {skipped}，失败 {failed}")
    print(f"输出目录: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()