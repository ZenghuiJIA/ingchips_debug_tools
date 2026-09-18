@echo off
chcp 65001 >nul
title AI-HIL Debugger - Standalone MCP Daemon Builder

echo ========================================================
echo   AI-HIL Standalone MCP Daemon Rebuild & Test Pipeline
echo ========================================================
echo.
echo This script will:
echo  1. Stop any background daemon processes locking the binary
echo  2. Freeze src-tauri\daemon\daemon_entry.py with PyInstaller
echo  3. Synchronize hil-daemon-x86_64-pc-windows-msvc.exe to bin/ and root
echo  4. Run automated MCP initialize and tool validation tests
echo  5. Redeploy MCP configurations to all AI Agents
echo  6. Refresh the standalone release distribution package
echo.

python "%~dp0scripts\build_daemon_windows.py"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Build pipeline failed with code %ERRORLEVEL%!
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo ========================================================
echo [SUCCESS] MCP Daemon compiled, tested and released!
echo ========================================================
pause
