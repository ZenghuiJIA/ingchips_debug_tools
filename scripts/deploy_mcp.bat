@echo off
setlocal
cd /d "%~dp0"

echo ========================================================
echo   AI-HIL MCP Server Deployment to CCSwitch & Agents
echo ========================================================

python "%~dp0scripts\deploy_mcp_to_agents.py"

echo.
pause
