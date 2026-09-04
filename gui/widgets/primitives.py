"""Small building blocks shared by every screen.

These mirror the shadcn/ui vocabulary (Card, Badge, Button variants,
Field) so the rest of the GUI reads declaratively instead of drowning in
layout code.

Only two button variants are used across the app - "default" for the one
obvious action of a card and "secondary" for everything beside it, plus
"destructive" for actions that throw work away. Keeping the vocabulary
this small is what stops a row of buttons from looking accidental.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


def label(text: str, variant: str = "") -> QLabel:
    """A QLabel tagged with a style variant used by theme.qss."""
    widget = QLabel(text)
    if variant:
        widget.setProperty("variant", variant)
    widget.setWordWrap(True)
    return widget


def button(text: str, variant: str = "default", tooltip: str = "") -> QPushButton:
    """A QPushButton in one of the shadcn variants."""
    widget = QPushButton(text)
    widget.setProperty("variant", variant)
    widget.setCursor(Qt.PointingHandCursor)
    # Buttons are clicked, not tabbed through; this also keeps the initial
    # focus from landing on a control and giving it a highlight ring.
    widget.setFocusPolicy(Qt.ClickFocus)
    if tooltip:
        widget.setToolTip(tooltip)
    return widget


def separator() -> QFrame:
    line = QFrame()
    line.setObjectName("separator")
    line.setFrameShape(QFrame.NoFrame)
    return line


def row(*widgets: QWidget, spacing: int = 8, stretch_last: bool = False) -> QWidget:
    """Horizontal container; convenience wrapper around QHBoxLayout."""
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    for widget in widgets:
        layout.addWidget(widget)
    if not stretch_last:
        layout.addStretch(1)
    return container


class Badge(QLabel):
    """Status pill. Tone is one of: neutral, success, warning, danger."""

    def __init__(self, text: str = "", tone: str = "neutral") -> None:
        super().__init__(text)
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.set_state(text, tone)

    def set_state(self, text: str, tone: str = "neutral") -> None:
        if self.text() == text and self.property("badge") == tone:
            return
        self.setText(text)
        self.setProperty("badge", tone)
        # Re-evaluate the stylesheet after a dynamic property change.
        self.style().unpolish(self)
        self.style().polish(self)


class Switch(QAbstractButton):
    """A shadcn-style toggle: a small track with a sliding knob.

    Drawn with QPainter rather than styled as a QCheckBox, because the
    checkbox indicator is a platform-drawn image that a stylesheet can
    only replace with a bitmap - and any bitmap looks wrong at the user's
    display scaling. `toggled(bool)` behaves like any checkable button.
    """

    TRACK_ON = QColor("#e4e4e7")
    TRACK_OFF = QColor("#232327")
    TRACK_DISABLED = QColor("#18181b")
    BORDER = QColor("#3f3f46")
    KNOB_ON = QColor("#18181b")
    KNOB_OFF = QColor("#a1a1aa")
    KNOB_DISABLED = QColor("#5b5b63")

    def __init__(self, checked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setFixedSize(38, 22)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        return QSize(38, 22)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        on = self.isChecked()
        enabled = self.isEnabled()

        track = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = track.height() / 2
        if not enabled:
            fill = self.TRACK_DISABLED
        else:
            fill = self.TRACK_ON if on else self.TRACK_OFF
        painter.setPen(QPen(self.BORDER, 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(track, radius, radius)

        diameter = track.height() - 6
        knob = QRectF(0, 0, diameter, diameter)
        knob.moveTop(track.center().y() - diameter / 2)
        knob.moveLeft(
            track.right() - diameter - 3 if on else track.left() + 3
        )
        if not enabled:
            knob_colour = self.KNOB_DISABLED
        else:
            knob_colour = self.KNOB_ON if on else self.KNOB_OFF
        painter.setPen(Qt.NoPen)
        painter.setBrush(knob_colour)
        painter.drawEllipse(knob)


class Card(QFrame):
    """Bordered surface with a title, optional description and a body.

    Use `add(widget)` to append to the body, and `header_extra(widget)` to
    drop something (usually a Badge or a button) on the title row.
    """

    def __init__(self, title: str, description: str = "") -> None:
        super().__init__()
        self.setObjectName("card")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(12)

        self._header = QHBoxLayout()
        self._header.setContentsMargins(0, 0, 0, 0)
        self._header.setSpacing(8)

        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(2)
        titles.addWidget(label(title, "cardTitle"))
        if description:
            titles.addWidget(label(description, "cardDescription"))

        self._header.addLayout(titles, 1)
        outer.addLayout(self._header)

        self._body = QVBoxLayout()
        self._body.setContentsMargins(0, 0, 0, 0)
        self._body.setSpacing(10)
        outer.addLayout(self._body)

    def header_extra(self, widget: QWidget) -> QWidget:
        self._header.addWidget(widget, 0, Qt.AlignTop | Qt.AlignRight)
        return widget

    def add(self, widget: QWidget) -> QWidget:
        self._body.addWidget(widget)
        return widget

    def add_layout(self, layout) -> None:
        self._body.addLayout(layout)


class CopyField(QWidget):
    """Read-only value with a copy button - used for URLs and the token.

    `secret=True` masks the value until the user reveals it.
    """

    def __init__(
        self,
        caption: str,
        value: str = "",
        secret: bool = False,
    ) -> None:
        super().__init__()
        self._secret = secret
        self._revealed = not secret

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        if caption:
            layout.addWidget(label(caption, "label"))

        line = QHBoxLayout()
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)

        self._field = QLineEdit(value)
        self._field.setReadOnly(True)
        self._field.setCursorPosition(0)
        # Read-only display fields should not grab focus when a window
        # opens, which is what put a text cursor in the first URL box.
        self._field.setFocusPolicy(Qt.ClickFocus)
        line.addWidget(self._field, 1)

        if secret:
            self._reveal_button = button(
                "Show", "secondary", "Show or hide the value"
            )
            self._reveal_button.clicked.connect(self._toggle_reveal)
            line.addWidget(self._reveal_button)

        self._copy_button = button("Copy", "secondary")
        self._copy_button.clicked.connect(self._copy)
        line.addWidget(self._copy_button)

        layout.addLayout(line)
        self.set_value(value)

    # --- api -------------------------------------------------------------

    def value(self) -> str:
        return self._value

    def set_value(self, value: str) -> None:
        self._value = value or ""
        self._render()

    def set_enabled(self, enabled: bool) -> None:
        self._field.setEnabled(enabled)
        self._copy_button.setEnabled(enabled)

    # --- internals -------------------------------------------------------

    def _render(self) -> None:
        if self._secret and not self._revealed:
            self._field.setText("\u2022" * min(len(self._value), 44))
        else:
            self._field.setText(self._value)
        self._field.setCursorPosition(0)

    def _toggle_reveal(self) -> None:
        self._revealed = not self._revealed
        self._reveal_button.setText("Hide" if self._revealed else "Show")
        self._render()

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self._value)
        self._copy_button.setText("Copied")
        self._copy_button.setEnabled(False)

        from PySide6.QtCore import QTimer

        def restore() -> None:
            self._copy_button.setText("Copy")
            self._copy_button.setEnabled(True)

        QTimer.singleShot(1200, restore)
