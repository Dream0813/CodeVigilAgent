@echo off
chcp 65001 > nul
rem ============================================================
rem  RETIRED: this diagnostic script targets the old chat.py /
rem  test_chat.py entry points. Kept only for reference.
rem  For a supported health check use:
rem      ascend_cli.py doctor
rem  or launchers\start-framecheck.bat (border check).
rem ============================================================
setlocal
set "ROOT=%~dp0.."
set "PYTHONPATH=%ROOT%;%PYTHONPATH%"
cd /d "%ROOT%"

echo ========================================
echo ReviewAgent 诊断工具（旧版，仅供参考）
echo ========================================
echo.

echo [1] 检查 Python 版本
python --version
echo.

echo [2] 检查当前目录
cd
echo.

echo [3] 检查 legacy 目录
dir "%~dp0chat.py"
echo.

echo [4] 运行简化测试
python "%~dp0test_chat.py"
echo.

echo [5] 尝试运行 legacy\chat.py
python "%~dp0chat.py"
echo.

pause
