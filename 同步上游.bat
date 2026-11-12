@echo off
chcp 65001>nul
setlocal
title 同步项目组总仓库 - CodeVigil Agent
cd /d "%~dp0"

rem Double-click to pull the upstream team repo into this desktop copy.
rem Uses scripts\sync_upstream.py because git fetch cannot reach
rem github.com from this network (proxy only allows api.github.com).

set "PY="
for %%C in (python py python3) do (
    if not defined PY (
        %%C -c "import sys" >nul 2>nul && set "PY=%%C"
    )
)

if not defined PY (
    echo   [失败] 没找到 Python。请先安装 Python 3。
    pause
    exit /b 1
)

echo.
echo   检查项目组总仓库是否有新提交...
echo.
%PY% scripts\sync_upstream.py --apply
echo.
echo   ---- 完成。上面的数字说明：
echo        「已是最新」= 没有新东西
echo        「已写入 N 个」= 新文件已更新到桌面程序
echo        「冲突」= 这些文件本地也改过，没被覆盖，需要手动合并
echo.
pause
