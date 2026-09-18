@echo off
setlocal
cd /d "%~dp0"

echo ========================================================
echo     AI-HIL Embedded Debugger (Development Mode)
echo ========================================================

if not exist "%~dp0node_modules" (
    echo [INFO] Installing frontend dependencies...
    call pnpm install
)

echo [INFO] Starting Tauri Dev with Vite Hot Reload...
call pnpm tauri dev

pause
