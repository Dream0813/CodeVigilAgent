@echo off
chcp 65001>nul
title ReviewAgent - New User Mode
setlocal

rem ============================================================
rem  New-user entry point.
rem  Uses a SEPARATE config folder so your real ~/.reviewagent
rem  (with your api key) is never touched.
rem
rem  Every run starts from an empty config -> the setup wizard
rem  appears, which is exactly what you want to check the frames.
rem ============================================================

rem Config folder lives next to this script, so it works from any clone path.
set "REVIEWAGENT_HOME=%~dp0reviewagent-fresh"

rem Set REVIEWAGENT_FRAME_DEBUG=1 to get a warning when any box is
rem not perfectly aligned (printed to stderr).
set "REVIEWAGENT_FRAME_DEBUG=1"

rem %~dp0 = the folder this .bat lives in.
cd /d "%~dp0"

rem Move the old fresh-home aside instead of deleting it.
rem (never deletes anything; you can throw the .old folders away yourself)
set "BAK=%REVIEWAGENT_HOME%.old.%RANDOM%"
if exist "%REVIEWAGENT_HOME%" (
  move "%REVIEWAGENT_HOME%" "%BAK%" >nul 2>nul
)

echo.
echo   ============================================================
echo    New User Mode
echo    config folder : %REVIEWAGENT_HOME%
echo    your real config is NOT touched (~/.reviewagent)
echo   ============================================================
echo.

node bin\reviewagent.js

echo.
echo   [exited] press any key to close
pause >nul
