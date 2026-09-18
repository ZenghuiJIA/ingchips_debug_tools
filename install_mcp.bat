@echo off
chcp 65001 >nul
title AI-HIL Embedded MCP Server Installer

echo ========================================================
echo      AI-HIL Embedded MCP Server - One-Click Installer
echo ========================================================
echo.
echo This script will register the Embedded HIL Debugger MCP server
echo into all discovered AI agents on your system:
echo  - CCSwitch (Database: ~/.cc-switch/cc-switch.db)
echo  - Claude Code (~/.claude.json)
echo  - Claude Desktop (%%APPDATA%%\Claude\claude_desktop_config.json)
echo  - Cursor / Windsurf (mcp.json)
echo  - OpenAI Codex (~/.codex/config.toml)
echo  - OpenCode (~/.config/opencode/opencode.json)
echo  - Gemini / Antigravity CLI (~/.gemini/config/mcp_config.json)
echo.

python "%~dp0scripts\deploy_mcp_to_agents.py"
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] MCP Deployment failed. Please ensure Python is installed.
    pause
    exit /b %ERRORLEVEL%
)

echo.
pause
