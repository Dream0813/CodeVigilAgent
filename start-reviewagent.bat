@echo off
chcp 65001>nul
title ReviewAgent
rem %~dp0 = the folder this .bat lives in, so the repo can be cloned anywhere.
cd /d "%~dp0"
echo   Starting ReviewAgent ...
echo.
node bin\reviewagent.js
echo.
echo   [exited] press any key to close
pause >nul
