"""
Range Sliders and Bars

Provides interactive timeline slider widgets.
Contains `RangeSlider` and `RangeBar` (main dialog) and
`TSRangeSlider` and `TSRangeBar` (from Time Series Panel), as well as
the `ToggleSwitch` widget.

Developed by Baggio Luiz de Castro e Silva
INPE - Sao Jose dos Campos, 2026
"""

from qgis.PyQt.QtCore import QDate, Qt, pyqtSignal
from qgis.PyQt.QtGui import QBrush, QColor, QFont, QPainter, QPen
from qgis.PyQt.QtWidgets import (
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QSlider,
    QStyle,
    QStyleOptionSlider,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr


def _nearest_range_handle(position, minimum_position, maximum_position, *, inverted=False):
    """Return the nearest range handle, resolving coincident handles by click side."""
    min_distance = abs(position - minimum_position)
    max_distance = abs(position - maximum_position)
    if min_distance < max_distance:
        return "minimum"
    if max_distance < min_distance:
        return "maximum"

    midpoint = (minimum_position + maximum_position) / 2.0
    if inverted:
        return "maximum" if position <= midpoint else "minimum"
    return "minimum" if position <= midpoint else "maximum"


class JumpSlider(QSlider):
    """QSlider that moves its handle directly to a clicked track position."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mouse_dragging = False
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _style_rects(self):
        """The groove and the handle as the style draws them."""
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        style = self.style()
        groove = style.subControlRect(QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderGroove, self)
        handle = style.subControlRect(QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderHandle, self)
        return groove, handle

    def _value_from_position(self, position):
        """The value that puts the centre of the handle under ``position``, on the style's own scale."""
        groove, handle = self._style_rects()
        if self.orientation() == Qt.Orientation.Horizontal:
            length, start, pos = handle.width(), groove.x(), position.x()
            span = groove.width() - length
        else:
            length, start, pos = handle.height(), groove.y(), position.y()
            span = groove.height() - length
        return QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), round(pos - start - length / 2), max(1, span), self.invertedAppearance()
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._mouse_dragging = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            # A press on the handle grabs it where it is; a press on the track
            # brings the handle under the pointer first, so the drag that
            # follows starts from there.
            if not self._style_rects()[1].contains(event.pos()):
                self.setValue(self._value_from_position(event.pos()))
        super().mousePressEvent(event)

    def _finish_mouse_drag(self):
        self._mouse_dragging = False
        self.setCursor(Qt.CursorShape.OpenHandCursor)  # the pointer is on the handle it just let go

    def mouseMoveEvent(self, event):
        if self._mouse_dragging and not event.buttons() & Qt.MouseButton.LeftButton:
            self._finish_mouse_drag()
        if not self._mouse_dragging:
            # Open hand over the handle, which a press grabs; pointing hand over
            # the track, where a press brings the handle.
            over_handle = self._style_rects()[1].contains(event.pos())
            self.setCursor(Qt.CursorShape.OpenHandCursor if over_handle else Qt.CursorShape.PointingHandCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton or not event.buttons() & Qt.MouseButton.LeftButton:
            self._finish_mouse_drag()


class RangeBar(QWidget):
    """
    A visual range bar with two draggable handles for timeline selection.
    Used in the main dialog.
    """

    rangeChanged = pyqtSignal(int, int)
    dragFinished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._min = 0
        self._max = 100
        self._start = 0
        self._end = 100
        self._year_positions = []
        self._dragging = None
        self._drag_offset = 0.0
        self._drag_changed = False
        self._handle_width = 14
        self._bar_height = 8
        self._bar_y = 25
        self._snap_threshold = 4  # pixels

        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setToolTip("Click the track to move the nearest handle, or drag a handle")

    def set_range(self, min_val: int, max_val: int, year_positions=None):
        self._min = min_val
        self._max = max_val
        if year_positions is not None:
            # An empty list replaces the old labels too, or a range without
            # a 1 January kept drawing the years of the previous range.
            self._year_positions = list(year_positions)
        self.update()

    def set_values(self, start: int, end: int):
        self._start = max(self._min, min(start, self._max))
        self._end = max(self._min, min(end, self._max))
        if self._start > self._end:
            self._start, self._end = self._end, self._start
        self.update()

    def _value_to_x(self, value: int) -> float:
        if self._max == self._min:
            return self._handle_width
        ratio = (value - self._min) / (self._max - self._min)
        return self._handle_width + ratio * (self.width() - 2 * self._handle_width)

    def _x_to_value(self, x: float) -> int:
        if self.width() <= 2 * self._handle_width:
            return self._min
        ratio = (x - self._handle_width) / (self.width() - 2 * self._handle_width)
        ratio = max(0.0, min(1.0, ratio))
        return int(self._min + ratio * (self._max - self._min))

    def _snap_to_year(self, value: int) -> int:
        """Snaps to the nearest 1 January within _snap_threshold pixels on screen, whatever the span of the bar."""
        x = self._value_to_x(value)
        for year_pos, year in self._year_positions:
            if abs(x - self._value_to_x(year_pos)) <= self._snap_threshold:
                return year_pos
        return value

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        bar_y = self._bar_y
        bar_h = self._bar_height

        # Background track
        painter.setBrush(QBrush(QColor("#e8e8e8")))
        painter.setPen(QPen(QColor("#bdbdbd"), 1))
        painter.drawRoundedRect(
            self._handle_width, bar_y, self.width() - 2 * self._handle_width, bar_h, bar_h // 2, bar_h // 2
        )

        # Selected range
        start_x = self._value_to_x(self._start)
        end_x = self._value_to_x(self._end)
        painter.setBrush(QBrush(QColor("#3498db")))
        painter.setPen(QPen(QColor("#2980b9"), 1))
        painter.drawRoundedRect(int(start_x), bar_y, int(end_x - start_x), bar_h, bar_h // 2, bar_h // 2)

        # Tick marks for years
        painter.setPen(QPen(QColor("#888"), 1))
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)

        min_label_spacing = 45
        step = 1
        if len(self._year_positions) > 1:
            avg_spacing = (self.width() - 2 * self._handle_width) / max(len(self._year_positions), 1)
            if avg_spacing < min_label_spacing:
                step = max(2, int(min_label_spacing / max(avg_spacing, 1)) + 1)

        for i, (year_pos, year) in enumerate(self._year_positions):
            x = self._value_to_x(year_pos)
            painter.drawLine(int(x), bar_y - 3, int(x), bar_y + bar_h + 3)
            if i % step == 0:
                painter.drawText(int(x) - 15, bar_y - 8, str(year))

        # Start handle
        painter.setBrush(QBrush(QColor("#1a5490")))
        painter.setPen(QPen(QColor("white"), 2))
        painter.drawEllipse(
            int(start_x) - self._handle_width // 2,
            bar_y + bar_h // 2 - self._handle_width // 2,
            self._handle_width,
            self._handle_width,
        )

        # End handle
        painter.setBrush(QBrush(QColor("#1a5490")))
        painter.setPen(QPen(QColor("white"), 2))
        painter.drawEllipse(
            int(end_x) - self._handle_width // 2,
            bar_y + bar_h // 2 - self._handle_width // 2,
            self._handle_width,
            self._handle_width,
        )

    def _in_track_bounds(self, event) -> bool:
        """True if the pointer is level with the drawn bar and handles, with a
        few pixels of slack, not just anywhere in the widget's taller box
        (there's extra height above the bar for the drag tooltip and below it
        for year tick labels)."""
        center = self._bar_y + self._bar_height / 2
        return abs(event.pos().y() - center) <= self._grab_radius()

    def _grab_radius(self):
        """How far from a handle's centre the pointer grabs it; the hand cursor shows over the same area."""
        return self._handle_width / 2 + 3

    def _handle_under(self, event):
        """ "start", "end" or None: the handle a press at ``event`` grabs."""
        if not self._in_track_bounds(event):
            return None
        x = event.pos().x()
        start_x = self._value_to_x(self._start)
        end_x = self._value_to_x(self._end)
        nearest = "start" if _nearest_range_handle(x, start_x, end_x) == "minimum" else "end"
        handle_x = start_x if nearest == "start" else end_x
        return nearest if abs(x - handle_x) <= self._grab_radius() else None

    @property
    def is_dragging(self) -> bool:
        return self._dragging is not None

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if not self._in_track_bounds(event):
            return
        x = event.pos().x()
        start_x = self._value_to_x(self._start)
        end_x = self._value_to_x(self._end)
        nearest = _nearest_range_handle(x, start_x, end_x)
        self._dragging = "start" if nearest == "minimum" else "end"
        self._drag_changed = False
        handle_x = start_x if self._dragging == "start" else end_x
        if self._handle_under(event) is not None:
            # Preserve the point where the handle was grabbed. Treating a
            # handle press as a track click makes the date jump before the
            # pointer has moved and gives the drag a sticky feel.
            self._drag_offset = x - handle_x
        else:
            self._drag_offset = 0.0
            self._move_dragged_handle(self._snap_to_year(self._x_to_value(x)))
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        event.accept()

    def _move_dragged_handle(self, value):
        """Move the active handle without crossing the other handle."""
        if self._max <= self._min:
            return False
        if self._dragging == "start":
            new_value = max(self._min, min(value, self._end - 1))
            changed = new_value != self._start
            self._start = new_value
        elif self._dragging == "end":
            new_value = min(self._max, max(value, self._start + 1))
            changed = new_value != self._end
            self._end = new_value
        else:
            return False
        if changed:
            self._drag_changed = True
            self.rangeChanged.emit(self._start, self._end)
        self.update()
        return changed

    def mouseMoveEvent(self, event):
        x = event.pos().x()
        if self._dragging:
            # Recover if Qt/the window manager dropped the matching release
            # event. A hover without the left button must never keep dragging.
            if not event.buttons() & Qt.MouseButton.LeftButton:
                self._finish_drag()
                return
            value = self._x_to_value(x - self._drag_offset)
            value = self._snap_to_year(value)
            self._move_dragged_handle(value)
        else:
            # The hand shows exactly where a press grabs a handle; elsewhere on
            # the bar a press moves the nearest handle there.
            if self._handle_under(event) is not None:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            elif self._in_track_bounds(event):
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

    def _finish_drag(self):
        was_dragging = self._dragging is not None
        drag_changed = self._drag_changed
        self._dragging = None
        self._drag_offset = 0.0
        self._drag_changed = False
        self.setCursor(Qt.CursorShape.ArrowCursor)
        if was_dragging and drag_changed:
            self.dragFinished.emit()
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton or not event.buttons() & Qt.MouseButton.LeftButton:
            self._finish_drag()
            event.accept()


class RangeSlider(QWidget):
    """
    A unified range slider widget combining QDateEdits with a RangeBar.
    Used in the main dialog.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._min_date = QDate(2017, 1, 1)
        self._max_date = QDate(2026, 2, 1)
        self._total_days = self._min_date.daysTo(self._max_date)
        self._updating = False
        self._start_value = 0
        self._end_value = self._total_days
        self._year_positions = []

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        date_inputs = QHBoxLayout()
        date_inputs.addWidget(QLabel("From:"))
        self.start_date_edit = QDateEdit()
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setDisplayFormat("dd/MM/yyyy")
        self.start_date_edit.dateChanged.connect(self._on_start_date_edited)
        date_inputs.addWidget(self.start_date_edit)

        date_inputs.addStretch()

        date_inputs.addWidget(QLabel("To:"))
        self.end_date_edit = QDateEdit()
        self.end_date_edit.setCalendarPopup(True)
        self.end_date_edit.setDisplayFormat("dd/MM/yyyy")
        self.end_date_edit.dateChanged.connect(self._on_end_date_edited)
        date_inputs.addWidget(self.end_date_edit)
        layout.addLayout(date_inputs)

        self.range_bar = RangeBar(self)
        self.range_bar.setFixedHeight(60)
        self.range_bar.rangeChanged.connect(self._on_range_bar_changed)
        layout.addWidget(self.range_bar)

        self.range_label = QLabel()
        self.range_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.range_label.setStyleSheet("font-size: 10px; color: #555;")
        layout.addWidget(self.range_label)

        self.setLayout(layout)
        # Fill the date edits from the initial bounds, so they match the label
        # before the first set_date_range from a collection or result list.
        RangeSlider.set_date_range(self, self._min_date, self._max_date)

    def set_date_range(self, min_date: QDate, max_date: QDate):
        """Sets the available date boundaries for the slider."""
        self._updating = True
        self._min_date = min_date
        self._max_date = max_date
        self._total_days = min_date.daysTo(max_date)
        self._start_value = 0
        self._end_value = self._total_days

        self._year_positions = []
        year = min_date.year()
        while year <= max_date.year() + 1:
            year_date = QDate(year, 1, 1)
            if year_date >= min_date and year_date <= max_date:
                days = min_date.daysTo(year_date)
                self._year_positions.append((days, year))
            year += 1
        if not self._year_positions:
            # A range inside one year: label it at its start.
            self._year_positions.append((0, min_date.year()))

        self.start_date_edit.setDateRange(min_date, max_date)
        self.end_date_edit.setDateRange(min_date, max_date)
        self.start_date_edit.setDate(min_date)
        self.end_date_edit.setDate(max_date)

        self.range_bar.set_range(0, self._total_days, self._year_positions)
        self.range_bar.set_values(0, self._total_days)

        self._updating = False
        self._update_all()

    def _on_range_bar_changed(self, start_val: int, end_val: int):
        if self._updating:
            return
        self._start_value = start_val
        self._end_value = end_val
        self._updating = True
        self.start_date_edit.setDate(self._min_date.addDays(start_val))
        self.end_date_edit.setDate(self._min_date.addDays(end_val))
        self._updating = False
        self._update_labels()

    def _on_start_date_edited(self, date: QDate):
        if self._updating:
            return
        self._set_selected_date(date, is_start=True)

    def _on_end_date_edited(self, date: QDate):
        if self._updating:
            return
        self._set_selected_date(date, is_start=False)

    def _update_all(self):
        self._update_labels()

    def _update_labels(self):
        start_date = self._min_date.addDays(self._start_value)
        end_date = self._min_date.addDays(self._end_value)
        days = start_date.daysTo(end_date)
        self.range_label.setText(
            tr(f"Period: {days} days ({start_date.toString('dd/MM/yyyy')} / {end_date.toString('dd/MM/yyyy')})")
        )

    def get_start_date(self) -> QDate:
        return self._min_date.addDays(self._start_value)

    def get_end_date(self) -> QDate:
        return self._min_date.addDays(self._end_value)

    def set_start_date(self, date: QDate):
        """Sets the selected start date, clamped to the available range; False when it was clamped."""
        return self._set_selected_date(date, is_start=True)

    def set_end_date(self, date: QDate):
        """Sets the selected end date, clamped to the available range; False when it was clamped."""
        return self._set_selected_date(date, is_start=False)

    def _set_selected_date(self, date: QDate, is_start: bool):
        if not date or not date.isValid() or self._min_date is None:
            return False
        days = max(0, min(self._min_date.daysTo(date), self._total_days))
        self._updating = True
        # A start after the end moves the end with it, and the other way round,
        # so the period is never inverted.
        if is_start:
            self._start_value = days
            self._end_value = max(self._end_value, days)
        else:
            self._end_value = days
            self._start_value = min(self._start_value, days)
        self.start_date_edit.setDate(self._min_date.addDays(self._start_value))
        self.end_date_edit.setDate(self._min_date.addDays(self._end_value))
        self.range_bar.set_values(self._start_value, self._end_value)
        self._updating = False
        self._update_labels()
        return self._min_date.addDays(days) == date


class TSRangeBar(RangeBar):
    """
    Timeline handle bar specific for the Time Series Panel.
    Inherits from RangeBar and overrides styling slightly.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._handle_width = 16
        self._bar_height = 6
        self._bar_y = 20
        self.setFixedHeight(50)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        bar_y = self._bar_y
        bar_h = self._bar_height

        # Background track
        painter.setBrush(QBrush(QColor("#e8e8e8")))
        painter.setPen(QPen(QColor("#bdbdbd"), 1))
        painter.drawRoundedRect(
            self._handle_width, bar_y, self.width() - 2 * self._handle_width, bar_h, bar_h // 2, bar_h // 2
        )

        # Selected range
        start_x = self._value_to_x(self._start)
        end_x = self._value_to_x(self._end)
        painter.setBrush(QBrush(QColor("#3498db")))
        painter.setPen(QPen(QColor("#2980b9"), 1))
        painter.drawRoundedRect(int(start_x), bar_y, int(end_x - start_x), bar_h, bar_h // 2, bar_h // 2)

        # Tick marks
        painter.setPen(QPen(QColor("#888"), 1))
        font = QFont()
        font.setPointSize(7)
        painter.setFont(font)

        min_label_spacing = 40
        step = 1
        if len(self._year_positions) > 1:
            avg_spacing = (self.width() - 2 * self._handle_width) / max(len(self._year_positions), 1)
            if avg_spacing < min_label_spacing:
                step = max(2, int(min_label_spacing / max(avg_spacing, 1)) + 1)

        for i, (year_pos, year) in enumerate(self._year_positions):
            x = self._value_to_x(year_pos)
            painter.drawLine(int(x), bar_y - 2, int(x), bar_y + bar_h + 2)
            if i % step == 0:
                painter.drawText(int(x) - 12, bar_y - 5, str(year))

        hw = self._handle_width
        painter.setBrush(QBrush(QColor("#1a5490")))
        painter.setPen(QPen(QColor("white"), 2))
        painter.drawEllipse(int(start_x) - hw // 2, bar_y + bar_h // 2 - hw // 2, hw, hw)
        painter.drawEllipse(int(end_x) - hw // 2, bar_y + bar_h // 2 - hw // 2, hw, hw)


class TSRangeSlider(RangeSlider):
    """
    Timeline slider specific for the Time Series Panel.
    Overrides minor layout spacing and font issues compared to the parent.
    """

    def _setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(4)

        date_inputs = QHBoxLayout()

        lbl_de = QLabel("From:")
        lbl_de.setStyleSheet("border: none; background: transparent; font-size: 10px;")
        date_inputs.addWidget(lbl_de)

        self.start_date_edit = QDateEdit()
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setDisplayFormat("dd/MM/yyyy")
        self.start_date_edit.setStyleSheet("font-size: 10px;")
        self.start_date_edit.dateChanged.connect(self._on_start_date_edited)
        date_inputs.addWidget(self.start_date_edit)

        date_inputs.addStretch()

        lbl_ate = QLabel("To:")
        lbl_ate.setStyleSheet("border: none; background: transparent; font-size: 10px;")
        date_inputs.addWidget(lbl_ate)

        self.end_date_edit = QDateEdit()
        self.end_date_edit.setCalendarPopup(True)
        self.end_date_edit.setDisplayFormat("dd/MM/yyyy")
        self.end_date_edit.setStyleSheet("font-size: 10px;")
        self.end_date_edit.dateChanged.connect(self._on_end_date_edited)
        date_inputs.addWidget(self.end_date_edit)
        layout.addLayout(date_inputs)

        self.range_bar = TSRangeBar(self)
        self.range_bar.rangeChanged.connect(self._on_range_bar_changed)
        layout.addWidget(self.range_bar)

        self.range_label = QLabel()
        self.range_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.range_label.setStyleSheet("font-size: 9px; color: #555; border: none; background: transparent;")
        layout.addWidget(self.range_label)

        self.setLayout(layout)
        self._init_dates()

    def _init_dates(self):
        self._has_collection_bounds = False
        self._updating = True
        year = self._min_date.year()
        while year <= self._max_date.year() + 1:
            year_date = QDate(year, 1, 1)
            if year_date >= self._min_date and year_date <= self._max_date:
                days = self._min_date.daysTo(year_date)
                self._year_positions.append((days, year))
            year += 1

        self.start_date_edit.setDateRange(self._min_date, self._max_date)
        self.end_date_edit.setDateRange(self._min_date, self._max_date)
        self.start_date_edit.setDate(self._max_date.addYears(-1))
        self.end_date_edit.setDate(self._max_date)

        self._start_value = self._min_date.daysTo(self._max_date.addYears(-1))
        self._end_value = self._total_days

        self.range_bar.set_range(0, self._total_days, self._year_positions)
        self.range_bar.set_values(self._start_value, self._end_value)
        self._updating = False
        self._update_labels()

    def set_date_range(self, min_date: QDate, max_date: QDate):
        """Set the collection's date bounds and keep the selected period when it still fits.

        The selection is clamped to the new bounds. On the first call, or when nothing of the
        selection remains, the last year of the new range is selected.
        """
        start, end = self.get_start_date(), self.get_end_date()
        first_bounds = not self._has_collection_bounds
        self._has_collection_bounds = True
        super().set_date_range(min_date, max_date)
        start = max(min_date, min(start, max_date))
        end = max(min_date, min(end, max_date))
        if first_bounds or start >= end:
            start, end = max(min_date, max_date.addYears(-1)), max_date
        self.set_start_date(start)
        self.set_end_date(end)


class ToggleSwitch(QWidget):
    """
    A compact toggle switch widget with an optional text label.
    """

    toggled = pyqtSignal(bool)

    def __init__(self, text="", checked=False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self._text = text
        self.setFixedHeight(22)
        self.setMinimumWidth(100)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, val: bool):
        self._checked = val
        self.update()

    def mousePressEvent(self, event):
        self._checked = not self._checked
        self.update()
        self.toggled.emit(self._checked)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        track_w, track_h = 32, 16
        track_x = 0
        track_y = (self.height() - track_h) // 2

        # Background track
        if self._checked:
            painter.setBrush(QBrush(QColor("#27ae60")))
        else:
            painter.setBrush(QBrush(QColor("#bdc3c7")))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(track_x, track_y, track_w, track_h, track_h // 2, track_h // 2)

        # Thumb
        knob_size = track_h - 4
        knob_y = track_y + 2
        if self._checked:
            knob_x = track_x + track_w - knob_size - 2
        else:
            knob_x = track_x + 2
        painter.setBrush(QBrush(QColor("white")))
        painter.drawEllipse(knob_x, knob_y, knob_size, knob_size)

        # Label text
        if self._text:
            painter.setPen(QPen(QColor("#333")))
            font = QFont()
            font.setPointSize(8)
            painter.setFont(font)
            text_x = track_w + 8
            painter.drawText(text_x, track_y + track_h - 3, self._text)
