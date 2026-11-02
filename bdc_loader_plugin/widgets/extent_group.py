"""
extent_group.py

The Extent area filter as a collapsible group with an arrow, like Tiles and
Vector File. The extent becomes the filter in use once one is set (drawn on
the canvas, typed, or taken from the canvas or a layer) and stops being it
when cleared.
"""

from qgis.core import QgsRectangle
from qgis.gui import QgsCollapsibleGroupBox, QgsExtentWidget
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import QLineEdit, QVBoxLayout

# Coordinate fields of QgsExtentWidget, in QgsRectangle argument order
_FIELDS = ("mXMinLineEdit", "mYMinLineEdit", "mXMaxLineEdit", "mYMaxLineEdit")


def parse_coordinate(text):
    """Degrees typed with "." or "," as the decimal mark, or None."""
    text = str(text or "").strip().replace(" ", "")
    if not text:
        return None
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def typed_rectangle(texts):
    """(xmin, ymin, xmax, ymax) from four typed fields, or None while incomplete or inverted."""
    values = [parse_coordinate(t) for t in texts]
    if any(v is None for v in values):
        return None
    xmin, ymin, xmax, ymax = values
    if xmin >= xmax or ymin >= ymax:
        return None
    return xmin, ymin, xmax, ymax


def _expanded_style():
    styles = getattr(QgsExtentWidget, "WidgetStyle", QgsExtentWidget)
    return styles.ExpandedStyle


def _draw_on_canvas_state():
    states = getattr(QgsExtentWidget, "ExtentState", QgsExtentWidget)
    return states.DrawOnCanvas


class ExtentGroup(QgsCollapsibleGroupBox):
    """Collapsible group holding a QGIS extent widget.

    ``isActive()`` is True while the extent is the area filter in use;
    ``activeChanged`` fires when that changes. Clearing deactivates it.
    """

    activeChanged = pyqtSignal(bool)

    def __init__(self, title="Extent", parent=None):
        super().__init__(title, parent)
        self._active = False
        self.extent_widget = QgsExtentWidget(None, _expanded_style())
        self.extent_widget.setNullValueAllowed(True, "Not set")
        self.extentChanged = self.extent_widget.extentChanged
        # "Draw on canvas" asks for the window to step aside while the user
        # drags on the map, and to come back once the rectangle is drawn.
        self.extent_widget.toggleDialogVisibility.connect(self._set_window_visible)
        self.content_layout = QVBoxLayout()
        self.content_layout.setContentsMargins(8, 8, 8, 8)
        self.content_layout.setSpacing(6)
        self.content_layout.addWidget(self.extent_widget)
        self.setLayout(self.content_layout)

    def _set_window_visible(self, visible):
        window = self.window()
        window.setVisible(visible)
        if visible:
            window.raise_()
            window.activateWindow()

    def wasDrawn(self):
        """True when the current extent was drawn on the map canvas."""
        return self.extent_widget.extentState() == _draw_on_canvas_state()

    def isActive(self):
        return self._active

    def setActive(self, active):
        active = bool(active)
        if active == self._active:
            return
        self._active = active
        if not active:
            self.extent_widget.clear()
        self.activeChanged.emit(active)

    def _typed_extent(self):
        """Extent shown in the coordinate fields.

        Read here rather than from QgsExtentWidget, which marks itself valid
        only when an extent comes from one of its buttons and reads a "." as
        a thousands separator in locales that use "," for decimals.
        """
        edits = [self.extent_widget.findChild(QLineEdit, name) for name in _FIELDS]
        if any(edit is None for edit in edits):
            return None
        bounds = typed_rectangle(edit.text() for edit in edits)
        return QgsRectangle(*bounds) if bounds else None

    def suspend(self):
        """Stop using the extent as the area filter but keep it, so setActive(True) resumes it."""
        if self._active:
            self._active = False
            self.activeChanged.emit(False)

    def clear(self):
        """Stop using the extent and forget it."""
        self.setActive(False)
        self.extent_widget.clear()

    def hasExtent(self):
        return self._typed_extent() is not None or bool(self.extent_widget.isValid())

    def outputExtent(self):
        typed = self._typed_extent()
        if typed is not None:
            return typed
        if self.extent_widget.isValid():
            return self.extent_widget.outputExtent()
        return QgsRectangle()

    def setOutputCrs(self, crs):
        self.extent_widget.setOutputCrs(crs)

    def setCurrentExtent(self, extent, crs):
        self.extent_widget.setCurrentExtent(extent, crs)

    def setOutputExtentFromUser(self, extent, crs):
        self.extent_widget.setOutputExtentFromUser(extent, crs)

    def setMapCanvas(self, canvas):
        self.extent_widget.setMapCanvas(canvas)
