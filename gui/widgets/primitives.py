"""Small building blocks shared by every screen.

The vocabulary is deliberately small, so screens read declaratively:

  Page      a scrollable column with a title, a subtitle and groups
  Group     a titled card of rows, with hairline dividers between them
  SettingRow  title and description on the left, controls on the right
  Badge     a status pill with a coloured dot
  Switch, Segmented, GlyphButton, NavButton - the controls

Buttons come in four variants: "default" (the one obvious action, light),
"secondary" (everything beside it), "destructive" (throws work away) and
"ghost" (quiet, text-only). Colours live in gui.widgets.tokens.

Card, CopyField and CollapsibleCard are the older, field-style pieces;
the setup guide still uses them.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui.widgets.icons import draw_icon
from gui.widgets.tokens import COLORS, GLOW_ALPHA, GLOW_RGB, TONE_DOT


def repolish(widget: QWidget) -> None:
    """Re-evaluate the stylesheet after a dynamic property change."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


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
    """Status pill. Tone is one of: neutral, success, warning, danger.

    A small dot in the tone's colour leads the text, so the state reads at
    a glance even where the pill itself is quiet.
    """

    def __init__(self, text: str = "", tone: str = "neutral", dot: bool = True) -> None:
        super().__init__(text)
        self._dot = dot
        self.setProperty("dot", "true" if dot else "false")
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.set_state(text, tone)

    def set_state(self, text: str, tone: str = "neutral") -> None:
        if self.text() == text and self.property("badge") == tone:
            return
        self.setText(text)
        self.setProperty("badge", tone)
        repolish(self)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().paintEvent(event)
        if not self._dot:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        colour = QColor(TONE_DOT.get(str(self.property("badge")), TONE_DOT["neutral"]))
        centre_x, centre_y = 12.0, self.height() / 2
        halo = QColor(colour)
        halo.setAlpha(46)
        painter.setBrush(halo)
        painter.drawEllipse(QRectF(centre_x - 5.0, centre_y - 5.0, 10.0, 10.0))
        painter.setBrush(colour)
        painter.drawEllipse(QRectF(centre_x - 3.0, centre_y - 3.0, 6.0, 6.0))


class Switch(QAbstractButton):
    """A shadcn-style toggle: a small track with a sliding knob.

    Drawn with QPainter rather than styled as a QCheckBox, because the
    checkbox indicator is a platform-drawn image that a stylesheet can
    only replace with a bitmap - and any bitmap looks wrong at the user's
    display scaling. `toggled(bool)` behaves like any checkable button.
    """

    TRACK_ON = QColor(COLORS["prim_bottom"])
    TRACK_OFF = QColor(COLORS["btn_bottom"])
    TRACK_DISABLED = QColor(COLORS["btn_disabled"])
    BORDER = QColor(COLORS["btn_edge"])
    BORDER_HI = QColor(COLORS["btn_hi"])
    KNOB_ON = QColor(COLORS["prim_text"])
    KNOB_OFF = QColor(COLORS["muted"])
    KNOB_DISABLED = QColor(COLORS["faint"])

    def __init__(self, checked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setFixedSize(36, 20)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        return QSize(36, 20)

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
        if enabled and not on:
            # The same light-from-above edge as the buttons: a brighter
            # hairline along the top half of the track.
            painter.save()
            painter.setClipRect(QRectF(track.left(), track.top() - 1, track.width(), radius))
            painter.setPen(QPen(self.BORDER_HI, 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(track, radius, radius)
            painter.restore()

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


class CollapsibleCard(QFrame):
    """Bordered surface with an expandable/collapsible body and a clickable header.

    Displays an arrow indicator (▾ expanded, ▸ collapsed), title, optional
    description, and extra widgets (e.g. Badges) in the header.
    """

    def __init__(
        self,
        title: str,
        description: str = "",
        collapsed: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self._collapsed = collapsed

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 14, 18, 14)
        outer.setSpacing(10)

        # Clickable header container
        self._header_widget = QWidget()
        self._header_widget.setCursor(Qt.PointingHandCursor)
        self._header = QHBoxLayout(self._header_widget)
        self._header.setContentsMargins(0, 0, 0, 0)
        self._header.setSpacing(10)

        # Indicator
        self._arrow = QLabel("▾" if not collapsed else "▸")
        self._arrow.setStyleSheet("color: %s; font-size: 13px; font-weight: bold;" % COLORS["muted"])
        self._arrow.setFixedWidth(14)
        self._header.addWidget(self._arrow)

        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(2)
        self._title_lbl = label(title, "cardTitle")
        titles.addWidget(self._title_lbl)
        if description:
            self._desc_lbl = label(description, "cardDescription")
            titles.addWidget(self._desc_lbl)
        else:
            self._desc_lbl = None

        self._header.addLayout(titles, 1)

        self._extras = QHBoxLayout()
        self._extras.setContentsMargins(0, 0, 0, 0)
        self._extras.setSpacing(8)
        self._header.addLayout(self._extras)

        outer.addWidget(self._header_widget)

        # Body container
        self._body_widget = QWidget()
        self._body = QVBoxLayout(self._body_widget)
        self._body.setContentsMargins(0, 4, 0, 0)
        self._body.setSpacing(10)
        outer.addWidget(self._body_widget)

        if collapsed:
            self._body_widget.setVisible(False)

        self._header_widget.mousePressEvent = self._on_header_clicked

    def _on_header_clicked(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.toggle()
            event.accept()
        else:
            super(QWidget, self._header_widget).mousePressEvent(event)

    def toggle(self) -> None:
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self._body_widget.setVisible(not collapsed)
        self._arrow.setText("▸" if collapsed else "▾")

    def is_collapsed(self) -> bool:
        return self._collapsed

    def header_extra(self, widget: QWidget) -> QWidget:
        self._extras.addWidget(widget, 0, Qt.AlignVCenter | Qt.AlignRight)
        return widget

    def add(self, widget: QWidget) -> QWidget:
        self._body.addWidget(widget)
        return widget

    def add_layout(self, layout) -> None:
        self._body.addLayout(layout)


# --- layout pieces of the redesigned panel ---------------------------------


class ElidedLabel(QLabel):
    """One line of text that shortens itself (with ...) instead of
    widening the window. The full text stays available as a tooltip.

    Used for URLs and paths, which have no spaces to wrap at.
    """

    def __init__(self, text: str = "", variant: str = "", mode=Qt.ElideMiddle) -> None:
        super().__init__()
        self._full = ""
        self._mode = mode
        if variant:
            self.setProperty("variant", variant)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(40)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt naming
        self._full = text or ""
        self.setToolTip(self._full if len(self._full) > 40 else "")
        self._elide()

    def text(self) -> str:
        return self._full

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        width = max(self.width() - 2, 10)
        shown = self.fontMetrics().elidedText(self._full, self._mode, width)
        QLabel.setText(self, shown)


class GlyphButton(QPushButton):
    """A button with a painted line icon before its text."""

    def __init__(self, text: str, glyph: str, variant: str = "secondary",
                 tooltip: str = "") -> None:
        super().__init__(text)
        self._glyph = glyph
        self.setProperty("variant", variant)
        self.setProperty("glyph", "true")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setAttribute(Qt.WA_Hover, True)
        if tooltip:
            self.setToolTip(tooltip)

    def set_glyph(self, glyph: str) -> None:
        if glyph != self._glyph:
            self._glyph = glyph
            self.update()

    def glyph_colour(self) -> QColor:
        if not self.isEnabled():
            return QColor(COLORS["faint"])
        if self.property("variant") == "default":
            return QColor(COLORS["prim_text"])
        return QColor(COLORS["text"] if self.underMouse() else COLORS["text_2"])

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().paintEvent(event)
        painter = QPainter(self)
        size = 15.0
        box = QRectF(12.0, (self.height() - size) / 2, size, size)
        draw_icon(painter, self._glyph, box, self.glyph_colour())


class NavButton(GlyphButton):
    """A sidebar entry. The selected one gets the accent colour - on the
    icon only, which is all the orange the main window needs."""

    def __init__(self, text: str, glyph: str) -> None:
        super().__init__(text, glyph, variant="nav")
        self.setObjectName("navItem")
        self.setCheckable(True)
        self.setFocusPolicy(Qt.NoFocus)

    def glyph_colour(self) -> QColor:
        if self.isChecked():
            return QColor(COLORS["accent"])
        return QColor(COLORS["text"] if self.underMouse() else COLORS["muted"])


class Segmented(QFrame):
    """A row of mutually exclusive options in one pill (Default | Verbose)."""

    changed = Signal(str)

    def __init__(self, options: list, current: str = "") -> None:
        super().__init__()
        self.setObjectName("segmented")
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict = {}
        for key, text in options:
            option = QPushButton(text)
            option.setObjectName("segment")
            option.setCheckable(True)
            option.setCursor(Qt.PointingHandCursor)
            option.setFocusPolicy(Qt.NoFocus)
            option.clicked.connect(lambda _checked=False, k=key: self._pick(k))
            self._group.addButton(option)
            self._buttons[key] = option
            layout.addWidget(option)
        self.set_value(current or (options[0][0] if options else ""))

    def value(self) -> str:
        for key, option in self._buttons.items():
            if option.isChecked():
                return key
        return ""

    def set_value(self, key: str) -> None:
        option = self._buttons.get(key)
        if option is not None and not option.isChecked():
            option.setChecked(True)

    def _pick(self, key: str) -> None:
        self.changed.emit(key)


class SettingRow(QWidget):
    """One line of a group: what it is on the left, the controls on the right."""

    def __init__(self, title: str, description: str = "", mono: bool = False) -> None:
        super().__init__()
        self.setObjectName("settingRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 11, 14, 11)
        layout.setSpacing(16)

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(2)
        self._title = label(title, "rowTitle")
        self._title.setWordWrap(False)
        text.addWidget(self._title)
        if mono:
            self._description = ElidedLabel(description, "rowMono")
        else:
            self._description = label(description, "rowDescription")
        text.addWidget(self._description)
        # hide() only: setVisible(True) on a widget that has no parent yet
        # opens it as its own top-level window for a moment.
        if not description:
            self._description.hide()
        layout.addLayout(text, 1)

        self._controls = QHBoxLayout()
        self._controls.setContentsMargins(0, 0, 0, 0)
        self._controls.setSpacing(8)
        layout.addLayout(self._controls, 0)

    def add(self, widget: QWidget) -> QWidget:
        self._controls.addWidget(widget, 0, Qt.AlignVCenter)
        return widget

    def insert(self, index: int, widget: QWidget) -> QWidget:
        self._controls.insertWidget(index, widget, 0, Qt.AlignVCenter)
        return widget

    def set_title(self, text: str) -> None:
        self._title.setText(text)

    def set_description(self, text: str) -> None:
        self._description.setText(text)
        self._description.setVisible(bool(text))

    def description(self) -> str:
        return self._description.text()


class Group(QWidget):
    """A titled card of rows, separated by hairlines."""

    def __init__(self, title: str = "", caption: str = "") -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        self._extras = QHBoxLayout()
        self._extras.setContentsMargins(0, 0, 0, 0)
        self._extras.setSpacing(8)
        self._title_label = label(title, "groupTitle")
        if title:
            head = QHBoxLayout()
            head.setContentsMargins(2, 0, 0, 0)
            head.setSpacing(8)
            head.addWidget(self._title_label, 1, Qt.AlignBottom)
            head.addLayout(self._extras)
            outer.addLayout(head)

        self._card = QFrame()
        self._card.setObjectName("group")
        self._rows = QVBoxLayout(self._card)
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(0)
        outer.addWidget(self._card, 1)

        self._caption = label(caption, "caption")
        self._caption.setContentsMargins(2, 0, 0, 0)
        outer.addWidget(self._caption)
        if not caption:
            self._caption.hide()

    def header_extra(self, widget: QWidget) -> QWidget:
        self._extras.addWidget(widget, 0, Qt.AlignVCenter)
        return widget

    def set_title(self, text: str) -> None:
        self._title_label.setText(text)

    def add_row(self, row: QWidget, stretch: int = 0) -> QWidget:
        if self._rows.count():
            self._rows.addWidget(separator_line())
        self._rows.addWidget(row, stretch)
        return row

    def clear_rows(self) -> None:
        while self._rows.count():
            item = self._rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # Hidden at once: deleteLater only runs on the next loop turn,
                # and until then the old row would still paint under the new.
                widget.hide()
                widget.deleteLater()

    def set_caption(self, text: str) -> None:
        self._caption.setText(text)
        self._caption.setVisible(bool(text))


def separator_line() -> QFrame:
    line = QFrame()
    line.setObjectName("divider")
    line.setFrameShape(QFrame.NoFrame)
    return line


class Page(QWidget):
    """One screen of the main window: a header and a column of groups.

    The column stops growing at a readable width and stays centred on
    wide windows. `scroll=False` is for pages whose content scrolls by
    itself (the activity log); `wide=True` lets such a page use the whole
    window width.
    """

    MAX_WIDTH = 880

    def __init__(
        self, title: str, subtitle: str = "", scroll: bool = True, wide: bool = False
    ) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        holder = QWidget()
        centre = QHBoxLayout(holder)
        centre.setContentsMargins(0, 0, 0, 0)
        centre.setSpacing(0)
        column = QWidget()
        if not wide:
            column.setMaximumWidth(self.MAX_WIDTH)
        centre.addStretch(0)
        centre.addWidget(column, 1)
        centre.addStretch(0)

        self._column = QVBoxLayout(column)
        self._column.setContentsMargins(36, 28, 36, 32)
        self._column.setSpacing(22)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(10)
        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(4)
        titles.addWidget(label(title, "pageTitle"))
        self._subtitle = label(subtitle, "pageSubtitle")
        titles.addWidget(self._subtitle)
        if not subtitle:
            self._subtitle.hide()
        head.addLayout(titles, 1)
        self._extras = QHBoxLayout()
        self._extras.setContentsMargins(0, 0, 0, 0)
        self._extras.setSpacing(8)
        head.addLayout(self._extras)
        self._column.addLayout(head)

        if scroll:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QScrollArea.NoFrame)
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            area.setWidget(holder)
            # A viewport fills itself from the palette unless told not to,
            # which would paint a flat slab over the backdrop's glow.
            area.viewport().setAutoFillBackground(False)
            holder.setAutoFillBackground(False)
            outer.addWidget(area)
        else:
            outer.addWidget(holder)

    def header_extra(self, widget: QWidget) -> QWidget:
        self._extras.addWidget(widget, 0, Qt.AlignTop)
        return widget

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self._column.addWidget(widget, stretch)
        return widget

    def add_layout(self, layout) -> None:
        self._column.addLayout(layout)

    def finish(self) -> None:
        """Push the content to the top on tall windows."""
        self._column.addStretch(1)

    def set_subtitle(self, text: str) -> None:
        self._subtitle.setText(text)
        self._subtitle.setVisible(bool(text))


class Backdrop(QWidget):
    """The content panel: a rounded graphite surface with a faint cool
    glow behind its top edge, the one bit of depth on the screen."""

    RADIUS = 10.0

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("backdrop")
        self.setAttribute(Qt.WA_StyledBackground, False)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(COLORS["panel"]))
        painter.drawRoundedRect(rect, self.RADIUS, self.RADIUS)

        painter.save()
        outline = QPainterPath()
        outline.addRoundedRect(rect, self.RADIUS, self.RADIUS)
        painter.setClipPath(outline)
        width = rect.width()
        radius = min(max(width * 0.52, 320.0), 640.0)
        painter.translate(rect.center().x(), rect.top() - radius * 0.12)
        painter.scale(1.0, 0.5)
        glow = QRadialGradient(0.0, 0.0, radius)
        r, g, b = GLOW_RGB
        glow.setColorAt(0.0, QColor(r, g, b, GLOW_ALPHA))
        glow.setColorAt(0.45, QColor(r, g, b, int(GLOW_ALPHA * 0.45)))
        glow.setColorAt(1.0, QColor(r, g, b, 0))
        painter.setBrush(glow)
        painter.drawEllipse(QRectF(-radius, -radius, 2 * radius, 2 * radius))
        painter.restore()

        painter.setPen(QPen(QColor(COLORS["panel_edge"]), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, self.RADIUS, self.RADIUS)


class CopyRow(SettingRow):
    """A row that shows a value (a URL, a path, the token) with a Copy
    button; `secret=True` masks it behind Show/Hide."""

    def __init__(self, title: str, value: str = "", secret: bool = False) -> None:
        super().__init__(title, value or " ", mono=True)
        self._secret = secret
        self._revealed = not secret
        self._value = ""
        self._reveal_button = None
        if secret:
            self._reveal_button = button("Show", "secondary", "Show or hide the value")
            self._reveal_button.clicked.connect(self._toggle_reveal)
            self.add(self._reveal_button)
        self._copy_button = button("Copy", "secondary")
        self._copy_button.clicked.connect(self._copy)
        self.add(self._copy_button)
        self.set_value(value)

    def value(self) -> str:
        return self._value

    def set_value(self, value: str) -> None:
        self._value = value or ""
        self._render()

    def set_copyable(self, enabled: bool) -> None:
        self._copy_button.setEnabled(enabled)

    def _render(self) -> None:
        if self._secret and not self._revealed:
            shown = "\u2022" * min(len(self._value), 32)
        else:
            shown = self._value
        self.set_description(shown or " ")

    def _toggle_reveal(self) -> None:
        self._revealed = not self._revealed
        self._reveal_button.setText("Hide" if self._revealed else "Show")
        self._render()

    def _copy(self) -> None:
        from PySide6.QtCore import QTimer

        QGuiApplication.clipboard().setText(self._value)
        self._copy_button.setText("Copied")
        self._copy_button.setEnabled(False)

        def restore() -> None:
            self._copy_button.setText("Copy")
            self._copy_button.setEnabled(True)

        QTimer.singleShot(1200, restore)
