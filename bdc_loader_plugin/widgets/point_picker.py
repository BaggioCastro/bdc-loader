"""
Point Picker Tool

Provides a map tool to select a geographic point on the QGIS map canvas.
Changes the mouse cursor to a crosshair and emits the clicked coordinates.

Developed by Baggio Luiz de Castro e Silva
INPE - Sao Jose dos Campos, 2026
"""

import logging

_logger = logging.getLogger("bdc_loader")
from qgis.gui import QgsMapTool
from qgis.PyQt.QtCore import Qt


class PointPickerTool(QgsMapTool):
    """
    A QGIS map tool for capturing click coordinates on the map canvas.

    Attributes:
        _callback (callable): The function called when a point is clicked.
        _canvas (QgsMapCanvas): The map canvas instance.
        _on_deactivate (callable): Optional callback when tool is deactivated.
    """

    def __init__(self, canvas, callback, on_deactivate=None):
        super().__init__(canvas)
        self._callback = callback
        self._canvas = canvas
        self._on_deactivate = on_deactivate
        self._deactivate_reason = None
        self._loading = False

    def canvasReleaseEvent(self, event):
        if self._loading:
            try:
                event.accept()
            except Exception as _e:
                _logger.debug("event.accept() failed: %s", _e)
            return
        point = self.toMapCoordinates(event.pos())
        self._callback(point)

    def set_loading(self, loading):
        self._loading = bool(loading)
        try:
            self._canvas.setCursor(Qt.CursorShape.WaitCursor if self._loading else Qt.CursorShape.CrossCursor)
        except Exception as _e:
            _logger.debug("setCursor failed: %s", _e)

    def cancel(self, reason="cancel"):
        self._deactivate_reason = reason
        try:
            self._canvas.unsetMapTool(self)
        except Exception as _e:
            _logger.debug("unsetMapTool failed: %s", _e)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancel("escape")
            event.accept()
        else:
            super().keyPressEvent(event)

    def activate(self):
        super().activate()
        self._canvas.setCursor(Qt.CursorShape.WaitCursor if self._loading else Qt.CursorShape.CrossCursor)
        try:
            self._canvas.setFocus(Qt.FocusReason.OtherFocusReason)
        except Exception as _e:
            _logger.debug("setFocus failed: %s", _e)

    def deactivate(self):
        reason = self._deactivate_reason
        self._deactivate_reason = None
        self._loading = False
        try:
            self._canvas.unsetCursor()
        except Exception as _e:
            _logger.debug("unsetCursor failed: %s", _e)
        if self._on_deactivate:
            try:
                self._on_deactivate(reason)
            except TypeError:
                self._on_deactivate()
        super().deactivate()
