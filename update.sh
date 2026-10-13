#!/bin/bash
# ComfyUI-QIBO 一键更新
echo "============================================"
echo "  ComfyUI-QIBO 一键更新"
echo "============================================"
echo ""

echo "[1/2] git pull 拉取最新代码..."
git pull || { echo ""; echo "❌ git pull 失败！请检查网络或 git 是否安装"; exit 1; }

echo ""
echo "[2/2] 更新 Python 依赖..."
python -m pip install -r requirements.txt || echo "⚠ 依赖更新有警告，可忽略"

echo ""
echo "============================================"
echo "✅ 更新完成！请重启 ComfyUI 使更新生效"
echo "============================================"