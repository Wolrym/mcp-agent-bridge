"""Render the control panel offscreen to PNG files, for visual review.

    python tools\\screenshot_gui.py [output folder]

Uses a throwaway settings file (two sample projects, tunnel configured but
off), starts nothing, and writes main.png, main-full.png and guide-*.png
into the output folder (default: .mcp-runs\\shots).
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
from PySide6.QtWidgets import QApplication, QScrollArea, QTabWidget  # noqa: E402

from core import logs  # noqa: E402
from gui import app as gui_app  # noqa: E402
from gui.main_window import MainWindow  # noqa: E402


def main(argv: list) -> int:
    out = Path(argv[0]) if argv else ROOT / ".mcp-runs" / "shots"
    out.mkdir(parents=True, exist_ok=True)
    qt = QApplication(sys.argv[:1])
    qt.setStyle("Fusion")
    qt.setPalette(gui_app._dark_palette())
    qt.setFont(QFont("Segoe UI", 10))
    qt.setStyleSheet(gui_app._load_theme())

    for text, level in [("Listening on http://127.0.0.1:9500/mcp", "info"),
                        ("read_file(path=C:\\proj\\main.py)  0.02s", "info"),
                        ("run_command(command=npm test, cwd=C:\\proj)  12.40s", "info"),
                        ("Blocked: taskkill /f /im python.exe", "warn")]:
        logs.log("files" if "read" in text else "terminal", text, level=level, kind="call")

    window = MainWindow()
    window.resize(1180, 860)
    window.show()

    def shoot() -> None:
        window.grab().save(str(out / "main.png"))
        areas = window.findChildren(QScrollArea)
        if areas:
            inner = areas[0].widget()
            inner.grab().save(str(out / "main-full.png"))
        try:
            from gui.widgets.setup_guide import SetupGuideDialog
            guide = SetupGuideDialog(window)
            guide.show()
            tabs = guide.findChild(QTabWidget)
            for index in range(tabs.count() if tabs else 1):
                if tabs:
                    tabs.setCurrentIndex(index)
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
