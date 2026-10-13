@echo off
chcp 65001 >nul
setlocal

REM 推送 ComfyUI-QIBO 到 Gitee
REM 用法：双击运行或 cmd 下 push_gitee.bat
REM   首次运行会提示输入 Gitee 私人访问令牌（Gitee 设置→私人令牌生成，勾选 projects 权限）
REM   也可先设置环境变量：set GITEE_TOKEN=xxxx

set GITEE_USER=qq719703856
set GITEE_REPO=comfy-ui-qibo
set BRANCH=master

echo ============================================
echo   推送 ComfyUI-QIBO 到 Gitee
echo ============================================
echo.

if "%GITEE_TOKEN%"=="" (
    set /p GITEE_TOKEN=请输入 Gitee 私人访问令牌：
    echo.
)

if "%GITEE_TOKEN%"=="" (
    echo ❌ 未提供令牌，退出
    pause
    exit /b 1
)

echo [1/3] 暂存全部变更（尊重 .gitignore）...
git add -A
if errorlevel 1 (
    echo ❌ git add 失败
    pause
    exit /b 1
)

echo [2/3] 提交（如无变更会跳过）...
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "update %date:~0,4%-%date:~5,2%-%date:~8,2%"
    if errorlevel 1 (
        echo ❌ git commit 失败
        pause
        exit /b 1
    )
)

echo [3/3] 推送到 Gitee...
set PUSH_URL=https://%GITEE_USER%:%GITEE_TOKEN%@gitee.com/%GITEE_USER%/%GITEE_REPO%.git
git push "%PUSH_URL%" %BRANCH%
set PUSH_RET=%errorlevel%

REM 清空变量避免泄露
set PUSH_URL=
set GITEE_TOKEN=

if %PUSH_RET% equ 0 (
    echo.
    echo ============================================
    echo ✅ 推送成功！
    echo ============================================
) else (
    echo.
    echo ❌ 推送失败，请检查令牌权限或网络
)
pause
endlocal