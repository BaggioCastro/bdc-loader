"""
icons.py

Small UI icons drawn with QPainter. They render the same whether or not the
system has emoji fonts, an icon theme, or the Qt SVG image plugin.

Each function takes a color (any QColor-compatible value) and returns a QIcon
with 16 px and 32 px pixmaps.
"""

from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF

_BASE = 16


def _make_icon(draw, color, width=1.6, same_when_disabled=False):
    icon = QIcon()
    for scale in (1, 2):
        pixmap = QPixmap(_BASE * scale, _BASE * scale)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(scale, scale)
        pen = QPen(QColor(color), width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        draw(painter)
        painter.end()
        icon.addPixmap(pixmap)
        if same_when_disabled:
            icon.addPixmap(pixmap, QIcon.Mode.Disabled)
    return icon


def _polyline(painter, *points):
    painter.drawPolyline(QPolygonF([QPointF(x, y) for x, y in points]))


def copy_icon(color="#24292f"):
    """Two overlapping sheets."""

    def draw(painter):
        back = QRectF(5.5, 1.5, 8.5, 10)
        front = QRectF(2, 4.5, 8.5, 10)
        painter.drawRoundedRect(back, 1.5, 1.5)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.fillRect(front.adjusted(-1, -1, 1, 1), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.drawRoundedRect(front, 1.5, 1.5)

    return _make_icon(draw, color)


def zoom_icon(color="#24292f"):
    """Magnifying glass."""

    def draw(painter):
        painter.drawEllipse(QPointF(6.5, 6.5), 4.5, 4.5)
        pen = painter.pen()
        pen.setWidthF(2.2)
        painter.setPen(pen)
        painter.drawLine(QPointF(10, 10), QPointF(14, 14))

    return _make_icon(draw, color)


def download_icon(color="#ffffff"):
    """Arrow pointing down into a tray."""

    def draw(painter):
        painter.drawLine(QPointF(8, 2), QPointF(8, 10.5))
        _polyline(painter, (4.5, 7), (8, 10.5), (11.5, 7))
        _polyline(painter, (2.5, 11), (2.5, 14), (13.5, 14), (13.5, 11))

    return _make_icon(draw, color, width=1.8)


def check_icon(color="#ffffff"):
    """Check mark. Keeps its color on disabled buttons, where it marks a finished state."""

    def draw(painter):
        _polyline(painter, (3, 8.5), (6.5, 12), (13, 4.5))

    return _make_icon(draw, color, width=2.0, same_when_disabled=True)


def crosshair_icon(color="#24292f"):
    """Circle with a center dot and four ticks, for picking a point on the map."""

    def draw(painter):
        painter.drawEllipse(QPointF(8, 8), 5, 5)
        for (x1, y1), (x2, y2) in (((8, 1), (8, 4)), ((8, 12), (8, 15)), ((1, 8), (4, 8)), ((12, 8), (15, 8))):
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        painter.setBrush(QColor(color))
        painter.drawEllipse(QPointF(8, 8), 1.2, 1.2)

    return _make_icon(draw, color)


def plus_icon(color="#24292f"):
    """Plus sign."""

    def draw(painter):
        painter.drawLine(QPointF(8, 3), QPointF(8, 13))
        painter.drawLine(QPointF(3, 8), QPointF(13, 8))

    return _make_icon(draw, color, width=1.8)


def trash_icon(color="#24292f"):
    """Trash can with lid."""

    def draw(painter):
        painter.drawLine(QPointF(2.5, 4), QPointF(13.5, 4))
        _polyline(painter, (6, 4), (6, 2.5), (10, 2.5), (10, 4))
        _polyline(painter, (4, 4), (4.8, 14), (11.2, 14), (12, 4))
        painter.drawLine(QPointF(6.8, 6.5), QPointF(6.8, 11.5))
        painter.drawLine(QPointF(9.2, 6.5), QPointF(9.2, 11.5))

    return _make_icon(draw, color, width=1.4)


def minimize_icon(color="#ffffff"):
    """Horizontal bar at the bottom: collapse to the title bar."""

    def draw(painter):
        painter.drawLine(QPointF(4, 12), QPointF(12, 12))

    return _make_icon(draw, color, width=2.0)


def restore_icon(color="#ffffff"):
    """Single window outline: expand back from the title bar."""

    def draw(painter):
        painter.drawRect(QRectF(3.5, 3.5, 9, 9))
        painter.drawLine(QPointF(3.5, 5.5), QPointF(12.5, 5.5))

    return _make_icon(draw, color, width=1.4)


def float_icon(color="#ffffff"):
    """Window with an arrow leaving it: detach a docked panel."""

    def draw(painter):
        _polyline(painter, (8, 3), (3, 3), (3, 13), (13, 13), (13, 8))
        painter.drawLine(QPointF(7.5, 8.5), QPointF(13, 3))
        _polyline(painter, (9.5, 3), (13, 3), (13, 6.5))

    return _make_icon(draw, color, width=1.4)


def dock_icon(color="#ffffff"):
    """Window with an arrow entering it: attach a floating panel."""

    def draw(painter):
        _polyline(painter, (8, 3), (3, 3), (3, 13), (13, 13), (13, 8))
        painter.drawLine(QPointF(13, 3), QPointF(7.5, 8.5))
        _polyline(painter, (7.5, 5), (7.5, 8.5), (11, 8.5))

    return _make_icon(draw, color, width=1.4)


def close_icon(color="#ffffff"):
    """Diagonal cross."""

    def draw(painter):
        painter.drawLine(QPointF(4, 4), QPointF(12, 12))
        painter.drawLine(QPointF(12, 4), QPointF(4, 12))

    return _make_icon(draw, color, width=1.8)


def _brazil(painter, w, h):
    painter.setBrush(QColor("#009c3b"))
    painter.drawRect(QRectF(0, 0, w, h))
    painter.setBrush(QColor("#ffdf00"))
    mx, my = w * 0.09, h * 0.13
    painter.drawPolygon(
        QPolygonF([QPointF(w / 2, my), QPointF(w - mx, h / 2), QPointF(w / 2, h - my), QPointF(mx, h / 2)])
    )
    painter.setBrush(QColor("#002776"))
    radius = h * 0.26
    painter.drawEllipse(QPointF(w / 2, h / 2), radius, radius)
    painter.setPen(QPen(QColor("#ffffff"), h * 0.05))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(QRectF(w / 2 - radius * 1.9, h / 2 - radius * 0.55, radius * 3.8, radius * 3.8), 62 * 16, 56 * 16)


def _united_states(painter, w, h):
    stripe = h / 13
    for i in range(13):
        painter.setBrush(QColor("#b22234" if i % 2 == 0 else "#ffffff"))
        painter.drawRect(QRectF(0, i * stripe, w, stripe + 0.3))
    painter.setBrush(QColor("#3c3b6e"))
    canton = QRectF(0, 0, w * 0.42, stripe * 7)
    painter.drawRect(canton)
    painter.setBrush(QColor("#ffffff"))
    for row in range(4):
        for col in range(5):
            x = canton.width() * (col + 0.5) / 5
            y = canton.height() * (row + 0.5) / 4
            painter.drawEllipse(QPointF(x, y), 0.45, 0.45)


_FLAGS = {"pt": _brazil, "en": _united_states}


def flag_icon(language, width=24, height=16):
    """The flag of the language's country (Brazil for "pt", the United States for "en"),
    bright when the button is checked and faded when it is not."""
    icon = QIcon()
    for scale in (1, 2):
        for state, opacity in ((QIcon.State.On, 1.0), (QIcon.State.Off, 0.45)):
            pixmap = QPixmap(width * scale, height * scale)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.scale(scale, scale)
            painter.setOpacity(opacity)
            painter.setPen(Qt.PenStyle.NoPen)
            _FLAGS[language](painter, width, height)
            painter.end()
            icon.addPixmap(pixmap, QIcon.Mode.Normal, state)
    return icon
