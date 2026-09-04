@echo off
REM Launcher only - all orchestration lives in Python.
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
)
"%PY%" run_core.py %*
endlocal
