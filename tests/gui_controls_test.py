"""Offscreen check of the new panel controls.

Builds the real window (no servers are started) and asserts that:
  * the master button exists, is compact, and flips its own label;
  * the autostart switch round-trips through the settings store;
  * the scroll viewport is transparent, which is what kept the shell's
    bottom-left corner rounded.

Run with:
    set "QT_QPA_PLATFORM=offscreen" && python tests\\gui_controls_test.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from core.config import settings  # noqa: E402
from gui.app import _dark_palette, _load_theme  # noqa: E402
from gui.main_window import MainWindow  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    app.setPalette(_dark_palette())
    app.setStyleSheet(_load_theme())

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
    check("master button is compact", master.objectName() == "titleAction")
    check(
        "master button sits in the title bar",
        window._chrome.title_bar.isAncestorOf(master),
    )
    check("master starts as primary", master.property("variant") == "default")

    window._sync_master(True)
    check("label flips when running", master.text() == "Stop everything", master.text())
    check("stop is quiet", master.property("variant") == "secondary")
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

    # --- corner fix ------------------------------------------------------
    scroll = window._shell.findChildren(type(window._shell))
    from PySide6.QtWidgets import QScrollArea

    areas = window.findChildren(QScrollArea)
    check("the panel has a scroll area", len(areas) == 1, str(len(areas)))
    if areas:
        check(
            "viewport does not fill itself",
            areas[0].viewport().autoFillBackground() is False,
        )
    check("shell is the rounded surface", window._shell.objectName() == "windowShell")
    del scroll

    window.close()

    print("")
    if failures:
        print("FAILED: " + ", ".join(failures))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
