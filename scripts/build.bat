@echo off
setlocal
cd /d "%~dp0.."
set "ROOT_DIR=%CD%"

echo ========================================================
echo        AI-HIL Embedded Debugger (Full Build)
echo ========================================================

echo [1/4] Building Tauri release application...
call pnpm tauri build --no-bundle
if errorlevel 1 (
    echo [ERROR] Tauri build failed!
    pause
    exit /b 1
)

echo [2/4] Checking standalone Python daemon binary...
if not exist "%ROOT_DIR%\bin\hil-daemon-x86_64-pc-windows-msvc.exe" (
    echo [INFO] Python daemon binary missing, building standalone daemon...
    python "%ROOT_DIR%\scripts\build_daemon_windows.py"
) else (
    echo [INFO] Standalone daemon binary ready. (Tip: run python scripts/build_daemon_windows.py to force rebuild daemon)
)

echo [3/4] Assembling compiled binaries into bin/...
if not exist "%ROOT_DIR%\bin" mkdir "%ROOT_DIR%\bin"
set "SRC_EXE=%ROOT_DIR%\src-tauri\target\release\ai-hil-debugger.exe"
if not exist "%SRC_EXE%" set "SRC_EXE=%ROOT_DIR%\src-tauri\target\release\app.exe"

copy /y "%SRC_EXE%" "%ROOT_DIR%\bin\AI-HIL-Debugger.exe" >nul
copy /y "%SRC_EXE%" "%ROOT_DIR%\src-tauri\target\release\app.exe" >nul

echo [4/4] Packaging release and deploying MCP...
python "%ROOT_DIR%\scripts\package_release.py"
python "%ROOT_DIR%\scripts\deploy_mcp_to_agents.py"

echo.
echo ========================================================
echo [SUCCESS] Build finished successfully!
echo Development binary ready at: bin\AI-HIL-Debugger.exe
echo Standalone release package at: release\AI-HIL-Debugger-v1.0.0-windows-x64\
echo MCP server deployed to: CCSwitch, Claude, Codex, OpenCode, Gemini
echo ========================================================
pause
