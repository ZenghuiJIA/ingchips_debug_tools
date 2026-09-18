@echo off
setlocal
cd /d "%~dp0"

echo ========================================================
echo        AI-HIL Embedded HIL Debugger (Windows)
echo ========================================================

echo [1/3] Cleaning up previous background instances...
powershell -NoProfile -Command "Stop-Process -Name 'AI-HIL-Debugger', 'app' -Force -ErrorAction SilentlyContinue"

if exist "%~dp0crash.log" del /f /q "%~dp0crash.log"
if exist "%~dp0app_debug.log" del /f /q "%~dp0app_debug.log"

set "TARGET_EXE=%~dp0AI-HIL-Debugger.exe"
if not exist "%TARGET_EXE%" set "TARGET_EXE=%~dp0bin\AI-HIL-Debugger.exe"
if not exist "%TARGET_EXE%" set "TARGET_EXE=%~dp0src-tauri\target\release\app.exe"

if not exist "%TARGET_EXE%" (
    echo [ERROR] Application binary not found!
    echo Please run build.bat first to compile the project.
    echo.
    pause
    exit /b 1
)

echo [2/3] Launching desktop application:
echo       %TARGET_EXE%
start "" "%TARGET_EXE%"

echo [3/3] Checking application status...
ping 127.0.0.1 -n 3 >nul 2>&1

powershell -NoProfile -Command "$p = Get-Process -Name 'AI-HIL-Debugger', 'app' -ErrorAction SilentlyContinue | Select-Object -First 1; if ($p) { Write-Host '[SUCCESS] AI-HIL-Debugger is running! PID:' $p.Id 'Memory:' ([math]::Round($p.WorkingSet64/1MB, 1)) 'MB' } else { Write-Host '[ERROR] Process failed to start.' }"

echo.
echo ========================================================
echo [SUCCESS] Application window opened.
echo You may close this launcher window at any time.
echo ========================================================
echo.
pause
