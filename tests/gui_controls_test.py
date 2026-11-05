"""Offscreen check of the new panel controls.

Builds the real window (no servers are started) and asserts that:
  * the master button exists, is compact, and flips its own label;
  * the autostart switch round-trips through the settings store;
  * the scroll viewport is transparent, which is what kept the shell's
    bottom-left corner rounded;
  * building rows (startup, settings refresh, setup guide) never flashes
    a widget as its own little top-level window.

Run with:
    set "QT_QPA_PLATFORM=offscreen" && python tests\\gui_controls_test.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Throwaway settings: the autostart check toggles a real setting.
_settings_file = Path(tempfile.mkdtemp(prefix="mcp-gui-")) / "settings.json"
_settings_file.write_text(
    json.dumps({"auth": {"enabled": True, "token": "gui-test"}}), encoding="utf-8"
)
os.environ["MCP_SETTINGS_PATH"] = str(_settings_file)

from PySide6.QtCore import QEvent, QObject  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from core.config import settings  # noqa: E402
from gui.app import _dark_palette, _load_theme  # noqa: E402
from gui.main_window import MainWindow  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    app.setPalette(_dark_palette())
    app.setStyleSheet(_load_theme())

    # Any widget shown while it has no parent becomes a window of its own:
    # on Windows that is a tiny flashing "MCP Agent Bridge" window.
    stray: list[str] = []

    class StrayWindows(QObject):
        def eventFilter(self, obj, event):  # noqa: N802 - Qt naming
            if (
                event.type() == QEvent.Show
                and obj.isWidgetType()
                and obj.isWindow()
                and not isinstance(obj, (MainWindow, QDialog))
            ):
                stray.append(type(obj).__name__)
            return False

    stray_filter = StrayWindows()
    app.installEventFilter(stray_filter)

    original = bool(settings.get("gui", "autostart", default=False))
    window = MainWindow()
    window.show()

    failures = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(("ok   " if condition else "FAIL ") + name + ("  " + detail if detail else ""))
        if not condition:
            failures.append(name)

    # --- master button ---------------------------------------------------
    master = window._master_button
    check("master button label", master.text() == "Start everything", master.text())
    check("master button is the sidebar action", master.objectName() == "masterAction")
    check(
        "master button is not in the title bar",
        not window._chrome.title_bar.isAncestorOf(master),
    )
    check(
        "health pill sits in the title bar",
        window._chrome.title_bar.isAncestorOf(window._health_pill),
    )
    check("master starts as primary", master.property("variant") == "default")

    window._sync_master(True)
    check("label flips when running", master.text() == "Stop everything", master.text())
    check("stop is quiet", master.property("variant") == "secondary")
    check("icon flips to stop", master._glyph == "stop")
    window._sync_master(False)
    check("label flips back", master.text() == "Start everything")

    check("nothing is running yet", window._anything_running() is False)

    # --- autostart switch ------------------------------------------------
    switch = window._autostart
    check("switch reflects settings", switch.isChecked() == original)

    switch.setChecked(not original)
    stored = bool(settings.get("gui", "autostart", default=False))
    check("toggling persists", stored == (not original), str(stored))
    check("no signal loop", switch.isChecked() == (not original))

    switch.setChecked(original)
    check(
        "restored",
        bool(settings.get("gui", "autostart", default=False)) == original,
    )

    # --- pages -----------------------------------------------------------
    from gui.main_window import PAGES

    for key, _text, _icon in PAGES:
        window.show_page(key)
        check("page " + key + " opens", window.current_page() == key)
        check("nav follows " + key, window._nav_buttons[key].isChecked())
    window.show_page("overview")

    # --- endpoints and the log filter -------------------------------------
    window._endpoint_mode.set_value("local")
    window._on_endpoint_mode("local")
    check(
        "local endpoints shown",
        window._files_endpoint.value().startswith("http://127.0.0.1"),
        window._files_endpoint.value(),
    )
    window._log_filter_control.set_value("problems")
    window._set_log_filter("problems")
    from core import logs
    logs.log("test", "quiet line")
    logs.log("test", "loud line", level="warn")
    text = window._log_view.toPlainText()
    check("problems filter hides info", "quiet line" not in text and "loud line" in text)
    window._set_log_filter("all")
    check("all shows everything again", "quiet line" in window._log_view.toPlainText())

    # --- corner fix ------------------------------------------------------
    from PySide6.QtWidgets import QScrollArea

    areas = window.findChildren(QScrollArea)
    check("pages scroll", len(areas) >= 5, str(len(areas)))
    check(
        "no viewport fills itself",
        all(area.viewport().autoFillBackground() is False for area in areas),
    )
    check("shell is the rounded surface", window._shell.objectName() == "windowShell")

    # --- no stray windows --------------------------------------------------
    from gui.widgets.setup_guide import SetupGuideDialog

    app.processEvents()
    window.refresh()
    app.processEvents()
    guide = SetupGuideDialog(window)
    for index in range(guide.page_count()):
        guide.show_page(index)
    app.processEvents()
    check("no stray top-level windows", not stray, ", ".join(stray[:5]))
    guide.deleteLater()

    window.close()

    print("")
    if failures:
        print("FAILED: " + ", ".join(failures))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
