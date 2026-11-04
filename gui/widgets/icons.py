"""Line icons drawn with QPainter.

No icon font and no image files: glyph fonts get swapped for colour emoji
on Windows, and bitmaps blur at fractional display scaling. Each icon is
a few strokes on a 16 x 16 grid, scaled to whatever box it is given.

    draw_icon(painter, "folder", QRectF(x, y, 16, 16), QColor("#fff"))
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen


def _grid(p: QPainterPath) -> None:
    for x, y in ((2, 2), (9, 2), (2, 9), (9, 9)):
        p.addRoundedRect(QRectF(x, y, 5, 5), 1.4, 1.4)


def _folder(p: QPainterPath) -> None:
    p.moveTo(1.8, 4.2)
    p.quadTo(1.8, 2.8, 3.2, 2.8)
    p.lineTo(6.0, 2.8)
    p.lineTo(7.6, 4.4)
    p.lineTo(12.8, 4.4)
    p.quadTo(14.2, 4.4, 14.2, 5.8)
    p.lineTo(14.2, 11.8)
    p.quadTo(14.2, 13.2, 12.8, 13.2)
    p.lineTo(3.2, 13.2)
    p.quadTo(1.8, 13.2, 1.8, 11.8)
    p.closeSubpath()


def _globe(p: QPainterPath) -> None:
    p.addEllipse(QRectF(2, 2, 12, 12))
    p.addEllipse(QRectF(5.4, 2, 5.2, 12))
    p.moveTo(2.3, 8)
    p.lineTo(13.7, 8)


def _shield(p: QPainterPath) -> None:
    p.moveTo(8, 1.8)
    p.lineTo(13.2, 3.8)
    p.lineTo(13.2, 7.6)
    p.cubicTo(13.2, 10.8, 11, 13, 8, 14.2)
    p.cubicTo(5, 13, 2.8, 10.8, 2.8, 7.6)
    p.lineTo(2.8, 3.8)
    p.closeSubpath()


def _bell(p: QPainterPath) -> None:
    p.moveTo(3.4, 11.4)
    p.lineTo(3.9, 10.6)
    p.lineTo(3.9, 7.2)
    p.cubicTo(3.9, 4.6, 5.7, 2.6, 8, 2.6)
    p.cubicTo(10.3, 2.6, 12.1, 4.6, 12.1, 7.2)
    p.lineTo(12.1, 10.6)
    p.lineTo(12.6, 11.4)
    p.closeSubpath()
    p.moveTo(6.6, 13.6)
    p.lineTo(9.4, 13.6)


def _pulse(p: QPainterPath) -> None:
    p.moveTo(1.5, 8.5)
    p.lineTo(4.6, 8.5)
    p.lineTo(6.4, 3.5)
    p.lineTo(9.4, 12.8)
    p.lineTo(11.2, 8.5)
    p.lineTo(14.5, 8.5)


def _book(p: QPainterPath) -> None:
    p.moveTo(8, 4.2)
    p.cubicTo(6.6, 3.2, 4.4, 2.9, 2, 3.2)
    p.lineTo(2, 12.6)
    p.cubicTo(4.4, 12.3, 6.6, 12.6, 8, 13.6)
    p.cubicTo(9.4, 12.6, 11.6, 12.3, 14, 12.6)
    p.lineTo(14, 3.2)
    p.cubicTo(11.6, 2.9, 9.4, 3.2, 8, 4.2)
    p.closeSubpath()
    p.moveTo(8, 4.2)
    p.lineTo(8, 13.4)


def _play(p: QPainterPath) -> None:
    p.moveTo(5, 3.2)
    p.lineTo(12.6, 8)
    p.lineTo(5, 12.8)
    p.closeSubpath()


def _stop(p: QPainterPath) -> None:
    p.addRoundedRect(QRectF(4, 4, 8, 8), 1.6, 1.6)


def _plus(p: QPainterPath) -> None:
    p.moveTo(8, 3)
    p.lineTo(8, 13)
    p.moveTo(3, 8)
    p.lineTo(13, 8)


def _external(p: QPainterPath) -> None:
    p.moveTo(9.5, 2.5)
    p.lineTo(13.5, 2.5)
    p.lineTo(13.5, 6.5)
    p.moveTo(13.5, 2.5)
    p.lineTo(7.5, 8.5)
    p.moveTo(11.5, 9.5)
    p.lineTo(11.5, 12.5)
    p.quadTo(11.5, 13.5, 10.5, 13.5)
    p.lineTo(3.5, 13.5)
    p.quadTo(2.5, 13.5, 2.5, 12.5)
    p.lineTo(2.5, 5.5)
    p.quadTo(2.5, 4.5, 3.5, 4.5)
    p.lineTo(6.5, 4.5)


_SHAPES = {
    "overview": _grid,
    "projects": _folder,
    "tunnel": _globe,
    "security": _shield,
    "notifications": _bell,
    "activity": _pulse,
    "guide": _book,
    "play": _play,
    "stop": _stop,
    "plus": _plus,
    "external": _external,
}

# Drawn filled rather than stroked.
_FILLED = {"play", "stop"}


def names() -> list:
    return sorted(_SHAPES)


def draw_icon(painter: QPainter, name: str, box: QRectF, colour: QColor,
              width: float = 1.35) -> None:
    shape = _SHAPES.get(name)
    if shape is None:
        return
    path = QPainterPath()
    shape(path)
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    scale = min(box.width(), box.height()) / 16.0
    painter.translate(box.center() - QPointF(8 * scale, 8 * scale))
    painter.scale(scale, scale)
    if name in _FILLED:
        painter.setPen(Qt.NoPen)
        painter.setBrush(colour)
    else:
        pen = QPen(colour, width / scale if scale > 1 else width)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
    painter.drawPath(path)
    painter.restore()
