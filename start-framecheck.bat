@echo off
chcp 65001>nul
title ReviewAgent - Frame Check
rem %~dp0 = the folder this .bat lives in, so the repo can be cloned anywhere.
cd /d "%~dp0"

rem ============================================================
rem  Border check ONLY. No API key needed, no network.
rem  Draws all four boxes and prints the display width of every
rem  line. Same width on every line of a box = vertical bars align.
rem ============================================================

echo.
python -m scripts.frame_doctor
echo.
echo   ------------------------------------------------------------
echo   If some rows are off, try these two in order:
echo     1. set REVIEWAGENT_AMBIGUOUS=0   ^&^& python -m scripts.frame_doctor
echo     2. switch the console font to NSimSun (Xin Song Ti)
echo   ------------------------------------------------------------
echo.
echo   [done] press any key to close
pause >nul
