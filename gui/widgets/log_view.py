"""The activity log: one record per paragraph, wrapped with a hanging indent.

Time and source sit in fixed-width columns; a long message wraps under its
own first character instead of under the time, so wrapped lines never look
like new records. QPlainTextEdit ignores paragraph indents, so this is a
read-only QTextEdit with a block limit.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontMetricsF, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextOption
from PySide6.QtWidgets import QTextEdit

SOURCE_WIDTH = 9   # characters reserved for the source column
GAP = 2            # spaces between columns


class LogView(QTextEdit):
    def __init__(self, max_records: int = 2000) -> None:
        super().__init__()
        self.setObjectName("logView")
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setLineWrapMode(QTextEdit.WidgetWidth)
        self.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.document().setMaximumBlockCount(max_records)
        self._empty = True

    def clear(self) -> None:  # noqa: D401 - Qt override
        super().clear()
        self._empty = True

    def _indent(self) -> float:
        self.ensurePolished()
        prefix = "00:00:00" + " " * GAP + " " * SOURCE_WIDTH + " " * GAP
        return QFontMetricsF(self.font()).horizontalAdvance(prefix)

    def add(self, stamp: str, source: str, message: str, colours: tuple) -> None:
        """Append one record. `colours` = (time, source, message)."""
        bar = self.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 4

        cursor = QTextCursor(self.document())
        cursor.movePosition(QTextCursor.End)
        block = QTextBlockFormat()
        indent = self._indent()
        block.setLeftMargin(indent)
        block.setTextIndent(-indent)
        block.setBottomMargin(2)
        if self._empty:
            cursor.setBlockFormat(block)
            self._empty = False
        else:
            cursor.insertBlock(block)

        source = source[:SOURCE_WIDTH]
        parts = (
            (stamp + " " * GAP, colours[0]),
            (source.ljust(SOURCE_WIDTH) + " " * GAP, colours[1]),
            # Line separators keep a multi-line message in one paragraph,
            # so its continuation lines get the same indent.
            (message.replace("\r\n", "\n").replace("\n", "\u2028"), colours[2]),
        )
        for text, colour in parts:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(colour))
            cursor.insertText(text, fmt)

        if at_bottom:
            bar.setValue(bar.maximum())

    def add_many(self, rows) -> None:
        """Rebuild quickly: rows of (stamp, source, message, colours)."""
        self.setUpdatesEnabled(False)
        try:
            for row in rows:
                self.add(*row)
        finally:
            self.setUpdatesEnabled(True)
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
