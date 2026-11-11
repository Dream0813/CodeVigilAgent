@echo off
chcp 65001>nul
setlocal enabledelayedexpansion
title CodeVigil Agent 桌面版
cd /d "%~dp0"

rem ============================================================
rem  双击这个文件启动桌面版。
rem
rem  为什么不用固定路径的 python：
rem     PATH 里可能有多个 Python，有的（比如精简版）不含 tkinter，
rem     直接用会报 ModuleNotFoundError。这里逐个试，挑第一个能用的。
rem ============================================================

echo.
echo   正在查找可用的 Python…
echo.

set "PY="

rem 先试 PATH 里的 python / py
for %%C in (python py python3) do (
    if not defined PY (
        %%C -c "import tkinter" >nul 2>nul && set "PY=%%C"
    )
)

rem PATH 里没有就遍历 where 的结果
if not defined PY (
    for /f "delims=" %%P in ('where python 2^>nul') do (
        if not defined PY (
            "%%P" -c "import tkinter" >nul 2>nul && set "PY=%%P"
        )
    )
)

if not defined PY (
    echo   [失败] 没找到带 tkinter 的 Python。
    echo.
    echo   解决办法（任选一个）：
    echo     1. 重新安装 Python，安装时勾选 "tcl/tk and IDLE"
    echo     2. 如果你有多个 Python，把带 tkinter 的那个放在 PATH 前面
    echo     3. 直接命令行运行：python desktop-app\win\app.py
    echo        看它报什么错，把错误发给我
    echo.
    pause
    exit /b 1
)

echo   使用 Python：%PY%
echo   正在启动窗口…
echo.

rem pythonw 不弹黑色控制台窗口；找不到就用普通 python
for %%D in ("%PY%") do set "PYDIR=%%~dpD"
set "PYW=%PYDIR%pythonw.exe"
if not exist "%PYW%" set "PYW=%PY%"

start "" "%PYW%" "%~dp0desktop-app\win\app.py"

rem 给窗口一点启动时间，然后关掉这个黑框
timeout /t 2 >nul
exit /b 0
