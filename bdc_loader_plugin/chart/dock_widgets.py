"""Widgets and stylesheets of the chart dock: the draggable title bar, band combos, channel labels and separators."""

import logging

_logger = logging.getLogger("bdc_loader")

from qgis.PyQt.QtCore import QPoint, Qt
from qgis.PyQt.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QLabel,
    QWidget,
)

from ..qt_compat import event_global_pos

_MODE_BTN_CHECKED = """
    QRadioButton {
        font-size: 11px; font-weight: bold; border: none;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #3498db, stop:1 #2980b9);
        color: white; border-radius: 4px; padding: 3px 10px;
    }
"""


_MODE_BTN_UNCHECKED = """
    QRadioButton {
        font-size: 11px; font-weight: bold; border: 1px solid #bdc3c7;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #f8f9fa, stop:1 #e9ecef);
        color: #555; border-radius: 4px; padding: 3px 10px;
    }
    QRadioButton:hover {
        border-color: #3498db; color: #2980b9;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #ffffff, stop:1 #f0f4f8);
    }
"""


_RGB_COMBO_STYLE = """
    QComboBox {
        font-size: 9px;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #f8f9fa, stop:1 #e9ecef);
        border: 1px solid #ccc;
        border-radius: 3px;
        padding: 1px 4px;
    }
    QComboBox:hover {
        border-color: #3498db;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #ffffff, stop:1 #f0f6ff);
    }
    QComboBox::drop-down {
        border: none;
        width: 16px;
    }
"""


_TITLE_BAR_STYLE = """
    #bdcChartTitleBar {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #34495e, stop:1 #2c3e50);
        border-top-left-radius: 4px; border-top-right-radius: 4px;
    }
"""


_CTRL_BAR_STYLE = """
    QWidget {
        background-color: #ecf0f1;
        border-radius: 4px;
        border: 1px solid #bdc3c7;
    }
    QRadioButton { font-weight: bold; color: #2c3e50; font-size: 10px; }
"""


_PAGE_CHART_BTN_STYLE = """
    QPushButton {
        font-size: 11px; font-weight: bold;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #fafafa, stop:1 #eee);
        border: 1px solid #ccc; border-radius: 3px;
    }
    QPushButton:hover { background: #ddd; border-color: #aaa; }
    QPushButton:disabled { color: #ccc; }
"""


_RANGE_LOCK_BTN_STYLE = """
    QPushButton {
        font-size: 9px; padding: 3px 6px;
        border: 1px solid #95a5a6; border-radius: 3px;
        background: #f8f9fa; color: #555;
    }
    QPushButton:checked {
        background: #27ae60; border-color: #1e8449;
        color: white; font-weight: bold;
    }
"""


_EXPORT_CSV_BTN_STYLE = """
    QPushButton {
        background-color: #3498db; color: white;
        border: none; border-radius: 3px;
        padding: 2px 10px; font-size: 9px; font-weight: bold;
    }
    QPushButton:hover { background-color: #2980b9; }
    QPushButton:disabled { background-color: #bdc3c7; }
"""


_EXPORT_SHP_BTN_STYLE = """
    QPushButton {
        background-color: #27ae60; color: white;
        border: none; border-radius: 3px;
        padding: 2px 10px; font-size: 9px; font-weight: bold;
    }
    QPushButton:hover { background-color: #229954; }
    QPushButton:disabled { background-color: #bdc3c7; }
"""


def _bar_separator():
    """Thin vertical line between groups of the control bar."""
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.VLine)
    sep.setStyleSheet("color: #bdc3c7; border: none; background: #bdc3c7; max-width: 1px;")
    return sep


def _channel_label(text, color):
    """Bold channel letter (R:, G:, B:, Y:) in the channel's color."""
    label = QLabel(text)
    label.setStyleSheet(f"border:none; background:transparent; font-size:11px; color:{color}; font-weight:bold;")
    return label


def _band_combo(width):
    """Band combo of the control bar, ``width`` pixels wide."""
    combo = QComboBox()
    combo.setStyleSheet(_RGB_COMBO_STYLE)
    combo.setFixedWidth(width)
    return combo


class _DraggableDockTitleBar(QWidget):
    """Custom dock title bar with portable native and manual drag support."""

    def __init__(self, dock):
        super().__init__(dock)
        self._dock = dock
        self._press_global = None
        self._drag_offset = None
        self._system_move_attempted = False
        self._system_move_started = False
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_global = event_global_pos(event)
            self._drag_offset = self._press_global - self._dock.mapToGlobal(QPoint(0, 0))
            self._system_move_attempted = False
            self._system_move_started = False
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_global is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if (event_global_pos(event) - self._press_global).manhattanLength() < QApplication.startDragDistance():
            return

        if not self._dock.isFloating():
            self._dock.setFloating(True)

        window_handle = self._dock.windowHandle()
        if not self._system_move_attempted and window_handle and hasattr(window_handle, "startSystemMove"):
            self._system_move_attempted = True
            try:
                self._system_move_started = bool(window_handle.startSystemMove())
            except RuntimeError:
                self._system_move_started = False
        if not self._system_move_started:
            self._dock.move(event_global_pos(event) - self._drag_offset)
        event.accept()

    def mouseReleaseEvent(self, event):
        self._press_global = None
        self._drag_offset = None
        self._system_move_attempted = False
        self._system_move_started = False
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dock.setFloating(not self._dock.isFloating())
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
