#!/bin/bash
# 推送当前仓库到 Gitee（多账号自动匹配）
# 原理：gitee_push_helper.py 读 origin → 解析账号 → 查 .gitee_tokens.json 令牌 → 输出 OK|账号|仓库|令牌
# 用法：bash push_gitee.sh
#   首次使用前，先在 .gitee_tokens.json 填好各账号令牌

cd "$(dirname "$0")"

echo "============================================"
echo "  推送到 Gitee（多账号自动匹配）"
echo "============================================"
echo ""

RESULT=$(python gitee_push_helper.py 2>&1)
STATUS=$(echo "$RESULT" | cut -d'|' -f1)

if [ "$STATUS" != "OK" ]; then
    MSG=$(echo "$RESULT" | cut -d'|' -f2-)
    echo "❌ $MSG"
    exit 1
fi

ACCOUNT=$(echo "$RESULT" | cut -d'|' -f2)
REPO=$(echo "$RESULT" | cut -d'|' -f3)
TOKEN=$(echo "$RESULT" | cut -d'|' -f4)

echo "归属账号: $ACCOUNT"
echo "仓库名:   $REPO"
echo "✓ 已匹配令牌"
echo ""

echo "[1/3] 暂存全部变更（尊重 .gitignore）..."
git add -A || { echo "❌ git add 失败"; exit 1; }

echo "[2/3] 提交（如无变更会跳过）..."
if git diff --cached --quiet; then
    echo "  无变更，跳过提交"
else
    git commit -m "update $(date +%Y-%m-%d)" || { echo "❌ git commit 失败"; exit 1; }
fi

echo "[3/4] 拉取远程并合并（本地优先）..."
PUSH_URL="https://${ACCOUNT}:${TOKEN}@gitee.com/${ACCOUNT}/${REPO}.git"
git fetch "$PUSH_URL" master:refs/remotes/gitee_master 2>&1 | grep -v "$TOKEN"
git merge -X ours refs/remotes/gitee_master -m "merge 远程变更，本地优先"
if [ $? -ne 0 ]; then
    echo "❌ 合并失败，请手动解决后重跑"
    PUSH_URL=""; TOKEN=""
    exit 1
fi

echo "[4/4] 推送到 Gitee..."
git push "$PUSH_URL" "$(git rev-parse --abbrev-ref HEAD)"
PUSH_RET=$?

PUSH_URL=""
TOKEN=""

echo ""
if [ $PUSH_RET -eq 0 ]; then
    echo "============================================"
    echo "✅ 推送成功！"
    echo "============================================"
else
    echo "❌ 推送失败，请检查令牌权限或网络"
    exit $PUSH_RET
fi