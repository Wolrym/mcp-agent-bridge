"""GUI entry point.

    python -m gui.app            open the control panel
    python -m gui.app --start    open it and start everything right away

The panel and the headless CLI share the same core, so it is safe to use
whichever fits the moment - just not both at once on the same ports.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow "python gui/app.py" as well as "python -m gui.app".
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core import logs  # noqa: E402
from core.config import settings  # noqa: E402
from gui.main_window import MainWindow  # noqa: E402

THEME_PATH = Path(__file__).resolve().parent / "theme.qss"


def _load_theme() -> str:
    try:
        return THEME_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        logs.log("gui", "Could not load theme: " + str(exc), level="warn")
        return ""


def _dark_palette() -> QPalette:
    """A dark base palette.

    The stylesheet covers our own widgets, but standard dialogs (file
    picker, message boxes) partly paint from the palette, so without this
    they flash up light grey.
    """
    background = QColor("#09090b")
    surface = QColor("#101013")
    text = QColor("#fafafa")
    muted = QColor("#a1a1aa")

    palette = QPalette()
    palette.setColor(QPalette.Window, background)
    palette.setColor(QPalette.WindowText, text)
    palette.setColor(QPalette.Base, QColor("#0c0c0f"))
    palette.setColor(QPalette.AlternateBase, surface)
    palette.setColor(QPalette.Text, text)
    palette.setColor(QPalette.PlaceholderText, muted)
    palette.setColor(QPalette.Button, surface)
    palette.setColor(QPalette.ButtonText, text)
    palette.setColor(QPalette.ToolTipBase, surface)
    palette.setColor(QPalette.ToolTipText, text)
    palette.setColor(QPalette.Highlight, QColor("#3f3f46"))
    palette.setColor(QPalette.HighlightedText, text)
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor("#5b5b63"))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#5b5b63"))
    return palette


def main(argv: list | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    app = QApplication(sys.argv[:1])
    app.setApplicationName("MCP Control Panel")
    app.setStyle("Fusion")
    app.setPalette(_dark_palette())
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(_load_theme())
    # Frameless windows have no native drop shadow; this keeps hover and
    # focus effects crisp instead of relying on platform defaults.
    app.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)

    window = MainWindow()
    window.show()

    # --start is the one-off way in; the autostart toggle on the panel is
    # the persistent one. Either brings up the servers and the tunnel.
    autostart = bool(settings.get("gui", "autostart", default=False))
    if "--start" in args or autostart:
        window.start_everything()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
