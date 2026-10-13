@echo off
chcp 65001 >nul
setlocal

REM Push current repo to Gitee with multi-account auto-match
REM First fill tokens in .gitee_tokens.json

echo ============================================
echo   推送到 Gitee (多账号自动匹配)
echo ============================================
echo.

for /f "tokens=1,2,3,4 delims=|" %%a in ('python gitee_push_helper.py 2^>nul') do (
    set STATUS=%%a
    set P1=%%b
    set P2=%%c
    set P3=%%d
)

if not "%STATUS%"=="OK" (
    echo ❌ %P1%
    echo.
    pause
    exit /b 1
)

set ACCOUNT=%P1%
set REPO=%P2%
set TOKEN=%P3%

echo 归属账号: %ACCOUNT%
echo 仓库名:   %REPO%
echo ✓ 已匹配令牌
echo.

echo [1/3] 暂存全部变更...
git add -A
if errorlevel 1 (
    echo ❌ git add 失败
    pause
    exit /b 1
)

echo [2/3] 提交 (如无变更会跳过)...
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "update %date:~0,4%-%date:~5,2%-%date:~8,2%"
    if errorlevel 1 (
        echo ❌ git commit 失败
        pause
        exit /b 1
    )
)

echo [3/4] 拉取远程并合并(本地优先)...
set PUSH_URL=https://%ACCOUNT%:%TOKEN%@gitee.com/%ACCOUNT%/%REPO%.git
git fetch "%PUSH_URL%" master:refs/remotes/gitee_master
git merge -X ours refs/remotes/gitee_master -m "merge remote, local first"
if errorlevel 1 (
    echo ❌ 合并失败，请手动解决后重跑
    set PUSH_URL=
    set TOKEN=
    pause
    exit /b 1
)

echo [4/4] 推送到 Gitee...
git push "%PUSH_URL%" master
set PUSH_RET=%errorlevel%

set PUSH_URL=
set TOKEN=

echo.
if %PUSH_RET% equ 0 (
    echo ============================================
    echo ✅ 推送成功！
    echo ============================================
) else (
    echo ❌ 推送失败，请检查令牌权限或网络
)
pause
endlocal