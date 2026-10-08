@echo off
setlocal enabledelayedexpansion
title AI-HIL Debugger - Environment Diagnostics

echo ======================================================================
echo    AI-HIL Debugger - Environment Diagnostics and System Health Check
echo ======================================================================
echo.
echo Checking runtime prerequisites for AI-HIL Debugger...
echo.

set HAS_ERROR=0

rem 1. Check Microsoft Edge WebView2 Runtime
echo [1/3] Checking Microsoft Edge WebView2 Runtime [Tauri GUI Engine]...
set WV_FOUND=0
set WV_VERSION=unknown

for /f "tokens=3" %%a in ('reg query "HKLM\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-9E4F-4275-A055-2242004F4E83}" /v pv 2^>nul') do (
    set WV_FOUND=1
    set WV_VERSION=%%a
)

if "!WV_FOUND!"=="0" (
    for /f "tokens=3" %%a in ('reg query "HKLM\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-9E4F-4275-A055-2242004F4E83}" /v pv 2^>nul') do (
        set WV_FOUND=1
        set WV_VERSION=%%a
    )
)

if "!WV_FOUND!"=="0" (
    for /f "tokens=3" %%a in ('reg query "HKCU\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-9E4F-4275-A055-2242004F4E83}" /v pv 2^>nul') do (
        set WV_FOUND=1
        set WV_VERSION=%%a
    )
)

if "!WV_FOUND!"=="0" (
    if exist "%ProgramFiles(x86)%\Microsoft\EdgeWebView\Application" (
        set WV_FOUND=1
        set WV_VERSION=Installed in Program Files
    )
)

if "!WV_FOUND!"=="1" (
    echo   [OK] Microsoft Edge WebView2 Runtime detected [Version: !WV_VERSION!]
) else (
    echo   [ERROR] Microsoft Edge WebView2 Runtime NOT found!
    echo   ----------------------------------------------------------------------
    echo   Notice: AI-HIL Debugger is built on Tauri and requires WebView2.
    echo   Please install the official evergreen bootstrapper:
    echo   https://go.microsoft.com/fwlink/p/?LinkId=2124703
    echo   ----------------------------------------------------------------------
    set HAS_ERROR=1
    set /p OPEN_WV="Open Microsoft download link in browser now? (Y/N): "
    if /i "!OPEN_WV!"=="Y" start https://go.microsoft.com/fwlink/p/?LinkId=2124703
)
echo.

rem 2. Check Visual C++ 2015-2022 x64 Runtime
echo [2/3] Checking Microsoft Visual C++ 2015-2022 [x64] Redistributable...
set VC_FOUND=0
for /f "tokens=3" %%a in ('reg query "HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\X64" /v Installed 2^>nul') do (
    if "%%a"=="0x1" set VC_FOUND=1
)

if "!VC_FOUND!"=="1" (
    echo   [OK] Visual C++ 2015-2022 [x64] Runtime is ready
) else (
    echo   [WARN] Visual C++ 2015-2022 [x64] Runtime not detected!
    echo   If you encounter VCRUNTIME140.dll errors on launch, install:
    echo   https://aka.ms/vs/17/release/vc_redist.x64.exe
)
echo.

rem 3. Check Python HIL Daemon Binary
echo [3/3] Checking Standalone HIL MCP Daemon Binary...
set DAEMON_EXE=
if exist "hil-daemon-x86_64-pc-windows-msvc.exe" set DAEMON_EXE=hil-daemon-x86_64-pc-windows-msvc.exe
if exist "bin\hil-daemon-x86_64-pc-windows-msvc.exe" set DAEMON_EXE=bin\hil-daemon-x86_64-pc-windows-msvc.exe

if not "!DAEMON_EXE!"=="" (
    echo   [OK] Found Daemon Binary: !DAEMON_EXE!
) else (
    echo   [WARN] hil-daemon-x86_64-pc-windows-msvc.exe not found in bin/ or root
)
echo.

echo ======================================================================
if "!HAS_ERROR!"=="0" (
    echo [STATUS: HEALTHY] All prerequisites passed. You can run AI-HIL-Debugger.exe!
) else (
    echo [STATUS: WARNING] Missing prerequisites detected above.
)
echo ======================================================================
echo.

set /p RUN_NOW="Launch AI-HIL-Debugger with console logging now? (Y/N): "
if /i "!RUN_NOW!"=="Y" (
    echo.
    echo Launching AI-HIL-Debugger.exe [Logs will appear in this window]...
    echo.
    if exist "AI-HIL-Debugger.exe" (
        .\AI-HIL-Debugger.exe
    ) else if exist "src-tauri\target\release\ai-hil-debugger.exe" (
        .\src-tauri\target\release\ai-hil-debugger.exe
    ) else (
        echo AI-HIL-Debugger.exe not found.
    )
)

echo.
pause
