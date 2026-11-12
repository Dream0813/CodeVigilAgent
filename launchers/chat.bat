@echo off
chcp 65001 > nul
rem This .bat lives in launchers\, so the repo root is one level up (%~dp0..).
python "%~dp0..\ascend_cli.py" chat %*
