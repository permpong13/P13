@echo off
setlocal
cd /d "%~dp0"
title P13 Revit MCP - Streamable HTTP
echo Starting P13 Revit MCP...
echo.
echo MCP endpoint:    http://127.0.0.1:8013/mcp
echo Browser health: http://127.0.0.1:8013/health
echo Security:        Localhost only, bearer authentication enabled
echo.
echo Keep this window open. Press Ctrl+C to stop the server.
echo.
uv run main.py --transport streamable-http --port 8013
echo.
echo P13 Revit MCP stopped.
pause
