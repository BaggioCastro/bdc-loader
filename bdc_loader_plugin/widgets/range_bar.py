"""
Range Bar

Provides an interactive AxisRangeBar with two draggable handles.
Mostly used for controlling the Y-axis and X-axis constraints of the
line charts and RGB scatter plots.

Developed by Baggio Luiz de Castro e Silva
INPE - Sao Jose dos Campos, 2026
"""

import logging

_logger = logging.getLogger("bdc_loader")
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QBrush, QColor, QFont, QPainter, QPen
from qgis.PyQt.QtWidgets import QWidget

from ..i18n import set_text
from .range_slider import _nearest_range_handle


class AxisRangeBar(QWidget):
    """
    An interactive UI widget acting as a range slider for graph axes.
    Can be oriented horizontally or vertically.

    Signals:
        rangeChanged (float, float): Emitted when the user adjusts the handles.
    """

    rangeChanged = pyqtSignal(float, float)

    def __init__(self, orientation="horizontal", label="", parent=None):
        """
        Initializes the AxisRangeBar.

        Args:
            orientation (str, optional): 'horizontal' or 'vertical'. Defaults to 'horizontal'.
            label (str, optional): An optional text label. Defaults to ''.
            parent (QWidget, optional): The parent widget. Defaults to None.
        """
        super().__init__(parent)
        self._orientation = orientation
        self._label = label
        self._data_min = 0.0
        self._data_max = 1.0
        self._view_min = 0.0
        self._view_max = 1.0
        self._dragging = None
        self._handle_size = 10
        self._bar_thickness = 5
        self._format_fn = None  # Function to format values on tooltip
        # Track ends in widget pixels along the bar, set to line up with the
        # plot area; None uses the widget length minus the handle size.
        self._track_span = None

        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setToolTip("Click the track to move the nearest handle. Double-click to reset.")

        if self._orientation == "horizontal":
            self.setFixedHeight(26)
            self.setMinimumWidth(80)
        else:
            self.setFixedWidth(26)
            self.setMinimumHeight(80)

    def set_track_span(self, start, end):
        """Draw the track from ``start`` to ``end`` pixels along the bar.

        The chart passes the pixel extent of its plot area so the track lines
        up with the axis it controls. ``None`` restores the full length.
        """
        span = None if start is None or end is None or end - start < 2 else (int(round(start)), int(round(end)))
        if span != self._track_span:
            self._track_span = span
            self.update()

    def _track_ends(self):
        """Pixel positions of the two ends of the track along the bar."""
        length = self.width() if self._orientation == "horizontal" else self.height()
        hs = self._handle_size
        if self._track_span:
            start, end = self._track_span
            return max(hs // 2, start), min(length - hs // 2, end)
        return hs, length - hs

    def set_format_fn(self, fn: callable):
        """
        Sets a custom formatting function for the tooltips (e.g., date formatter).

        Args:
            fn (callable): A function taking a float and returning a string.
        """
        self._format_fn = fn

    def _format_value(self, v: float) -> str:
        """Applies the formatting function, falling back to 1 decimal place format."""
        if self._format_fn:
            try:
                return self._format_fn(v)
            except Exception as _e:
                _logger.debug("Range bar format function failed: %s", _e)
        return f"{v:.1f}"

    def set_data_range(self, dmin: float, dmax: float):
        """
        Sets the global data boundary for the range bar.

        Args:
            dmin (float): The minimum valid data limit.
            dmax (float): The maximum valid data limit.
        """
        if dmax <= dmin:
            dmax = dmin + 1
        self._data_min = dmin
        self._data_max = dmax
        self._view_min = dmin
        self._view_max = dmax
        self.update()

    def set_view_range(self, vmin: float, vmax: float):
        """
        Sets the visually active range (handles).

        Args:
            vmin (float): The minimum displayed boundary.
            vmax (float): The maximum displayed boundary.
        """
        self._view_min = max(self._data_min, min(vmin, self._data_max))
        self._view_max = max(self._data_min, min(vmax, self._data_max))
        if self._view_min > self._view_max:
            self._view_min, self._view_max = self._view_max, self._view_min
        minimum_gap = self._minimum_gap_value()
        if self._view_max - self._view_min < minimum_gap:
            if self._view_min + minimum_gap <= self._data_max:
                self._view_max = self._view_min + minimum_gap
            else:
                self._view_min = self._view_max - minimum_gap
        self.update()

    def _minimum_gap_value(self):
        """Return a one-pixel value gap so handles cannot occupy the same position."""
        start, end = self._track_ends()
        usable_span = max(1, end - start)
        return (self._data_max - self._data_min) / usable_span

    def get_view_range(self) -> tuple:
        """Returns the current visually active min/max boundaries."""
        return (self._view_min, self._view_max)

    def reset(self):
        """Resets the visual handles to the full data extents."""
        # Block signals to prevent _on_y_range_changed issues from overriding values
        old_state = self.signalsBlocked()
        self.blockSignals(True)
        self._view_min = self._data_min
        self._view_max = self._data_max
        self.update()
        self.blockSignals(old_state)
        # Manually emit since we safely reset
        self.rangeChanged.emit(self._view_min, self._view_max)

    def _frac_to_pos(self, frac: float) -> float:
        """Converts a ratio (0.0 - 1.0) into a pixel coordinate."""
        start, end = self._track_ends()
        if self._orientation == "horizontal":
            return start + frac * (end - start)
        return start + (1.0 - frac) * (end - start)

    def _pos_to_frac(self, pos: float) -> float:
        """Converts a pixel coordinate into a ratio (0.0 - 1.0)."""
        start, end = self._track_ends()
        span = end - start
        if span <= 0:
            return 0.0
        if self._orientation == "horizontal":
            return max(0.0, min(1.0, (pos - start) / span))
        return max(0.0, min(1.0, 1.0 - (pos - start) / span))

    def _value_to_frac(self, value: float) -> float:
        """Converts a data value to a 0.0-1.0 fraction ratio."""
        rng = self._data_max - self._data_min
        if rng <= 0:
            return 0.0
        return (value - self._data_min) / rng

    def _frac_to_value(self, frac: float) -> float:
        """Converts a 0.0-1.0 fraction ratio to a corresponding data value."""
        return self._data_min + frac * (self._data_max - self._data_min)

    def paintEvent(self, event):
        """Custom QWidget paint event handling UI drawing."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        hs = self._handle_size
        bt = self._bar_thickness
        start, end = self._track_ends()

        if self._orientation == "horizontal":
            bar_y = (self.height() - bt) // 2
            painter.setBrush(QBrush(QColor("#e0e0e0")))
            painter.setPen(QPen(QColor("#ccc"), 1))
            painter.drawRoundedRect(start, bar_y, end - start, bt, bt // 2, bt // 2)
            f_min = self._value_to_frac(self._view_min)
            f_max = self._value_to_frac(self._view_max)
            x1 = self._frac_to_pos(f_min)
            x2 = self._frac_to_pos(f_max)
            painter.setBrush(QBrush(QColor("#3498db")))
            painter.setPen(QPen(QColor("#2980b9"), 1))
            painter.drawRoundedRect(int(x1), bar_y, int(x2 - x1), bt, bt // 2, bt // 2)
            painter.setBrush(QBrush(QColor("#1a5490")))
            painter.setPen(QPen(QColor("white"), 1.5))
            cy = self.height() // 2
            painter.drawEllipse(int(x1) - hs // 2, cy - hs // 2, hs, hs)
            painter.drawEllipse(int(x2) - hs // 2, cy - hs // 2, hs, hs)

            # Show min/max values during drag
            if self._dragging:
                painter.setPen(QPen(QColor("#1a5490")))
                font = QFont()
                font.setPointSize(7)
                font.setBold(True)
                painter.setFont(font)
                painter.drawText(int(x1) - 20, bar_y - 3, self._format_value(self._view_min))
                painter.drawText(int(x2) - 20, bar_y - 3, self._format_value(self._view_max))
        else:
            bar_x = (self.width() - bt) // 2
            painter.setBrush(QBrush(QColor("#e0e0e0")))
            painter.setPen(QPen(QColor("#ccc"), 1))
            painter.drawRoundedRect(bar_x, start, bt, end - start, bt // 2, bt // 2)
            f_min = self._value_to_frac(self._view_min)
            f_max = self._value_to_frac(self._view_max)
            y_max_pos = self._frac_to_pos(f_max)
            y_min_pos = self._frac_to_pos(f_min)
            painter.setBrush(QBrush(QColor("#3498db")))
            painter.setPen(QPen(QColor("#2980b9"), 1))
            painter.drawRoundedRect(bar_x, int(y_max_pos), bt, int(y_min_pos - y_max_pos), bt // 2, bt // 2)
            cx = self.width() // 2
            painter.setBrush(QBrush(QColor("#1a5490")))
            painter.setPen(QPen(QColor("white"), 1.5))
            painter.drawEllipse(cx - hs // 2, int(y_max_pos) - hs // 2, hs, hs)
            painter.drawEllipse(cx - hs // 2, int(y_min_pos) - hs // 2, hs, hs)

            # Show min/max values during vertical drag
            if self._dragging:
                painter.setPen(QPen(QColor("#1a5490")))
                font = QFont()
                font.setPointSize(6)
                font.setBold(True)
                painter.setFont(font)
                painter.save()
                painter.translate(self.width(), int(y_max_pos))
                painter.drawText(2, 4, self._format_value(self._view_max))
                painter.restore()
                painter.save()
                painter.translate(self.width(), int(y_min_pos))
                painter.drawText(2, 4, self._format_value(self._view_min))
                painter.restore()

    def _in_track_bounds(self, event) -> bool:
        """True if the click's cross-axis coordinate falls on the drawn bar/handles,
        not just anywhere in the widget's full bounding box."""
        hs = self._handle_size
        if self._orientation == "horizontal":
            center = self.height() // 2
            cross = event.pos().y()
        else:
            center = self.width() // 2
            cross = event.pos().x()
        return abs(cross - center) <= hs // 2

    def mousePressEvent(self, event):
        """Move the nearest handle to any clicked point on the track."""
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if not self._in_track_bounds(event):
            return
        pos = event.pos().x() if self._orientation == "horizontal" else event.pos().y()
        f_min = self._value_to_frac(self._view_min)
        f_max = self._value_to_frac(self._view_max)
        p_min = self._frac_to_pos(f_min)
        p_max = self._frac_to_pos(f_max)

        nearest = _nearest_range_handle(
            pos,
            p_min,
            p_max,
            inverted=self._orientation == "vertical",
        )
        self._dragging = "min" if nearest == "minimum" else "max"
        self._move_dragged_handle(pos)
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def _move_dragged_handle(self, pos):
        frac = self._pos_to_frac(pos)
        value = max(self._data_min, min(self._frac_to_value(frac), self._data_max))
        minimum_gap = self._minimum_gap_value()
        if self._dragging == "min":
            new_value = min(value, self._view_max - minimum_gap)
            changed = new_value != self._view_min
            self._view_min = new_value
        elif self._dragging == "max":
            new_value = max(value, self._view_min + minimum_gap)
            changed = new_value != self._view_max
            self._view_max = new_value
        else:
            return False
        if changed:
            self.rangeChanged.emit(self._view_min, self._view_max)
        self.update()
        return changed

    def mouseMoveEvent(self, event):
        """Processes drag movement, updating active boundaries."""
        pos = event.pos().x() if self._orientation == "horizontal" else event.pos().y()
        if self._dragging:
            self._move_dragged_handle(pos)

            # Set tooltip text showing current bounds
            tip = f"{self._format_value(self._view_min)} ~ {self._format_value(self._view_max)}"
            self.setToolTip(tip)
        else:
            f_min = self._value_to_frac(self._view_min)
            f_max = self._value_to_frac(self._view_max)
            p_min = self._frac_to_pos(f_min)
            p_max = self._frac_to_pos(f_max)
            if self._orientation == "vertical":
                near = abs(pos - p_max) < self._handle_size + 2 or abs(pos - p_min) < self._handle_size + 2
            else:
                near = abs(pos - p_min) < self._handle_size + 2 or abs(pos - p_max) < self._handle_size + 2
            self.setCursor(Qt.CursorShape.OpenHandCursor if near else Qt.CursorShape.ArrowCursor)
            set_text(self, "Click or drag to adjust range. Double-click to reset.", "tip")

    def mouseReleaseEvent(self, event):
        """Concludes the drag operation."""
        self._dragging = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def mouseDoubleClickEvent(self, event):
        """Resets boundaries acting on double click."""
        self.reset()
