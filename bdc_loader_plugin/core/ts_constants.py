# -*- coding: utf-8 -*-
"""
Time Series constants, color presets, index definitions, and helper widgets.

Centralizes module-level constants used by the time series panel and core modules.
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QWidget

from ..qt_compat import event_global_pos

BAND_COLORS = [
    "#2980b9",
    "#e74c3c",
    "#27ae60",
    "#f39c12",
    "#8e44ad",
    "#1abc9c",
    "#d35400",
    "#2c3e50",
    "#c0392b",
    "#16a085",
    "#e67e22",
    "#3498db",
    "#9b59b6",
    "#34495e",
    "#e84393",
]

# Fallback common_name mapping for known satellite band names
_KNOWN_COMMON_NAMES = {
    # Sentinel-2
    "B02": "blue",
    "B03": "green",
    "B04": "red",
    "B08": "nir",
    "B8A": "nir08",
    "B05": "rededge",
    "B11": "swir16",
    "B12": "swir22",
    "B01": "coastal",
    "B06": "rededge",
    "B07": "rededge",
    # Sentinel-2 lowercase
    "b02": "blue",
    "b03": "green",
    "b04": "red",
    "b08": "nir",
    "b8a": "nir08",
    "b11": "swir16",
    "b12": "swir22",
    # Landsat
    "red": "red",
    "green": "green",
    "blue": "blue",
    "nir": "nir",
    "nir08": "nir",
    "swir16": "swir16",
    "swir22": "swir22",
    "coastal": "coastal",
    "SR_B1": "coastal",
    "SR_B2": "blue",
    "SR_B3": "green",
    "SR_B4": "red",
    "SR_B5": "nir",
    "SR_B6": "swir16",
    "SR_B7": "swir22",
    # CBERS
    "BAND13": "blue",
    "BAND14": "green",
    "BAND15": "red",
    "BAND16": "nir",
    "BAND5": "blue",
    "BAND6": "green",
    "BAND7": "red",
    "BAND8": "nir",
    # AMAZONIA-1
    "BAND1": "blue",
    "BAND2": "green",
    "BAND3": "red",
    "BAND4": "nir",
    # MODIS reflectance bands
    "red_reflectance": "red",
    "NIR_reflectance": "nir",
    "blue_reflectance": "blue",
    "MIR_reflectance": "swir16",
}

# Vegetation indices that can be computed from source bands
_INDEX_DEFS = {
    "_NDVI": {
        "output": "NDVI",
        "requires": ["nir", "red"],
        "label": "NDVI (calc)",
    },
    "_EVI": {
        "output": "EVI",
        "requires": ["nir", "red", "blue"],
        "label": "EVI (calc)",
    },
}


class _BandsResizeHandle(QWidget):
    """Tiny drag handle at the bottom of the bands area — lets user resize it."""

    def __init__(self, target_scroll, parent=None):
        super().__init__(parent)
        self._target = target_scroll
        self._dragging = False
        self._start_y = 0
        self._start_h = 0
        self.setFixedHeight(7)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setToolTip("Drag to resize bands area")
        self.setStyleSheet("""
            background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 #d5dbdb, stop:0.5 #bdc3c7, stop:1 #d5dbdb);
            border-radius: 3px;
        """)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._start_y = event_global_pos(event).y()
            self._start_h = self._target.height()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging:
            delta = event_global_pos(event).y() - self._start_y
            new_h = max(50, min(350, self._start_h + delta))
            self._target.setFixedHeight(int(new_h))
            event.accept()

    def mouseReleaseEvent(self, event):
        self._dragging = False
        event.accept()
