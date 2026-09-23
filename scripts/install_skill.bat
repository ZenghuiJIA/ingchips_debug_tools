@echo off
chcp 65001 >nul
title AI-HIL Debugger - Skill Installer

echo ========================================================
echo       AI-HIL Debugger - AI Agent Skill Installer
echo ========================================================

python "%~dp0scripts\install_skill.py"
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python execution failed. Please check Python environment.
    pause
    exit /b %ERRORLEVEL%
)

echo.
pause
