import json, re, subprocess, sys, os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

def emit(status, *parts):
    print("|".join([status] + list(parts)))
    sys.exit()

try:
    url = subprocess.check_output(
        ["git", "remote", "get-url", "origin"], stderr=subprocess.DEVNULL
    ).decode().strip()
except Exception:
    emit("ERROR", "未配置 origin 远程，请先: git remote add origin https://gitee.com/<账号>/<仓库>.git")

m = re.match(r".*gitee\.com/([^/]+)/([^/]+?)\.git", url)
if not m:
    emit("ERROR", f"无法从 origin 解析 gitee 账号/仓库: {url}")
account, repo = m.group(1), m.group(2)

try:
    d = json.load(open(".gitee_tokens.json", "r", encoding="utf-8"))
except Exception:
    emit("ERROR", "未找到 .gitee_tokens.json，请先创建并填入令牌")

token = d.get(account, "")
if not token or "在这里填" in token:
    emit("ERROR", f".gitee_tokens.json 中未配置账号 [{account}] 的令牌；请编辑该文件，生成地址: Gitee → 设置 → 私人令牌(勾选 projects)")

emit("OK", account, repo, token)