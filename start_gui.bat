@echo off
REM Launch the MCP control panel. Prefers the local virtualenv if present.
setlocal
cd /d "%~dp0"

set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

"%PY%" -m gui.app %*
if errorlevel 1 pause
