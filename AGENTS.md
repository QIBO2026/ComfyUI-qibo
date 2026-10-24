# AGENTS.md — 项目操作规范

## Bash / Git 命令（防卡死，必须遵循）

Windows git-bash 环境下以下命令模式偶发挂起，**禁止使用**：

- ❌ `ls | grep` 在主目录（/c/Users/...）跑管道
- ❌ `git push ... 2>&1 | tail` / `| head`——git push 进度条 `\r` 刷新经管道堵死
- ❌ `cat > file <<'EOF' ... EOF` 100+ 行含中文的 heredoc

**正确做法**：

1. **git push 不接管道**，直接 `git push <url> master`，输出完整显示
2. **拆分命令链**：`node --check` / `git add+commit` / `git push` 分三次执行，不 `&&` 串联
3. **push 给长 timeout**：bash 工具 timeout=180000
4. **长测试脚本用 write 工具**写到 `C:/Users/Administrator/AppData/Local/Temp/xxx.js`，bash 只跑 `node 路径`
5. **检查文件存在用 read/glob**，不用 `ls | grep`
6. git http 低速超时已全局配置（`http.lowSpeedLimit=1000` + `http.lowSpeedTime=30`），慢于 1KB/s 持续 30s 自动中止

## 构建/测试

- Python 编译：`python -m py_compile <file>`
- JS 语法：`node --check <file>`
- 单测：`python tests/test_xxx.py`（自校验脚本模式；pytest 无法运行因插件根 `__init__.py` 包名含连字符）

## 部署

本地 `git push` 到 Gitee → 服务器 `git pull` + 重启 ComfyUI（新路由必须重启才注册）→ 浏览器 Ctrl+F5。
push 用多账号令牌：`https://qq719703856:<token>@gitee.com/qq719703856/ComfyUI-qibo.git`。