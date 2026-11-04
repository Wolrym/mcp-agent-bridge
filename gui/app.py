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

import os  # noqa: E402
import threading  # noqa: E402
import traceback  # noqa: E402

from PySide6.QtCore import QLockFile, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QIcon, QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from core import logs  # noqa: E402
from core.config import PROJECT_ROOT, settings  # noqa: E402
from gui.main_window import MainWindow  # noqa: E402

THEME_PATH = Path(__file__).resolve().parent / "theme.qss"
LOG_DIR = PROJECT_ROOT / "logs"
ICON_DIR = PROJECT_ROOT / "assets"
APP_ID = "MCPAgentBridge.ControlPanel"


def _app_icon() -> QIcon:
    icon = QIcon()
    for name in ("icon.ico", "icon.png"):
        path = ICON_DIR / name
        if path.is_file():
            icon.addFile(str(path))
    return icon


def _set_taskbar_identity() -> None:
    """Group the window under its own taskbar icon, not python.exe's."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:  # noqa: BLE001 - purely cosmetic
        pass


def _prepare_output() -> None:
    """Make the app safe to run without a console, and leave a trail.

    Started through pythonw.exe (the normal shortcut) there is no console:
    sys.stdout and sys.stderr are None, and libraries that touch them -
    uvicorn's log formatter calls sys.stdout.isatty() - crash. They get
    the null device instead, and every log line goes to logs/bridge.log so
    a windowless panel can still be diagnosed. With a console (the debug
    shortcut) the lines are printed live as well.
    """
    has_console = sys.stdout is not None
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    logs.enable_file(LOG_DIR / "bridge.log")
    if has_console:
        logs.enable_console()

    def report(text: str) -> None:
        logs.log("gui", "Unhandled error:\n" + text.rstrip(), level="error")

    previous = sys.excepthook

    def excepthook(exc_type, exc, tb) -> None:
        report("".join(traceback.format_exception(exc_type, exc, tb)))
        previous(exc_type, exc, tb)

    def thread_hook(args) -> None:
        report("".join(traceback.format_exception(
            args.exc_type, args.exc_value, args.exc_traceback
        )))

    sys.excepthook = excepthook
    threading.excepthook = thread_hook


def _single_instance() -> QLockFile | None:
    """Hold a lock while the panel runs; None if another copy holds it.

    Without a console a second double-click used to start a second panel
    that silently failed on busy ports.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(LOG_DIR / "panel.lock"))
    if lock.tryLock(200):
        return lock
    return None


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

    _prepare_output()
    _set_taskbar_identity()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("MCP Agent Bridge")
    app.setWindowIcon(_app_icon())

    lock = _single_instance()
    if lock is None:
        QMessageBox.information(
            None, "MCP Agent Bridge",
            "The control panel is already running - look for it on the "
            "taskbar.",
        )
        return 0
    app.setStyle("Fusion")
    app.setPalette(_dark_palette())
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(_load_theme())
    # Frameless windows have no native drop shadow; this keeps hover and
    # focus effects crisp instead of relying on platform defaults.
    app.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)

    use_v2 = "--v2" in args or os.environ.get("MCP_GUI_V2") == "1"
    if use_v2:
        from gui.main_window_v2 import MainWindowV2
        window = MainWindowV2()
    else:
        window = MainWindow()

    window.show()

    # --start is the one-off way in; the autostart toggle on the panel is
    # the persistent one. Either brings up the servers and the tunnel.
    autostart = bool(settings.get("gui", "autostart", default=False))
    if "--start" in args or autostart:
        window.start_everything()

    code = app.exec()
    lock.unlock()
    return code


if __name__ == "__main__":
    sys.exit(main())
