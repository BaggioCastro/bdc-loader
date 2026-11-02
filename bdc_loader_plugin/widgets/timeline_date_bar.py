"""Clickable strip of the dates in a timeline group, with the current date highlighted."""

import logging

_logger = logging.getLogger("bdc_loader")

from qgis.PyQt.QtCore import QPoint, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from qgis.PyQt.QtWidgets import (
    QSizePolicy,
    QToolTip,
    QWidget,
)

from ..qt_compat import event_global_pos


class TimelineDateBar(QWidget):
    """Horizontal date bar with clickable markers and smooth drag support."""

    dateClicked = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dates = []
        self._current = -1
        self._dragging = False
        self._hover_idx = -1
        self.setMinimumHeight(40)
        self.setMaximumHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)

    def set_dates(self, dates, current_idx=0):
        self._dates = dates
        self._current = current_idx
        self.update()

    def _idx_from_x(self, x):
        """Return the nearest date index for a given x position."""
        if not self._dates:
            return -1
        n = len(self._dates)
        w = self.width()
        margin = 40
        if n == 1:
            return 0
        track_w = w - 2 * margin
        if track_w <= 0:
            return 0
        ratio = max(0.0, min(1.0, (x - margin) / track_w))
        return max(0, min(n - 1, round(ratio * (n - 1))))

    def paintEvent(self, event):
        if not self._dates:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()
        n = len(self._dates)
        margin = 40
        y_line = h // 2 + 2

        # Background gradient
        grad = QLinearGradient(0, 0, w, 0)
        grad.setColorAt(0.0, QColor("#e8f0fe"))
        grad.setColorAt(1.0, QColor("#f0f6ff"))
        painter.fillRect(0, 0, w, h, grad)

        # Track line
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#d0d8e8"))
        painter.drawRoundedRect(margin, y_line - 2, w - 2 * margin, 4, 2, 2)

        # Filled track up to current marker
        if n > 1 and self._current >= 0:
            x_cur = margin + int(self._current * (w - 2 * margin) / (n - 1))
            painter.setBrush(QColor("#2e7dd1"))
            painter.drawRoundedRect(margin, y_line - 2, x_cur - margin, 4, 2, 2)

        if n == 0:
            painter.end()
            return

        # Date markers
        for i, d in enumerate(self._dates):
            x = margin + int(i * (w - 2 * margin) / (n - 1)) if n > 1 else w // 2

            if i == self._current:
                # Active marker
                painter.setPen(QPen(QColor("#1a5fa8"), 2))
                painter.setBrush(QColor("#2e7dd1"))
                painter.drawEllipse(QPoint(x, y_line), 8, 8)
                # Inner dot
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#fff"))
                painter.drawEllipse(QPoint(x, y_line), 3, 3)
                # Active date label
                painter.setPen(QColor("#1a5fa8"))
                font = QFont()
                font.setPointSize(8)
                font.setBold(True)
                painter.setFont(font)
                painter.drawText(x - 40, 0, 80, 14, Qt.AlignmentFlag.AlignCenter, d)
            elif i == self._hover_idx:
                # Hover marker (enlarged)
                painter.setPen(QPen(QColor("#5a9fd4"), 1.5))
                painter.setBrush(QColor("#b8d4ef"))
                painter.drawEllipse(QPoint(x, y_line), 6, 6)
                # Hover date label
                painter.setPen(QColor("#5a9fd4"))
                font = QFont()
                font.setPointSize(7)
                painter.setFont(font)
                painter.drawText(x - 40, 0, 80, 14, Qt.AlignmentFlag.AlignCenter, d)
            else:
                # Inactive marker
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#a0aec0"))
                painter.drawEllipse(QPoint(x, y_line), 4, 4)

        painter.end()

    def mousePressEvent(self, event):
        if not self._dates or event.button() != Qt.MouseButton.LeftButton:
            return
        idx = self._idx_from_x(event.pos().x())
        if idx >= 0:
            self._dragging = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.dateClicked.emit(idx)

    def mouseMoveEvent(self, event):
        if not self._dates:
            return
        n = len(self._dates)
        w = self.width()
        margin = 40

        if self._dragging:
            idx = self._idx_from_x(event.pos().x())
            if 0 <= idx < n and idx != self._current:
                self.dateClicked.emit(idx)
            return

        # Hover detection
        mx = event.pos().x()
        old_hover = self._hover_idx
        self._hover_idx = -1
        for i in range(n):
            x = margin + int(i * (w - 2 * margin) / (n - 1)) if n > 1 else w // 2
            if abs(mx - x) < 12:
                self._hover_idx = i
                QToolTip.showText(event_global_pos(event), self._dates[i])
                break
        else:
            QToolTip.hideText()
        if old_hover != self._hover_idx:
            self.update()

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._dragging = False
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def leaveEvent(self, event):
        if self._hover_idx != -1:
            self._hover_idx = -1
            self.update()
        super().leaveEvent(event)
