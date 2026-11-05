"""Render the control panel offscreen to PNG files, for visual review.

    python tools\\screenshot_gui.py [output folder]

Uses a throwaway settings file (two sample projects, tunnel configured but
off), starts nothing, and writes main.png (the overview), main-<page>.png
for every sidebar page, guide-*.png, plus small copies (titlebar.png,
main-small.png) into the output folder (default: .mcp-runs\\shots).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# The offscreen platform reads fonts from a folder instead of asking
# Windows; without this every label renders as empty boxes.
if sys.platform == "win32":
    os.environ.setdefault(
        "QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    )

_temp = Path(tempfile.mkdtemp(prefix="mcp-shot-"))
(_temp / "settings.json").write_text(json.dumps({
    "auth": {"enabled": True, "token": "sample-token-for-screenshots-only"},
    "tunnel": {"enabled": False, "domain": "example.com", "user_slug": "alex",
               "files_hostname": "alex-files.example.com",
               "terminal_hostname": "alex-term.example.com",
               "config_file": "C:\\Users\\alex\\.cloudflared\\config.yml"},
    "projects": [
        {"id": "web", "name": "web-shop", "root": "C:\\Users\\alex\\code\\web-shop", "selected_at": None},
        {"id": "bridge", "name": "mcp-agent-bridge", "root": str(ROOT), "selected_at": None},
    ],
    "active_project_id": "bridge",
}), encoding="utf-8")
os.environ["MCP_SETTINGS_PATH"] = str(_temp / "settings.json")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core import logs  # noqa: E402
from gui import app as gui_app  # noqa: E402
from gui.main_window import PAGES, MainWindow  # noqa: E402


def main(argv: list) -> int:
    out = Path(argv[0]) if argv else ROOT / ".mcp-runs" / "shots"
    out.mkdir(parents=True, exist_ok=True)
    qt = QApplication(sys.argv[:1])
    qt.setStyle("Fusion")
    qt.setPalette(gui_app._dark_palette())
    qt.setFont(QFont("Segoe UI", 10))
    qt.setStyleSheet(gui_app._load_theme())
    qt.setWindowIcon(gui_app._app_icon())

    for text, level in [("Listening on http://127.0.0.1:9500/mcp", "info"),
                        ("read_file(path=C:\\proj\\main.py)  0.02s", "info"),
                        ("run_command(command=npm test, cwd=C:\\proj)  12.40s", "info"),
                        ("run_command(command=git status --short & git log --oneline -3 & git fetch -q origin & git status -sb | findstr \"##\" & git rev-list --count origin/main..main, cwd=C:\\Users\\Dima\\VSCodeProjects\\tools\\mcp-agent-bridge)  5.21s", "info"),
                        ("Request failed error=\"dial tcp 127.0.0.1:9501: connectex: No connection could be made because the target machine actively refused it.\" dest=https://mcp-term.example.com/mcp", "warn"),
                        ("Blocked: taskkill /f /im python.exe", "warn")]:
        logs.log("files" if "read" in text else "terminal", text, level=level, kind="call")

    window = MainWindow()
    window.resize(1120, 780)
    window.show()

    def shoot() -> None:
        # One picture per sidebar page; main.png is the overview.
        for key in [k for k, _t, _i in PAGES]:
            window.show_page(key)
            qt.processEvents()
            window.grab().save(str(out / f"main-{key}.png"))
        window.show_page("overview")
        qt.processEvents()
        shot = window.grab()
        shot.save(str(out / "main.png"))
        # Small copies: some clients pass images to the model as base64
        # text, so the full-size PNG is expensive to look at.
        shot.copy(0, 0, 640, 56).save(str(out / "titlebar.png"))
        shot.scaledToWidth(640).save(str(out / "main-small.png"))
        try:
            from gui.widgets.setup_guide import SetupGuideDialog
            guide = SetupGuideDialog(window)
            guide.show()
            for index in range(guide.page_count()):
                guide.show_page(index)
                qt.processEvents()
                guide.grab().save(str(out / f"guide-{index + 1}.png"))
            guide.close()
        finally:
            window.close()
            qt.quit()

    QTimer.singleShot(600, shoot)
    qt.exec()
    print("saved to", out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
