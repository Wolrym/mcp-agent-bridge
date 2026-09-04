"""Custom window chrome: our own title bar instead of the Windows one.

Qt cannot restyle the native caption bar, so the window is created
frameless and the bar is rebuilt as ordinary widgets. Moving and resizing
still go through the compositor via `startSystemMove` and
`startSystemResize`, so snapping, Aero shake and multi-monitor DPI keep
working exactly as users expect - only the pixels are ours.

The window buttons are drawn with QPainter rather than set as text: glyph
characters get substituted by the colour emoji font on Windows, which is
how you end up with a pink square instead of a maximise icon.

Usage:

    chrome = install_frameless(window, "MCP Control Panel")
    layout.addWidget(chrome.title_bar)
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QWidget,
)

GRIP = 6           # thickness of the invisible resize strips, in pixels
BAR_HEIGHT = 40

# Palette, kept in sync with theme.qss.
ICON = QColor("#a1a1aa")
ICON_HOVER = QColor("#fafafa")
HOVER_BG = QColor("#1f1f23")
CLOSE_BG = QColor("#b91c1c")

_EDGES = (
    (Qt.LeftEdge, Qt.SizeHorCursor),
    (Qt.RightEdge, Qt.SizeHorCursor),
    (Qt.TopEdge, Qt.SizeVerCursor),
    (Qt.BottomEdge, Qt.SizeVerCursor),
    (Qt.LeftEdge | Qt.TopEdge, Qt.SizeFDiagCursor),
    (Qt.RightEdge | Qt.BottomEdge, Qt.SizeFDiagCursor),
    (Qt.RightEdge | Qt.TopEdge, Qt.SizeBDiagCursor),
    (Qt.LeftEdge | Qt.BottomEdge, Qt.SizeBDiagCursor),
)


class _Grip(QWidget):
    """An invisible strip along one edge or corner that starts a resize."""

    def __init__(self, window: QWidget, edges, cursor) -> None:
        super().__init__(window)
        self._window = window
        self._edges = edges
        self.setCursor(cursor)
        self.setAttribute(Qt.WA_NoSystemBackground)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() != Qt.LeftButton:
            return
        handle = self._window.windowHandle()
        if handle is not None:
            handle.startSystemResize(self._edges)


class WindowButton(QAbstractButton):
    """A caption button whose icon is drawn, not typed.

    `kind` is one of: minimize, maximize, restore, close.
    """

    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind = kind
        self._hovered = False
        self.setFixedSize(34, 26)
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_Hover, True)

    def set_kind(self, kind: str) -> None:
        self.kind = kind
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._hovered = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._hovered = False
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        if self._hovered:
            background = CLOSE_BG if self.kind == "close" else HOVER_BG
            painter.setPen(Qt.NoPen)
            painter.setBrush(background)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 6, 6)

        colour = ICON_HOVER if self._hovered else ICON
        pen = QPen(colour)
        pen.setWidthF(1.3)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        centre = QRectF(self.rect()).center()
        size = 9.0
        box = QRectF(0, 0, size, size)
        box.moveCenter(centre)

        if self.kind == "minimize":
            y = centre.y()
            painter.drawLine(box.left(), y, box.right(), y)
        elif self.kind == "maximize":
            painter.drawRoundedRect(box, 1.5, 1.5)
        elif self.kind == "restore":
            back = QRectF(box).adjusted(2.5, -2.5, 2.5, -2.5)
            painter.drawRoundedRect(back, 1.5, 1.5)
            front = QRectF(box).adjusted(-2.5, 2.5, -2.5, 2.5)
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(front, 1.5, 1.5)
        else:  # close
            painter.drawLine(box.topLeft(), box.bottomRight())
            painter.drawLine(box.topRight(), box.bottomLeft())


class TitleBar(QWidget):
    """Draggable bar with the window title and the window buttons."""

    def __init__(
        self,
        window: QWidget,
        title: str,
        show_maximize: bool = True,
    ) -> None:
        super().__init__(window)
        self._window = window
        self._maximize: WindowButton | None = None
        self.setObjectName("titleBar")
        self.setFixedHeight(BAR_HEIGHT)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 8, 0)
        layout.setSpacing(10)

        dot = QLabel()
        dot.setObjectName("titleDot")
        dot.setFixedSize(8, 8)
        layout.addWidget(dot)

        self._title = QLabel(title)
        self._title.setObjectName("titleText")
        layout.addWidget(self._title)

        self._slot = QHBoxLayout()
        self._slot.setContentsMargins(0, 0, 0, 0)
        self._slot.setSpacing(8)
        layout.addLayout(self._slot)

        layout.addStretch(1)

        if show_maximize:
            minimize = WindowButton("minimize", self)
            minimize.clicked.connect(window.showMinimized)
            layout.addWidget(minimize)

            self._maximize = WindowButton("maximize", self)
            self._maximize.clicked.connect(self.toggle_maximized)
            layout.addWidget(self._maximize)

        close = WindowButton("close", self)
        close.clicked.connect(window.close)
        layout.addWidget(close)

    def add_widget(self, widget: QWidget) -> QWidget:
        """Place a widget (a status pill, say) next to the title."""
        self._slot.addWidget(widget)
        return widget

    def set_title(self, title: str) -> None:
        self._title.setText(title)

    def sync_state(self) -> None:
        if self._maximize is not None:
            self._maximize.set_kind(
                "restore" if self._window.isMaximized() else "maximize"
            )

    def toggle_maximized(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()
        self.sync_state()

    # --- dragging --------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() != Qt.LeftButton:
            return
        handle = self._window.windowHandle()
        if handle is not None:
            handle.startSystemMove()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.LeftButton and self._maximize is not None:
            self.toggle_maximized()


class _Chrome(QObject):
    """Keeps the resize grips and the maximise icon in sync with the window."""

    def __init__(self, window: QWidget, title_bar: TitleBar) -> None:
        super().__init__(window)
        self.window = window
        self.title_bar = title_bar
        self._grips = [_Grip(window, edges, cursor) for edges, cursor in _EDGES]
        window.installEventFilter(self)
        self._sync()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt naming
        if watched is self.window and event.type() in (
            QEvent.Resize,
            QEvent.Show,
            QEvent.WindowStateChange,
        ):
            self._sync()
        return False

    def _sync(self) -> None:
        self.title_bar.sync_state()
        self._square_when_maximized()
        self._layout_grips()

    def _square_when_maximized(self) -> None:
        """Rounded corners look wrong edge-to-edge, so drop them maximised."""
        shell = self.window.findChild(QWidget, "windowShell")
        if shell is None:
            return
        maximized = self.window.isMaximized()
        if shell.property("maximized") == maximized:
            return
        shell.setProperty("maximized", maximized)
        shell.style().unpolish(shell)
        shell.style().polish(shell)

    def _layout_grips(self) -> None:
        width = self.window.width()
        height = self.window.height()
        maximized = self.window.isMaximized()

        # left, right, top, bottom, then the four corners
        boxes = [
            (0, GRIP, GRIP, height - 2 * GRIP),
            (width - GRIP, GRIP, GRIP, height - 2 * GRIP),
            (GRIP, 0, width - 2 * GRIP, GRIP),
            (GRIP, height - GRIP, width - 2 * GRIP, GRIP),
            (0, 0, GRIP, GRIP),
            (width - GRIP, height - GRIP, GRIP, GRIP),
            (width - GRIP, 0, GRIP, GRIP),
            (0, height - GRIP, GRIP, GRIP),
        ]
        for grip, box in zip(self._grips, boxes):
            # A maximized window must not be resizable by its edges.
            grip.setVisible(not maximized)
            grip.setGeometry(*box)
            grip.raise_()


def install_frameless(
    window: QWidget,
    title: str,
    show_maximize: bool = True,
) -> _Chrome:
    """Strip the native frame and return the chrome (title bar + grips).

    The caller is responsible for putting `chrome.title_bar` at the top of
    the window's own layout, inside a widget named "windowShell".
    """
    window.setWindowFlag(Qt.FramelessWindowHint, True)
    # Needed for the rounded corners of the shell to show as transparent
    # rather than as black wedges.
    window.setAttribute(Qt.WA_TranslucentBackground, True)
    window.setWindowTitle(title)
    title_bar = TitleBar(window, title, show_maximize=show_maximize)
    return _Chrome(window, title_bar)
