@echo off
chcp 65001 > nul
rem Retired entry point, kept for reference. Repo root is one level up.
cd /d "%~dp0.."
python scripts\smart_reviewer.py
pause
