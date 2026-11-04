"""Create the two Windows shortcuts for the control panel.

    python tools\\make_shortcuts.py             in the project folder
    python tools\\make_shortcuts.py --desktop   ...and on the desktop too

"MCP Agent Bridge"          pythonw.exe -m gui.app: no console window.
                            Log lines go to logs\\bridge.log.
"MCP Agent Bridge (debug)"  cmd /k python -m gui.app: a console that shows
                            the live log and stays open after a crash, so
                            the traceback can be read.

Shortcuts store absolute paths. Run this again after moving or renaming
the project folder. Nothing is built or installed.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICON = ROOT / "assets" / "icon.ico"
NAME = "MCP Agent Bridge"

_POWERSHELL = r"""
$shell = New-Object -ComObject WScript.Shell
$folders = @($env:SC_FOLDER)
if ($env:SC_DESKTOP -eq '1') { $folders += [Environment]::GetFolderPath('Desktop') }
foreach ($folder in $folders) {
  foreach ($kind in @('normal', 'debug')) {
    if ($kind -eq 'normal') { $name = $env:SC_NAME; $target = $env:SC_PYW; $arguments = '-m gui.app' }
    else { $name = $env:SC_NAME + ' (debug)'; $target = $env:ComSpec; $arguments = '/k ""' + $env:SC_PY + '" -m gui.app"' }
    $link = $shell.CreateShortcut((Join-Path $folder ($name + '.lnk')))
    $link.TargetPath = $target
    $link.Arguments = $arguments
    $link.WorkingDirectory = $env:SC_ROOT
    $link.IconLocation = $env:SC_ICON + ',0'
    $link.Description = 'MCP Agent Bridge control panel (' + $kind + ')'
    $link.Save()
    Write-Output ('created ' + (Join-Path $folder ($name + '.lnk')))
  }
}
"""


def interpreters() -> tuple:
    """(python.exe, pythonw.exe): the project's .venv first, then this one."""
    venv = ROOT / ".venv" / "Scripts"
    base = venv if (venv / "pythonw.exe").is_file() else Path(sys.executable).parent
    python, pythonw = base / "python.exe", base / "pythonw.exe"
    if not pythonw.is_file():
        raise SystemExit(f"pythonw.exe not found next to {python}")
    return python, pythonw


def main(argv: list) -> int:
    if os.name != "nt":
        print("Shortcuts are a Windows thing; nothing to do here.")
        return 1
    python, pythonw = interpreters()
    env = dict(
        os.environ,
        SC_FOLDER=str(ROOT), SC_ROOT=str(ROOT), SC_ICON=str(ICON), SC_NAME=NAME,
        SC_PY=str(python), SC_PYW=str(pythonw),
        SC_DESKTOP="1" if "--desktop" in argv else "0",
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", _POWERSHELL],
        env=env, capture_output=True, text=True,
    )
    print((result.stdout + result.stderr).strip())
    return result.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
