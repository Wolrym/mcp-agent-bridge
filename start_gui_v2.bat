@echo off
REM Launch the redesigned MCP control panel (v2).
setlocal
cd /d "%~dp0"

set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

"%PY%" -m gui.app --v2 %*
if errorlevel 1 pause
