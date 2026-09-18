@echo off
setlocal
cd /d "%~dp0"

echo ========================================================
echo        AI-HIL Embedded Debugger (Full Build)
echo ========================================================

echo [1/3] Building Tauri release application...
call pnpm tauri build --no-bundle
if errorlevel 1 (
    echo [ERROR] Tauri build failed!
    pause
    exit /b 1
)

echo [2/4] Checking standalone Python daemon binary...
if not exist "%~dp0bin\hil-daemon-x86_64-pc-windows-msvc.exe" (
    echo [INFO] Python daemon binary missing, building standalone daemon...
    call "%~dp0build_daemon.bat"
) else (
    echo [INFO] Standalone daemon binary ready. (Tip: run build_daemon.bat to force rebuild daemon)
)

echo [3/3] Assembling distribution files into bin/ and root...
if not exist "%~dp0bin" mkdir "%~dp0bin"
copy /y "%~dp0src-tauri\target\release\app.exe" "%~dp0bin\AI-HIL-Debugger.exe" >nul
copy /y "%~dp0src-tauri\binaries\hil-daemon-x86_64-pc-windows-msvc.exe" "%~dp0bin\" >nul
copy /y "%~dp0src-tauri\target\release\app.exe" "%~dp0AI-HIL-Debugger.exe" >nul
copy /y "%~dp0src-tauri\binaries\hil-daemon-x86_64-pc-windows-msvc.exe" "%~dp0" >nul
copy /y "%~dp0src-tauri\target\release\app.exe" "%~dp0src-tauri\target\debug\app.exe" >nul

echo [4/4] Deploying MCP to CCSwitch and Agent configurations...
python "%~dp0scripts\deploy_mcp_to_agents.py"

echo.
echo ========================================================
echo [SUCCESS] Build finished successfully!
echo Executable ready at: AI-HIL-Debugger.exe
echo MCP server deployed to: CCSwitch, Claude, Codex, OpenCode, Gemini
echo You can run start.bat or double-click AI-HIL-Debugger.exe
echo ========================================================
pause
