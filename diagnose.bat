@echo off
chcp 65001 >nul
title AI-HIL Debugger - 运行环境自检与启动诊断工具

echo ======================================================================
echo    AI-HIL Debugger - 系统运行环境自检与启动诊断工具
echo ======================================================================
echo.
echo 正在检测当前 Windows 计算机的基础运行依赖环境，请稍候...
echo.

set HAS_ERROR=0

:: 1. 检测 Microsoft Edge WebView2 运行时
echo [1/3] 检测 Microsoft Edge WebView2 运行时 (Tauri GUI 内核)...
set WV_FOUND=0
set WV_VERSION=未知

:: 检查 64位注册表 (WOW6432Node)
for /f "tokens=3" %%a in ('reg query "HKLM\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-9E4F-4275-A055-2242004F4E83}" /v pv 2^>nul') do (
    set WV_FOUND=1
    set WV_VERSION=%%a
)

:: 检查 64位原生注册表
if "%WV_FOUND%"=="0" (
    for /f "tokens=3" %%a in ('reg query "HKLM\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-9E4F-4275-A055-2242004F4E83}" /v pv 2^>nul') do (
        set WV_FOUND=1
        set WV_VERSION=%%a
    )
)

:: 检查 当前用户注册表
if "%WV_FOUND%"=="0" (
    for /f "tokens=3" %%a in ('reg query "HKCU\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-9E4F-4275-A055-2242004F4E83}" /v pv 2^>nul') do (
        set WV_FOUND=1
        set WV_VERSION=%%a
    )
)

:: 检查 默认磁盘目录备选
if "%WV_FOUND%"=="0" (
    if exist "%ProgramFiles(x86)%\Microsoft\EdgeWebView\Application" (
        set WV_FOUND=1
        set WV_VERSION=检测到安装目录
    )
)

if "%WV_FOUND%"=="1" (
    echo   [✔ 正常] 已安装 Microsoft Edge WebView2 运行时 (版本: %WV_VERSION%)
) else (
    echo   [❌ 缺失] 未检测到 Microsoft Edge WebView2 运行时！
    echo   ----------------------------------------------------------------------
    echo   原因说明: 本软件基于轻量级 Tauri 架构，需要系统提供 WebView2 渲染组件。
    echo   处理方法: 请下载安装微软官方微型引导程序 (约 1.8MB)，安装后即可运行。
    echo   ----------------------------------------------------------------------
    set HAS_ERROR=1
    set /p OPEN_WV="是否立即打开微软官方下载地址？(Y/N): "
    if /i "%OPEN_WV%"=="Y" (
        start https://go.microsoft.com/fwlink/p/?LinkId=2124703
    )
)
echo.

:: 2. 检测 Visual C++ 2015-2022 x64 运行库
echo [2/3] 检测 Microsoft Visual C++ 2015-2022 (x64) 基础运行库...
set VC_FOUND=0
for /f "tokens=3" %%a in ('reg query "HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\X64" /v Installed 2^>nul') do (
    if "%%a"=="0x1" set VC_FOUND=1
)

if "%VC_FOUND%"=="1" (
    echo   [✔ 正常] Visual C++ 2015-2022 (x64) 运行库已就绪
) else (
    echo   [⚠ 警告] 未检测到 VC++ 2015-2022 (x64) 运行库！
    echo   若启动时弹出 VCRUNTIME140.dll 报错，可安装微软官方运行库:
    echo   https://aka.ms/vs/17/release/vc_redist.x64.exe
)
echo.

:: 3. 检测后台守护进程文件
echo [3/3] 检测调试器 Python 守护进程...
set DAEMON_EXE=
if exist "hil-daemon-x86_64-pc-windows-msvc.exe" set DAEMON_EXE=hil-daemon-x86_64-pc-windows-msvc.exe
if exist "bin\hil-daemon-x86_64-pc-windows-msvc.exe" set DAEMON_EXE=bin\hil-daemon-x86_64-pc-windows-msvc.exe

if not "%DAEMON_EXE%"=="" (
    echo   [✔ 正常] 找到守护进程执行体: %DAEMON_EXE%
) else (
    echo   [⚠ 警告] 当前目录下未找到独立的 hil-daemon-x86_64-pc-windows-msvc.exe
)
echo.

echo ======================================================================
if "%HAS_ERROR%"=="0" (
    echo [状态良好] 基础环境检测通过，您可以直接双击运行 AI-HIL-Debugger.exe。
) else (
    echo [存在异常] 请根据上述红叉提示先安装缺失的系统组件。
)
echo ======================================================================
echo.

set /p RUN_NOW="是否现在直接以【带日志控制台模式】启动 AI-HIL-Debugger？(Y/N): "
if /i "%RUN_NOW%"=="Y" (
    echo.
    echo 正在启动 AI-HIL-Debugger.exe (日志将实时输出在此窗口，按 Ctrl+C 可停止)...
    echo.
    if exist "AI-HIL-Debugger.exe" (
        .\AI-HIL-Debugger.exe
    ) else if exist "src-tauri\target\release\ai-hil-debugger.exe" (
        .\src-tauri\target\release\ai-hil-debugger.exe
    ) else (
        echo 未找到 AI-HIL-Debugger.exe，请确认文件完整解压。
    )
)

echo.
pause
