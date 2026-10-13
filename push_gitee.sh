#!/bin/bash
# 推送 ComfyUI-QIBO 到 Gitee
# 用法：bash push_gitee.sh
#   首次运行会提示输入 Gitee 私人访问令牌（在 Gitee 设置→私人令牌生成，勾选 projects 权限）
#   也可直接设置环境变量：GITEE_TOKEN=xxxx bash push_gitee.sh

GITEE_USER="qq719703856"
GITEE_REPO="comfy-ui-qibo"
BRANCH="master"

echo "============================================"
echo "  推送 ComfyUI-QIBO 到 Gitee"
echo "============================================"
echo ""

# 读取令牌：优先环境变量，否则交互输入（隐藏显示）
if [ -z "$GITEE_TOKEN" ]; then
    printf "请输入 Gitee 私人访问令牌（输入不可见）："
    read -s GITEE_TOKEN
    echo ""
fi

if [ -z "$GITEE_TOKEN" ]; then
    echo "❌ 未提供令牌，退出"
    exit 1
fi

echo "[1/3] 暂存全部变更（尊重 .gitignore）..."
git add -A || { echo "❌ git add 失败"; exit 1; }

echo "[2/3] 提交（如无变更会跳过）..."
git diff --cached --quiet || git commit -m "update $(date +%Y-%m-%d)" || { echo "❌ git commit 失败"; exit 1; }

echo "[3/3] 推送到 Gitee..."
PUSH_URL="https://${GITEE_USER}:${GITEE_TOKEN}@gitee.com/${GITEE_USER}/${GITEE_REPO}.git"
git push "$PUSH_URL" "$BRANCH"
PUSH_RET=$?

# 立即清空变量，避免泄露
PUSH_URL=""
GITEE_TOKEN=""

if [ $PUSH_RET -eq 0 ]; then
    echo ""
    echo "============================================"
    echo "✅ 推送成功！"
    echo "============================================"
else
    echo ""
    echo "❌ 推送失败，请检查令牌权限或网络"
    exit $PUSH_RET
fi