@echo off
chcp 65001>nul
title ReviewAgent (兼容模式)
rem ============================================================
rem  兼容模式 / 退回开关
rem
rem  作用：关闭「定位渲染」，边框改回原来的「补空格对齐」。
rem
rem  什么时候用这个：
rem    1. 界面右边框位置乱跳、上下跑
rem    2. 屏幕上出现 ^[  或 [1;2H 之类的乱码控制符
rem    3. 用的是 Windows 7 之类的老终端（不支持光标定位）
rem
rem  换回正常模式：双击 start-reviewagent.bat
rem ============================================================

cd /d "%~dp0"
set "REVIEWAGENT_RENDER=pad"

echo.
echo   [兼容模式] 已关闭定位渲染，边框改用补空格对齐
echo   换回正常模式请双击 start-reviewagent.bat
echo.

node bin\reviewagent.js

echo.
echo   [exited] press any key to close
pause >nul
