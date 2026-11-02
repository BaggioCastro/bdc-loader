"""
qt_compat.py

Helpers for Qt APIs that differ between PyQt5 (QGIS 3) and PyQt6 (QGIS 4).
"""


def event_global_pos(event):
    """Return the global position of a mouse event as a QPoint.

    PyQt6 only provides ``globalPosition()`` (QPointF); PyQt5 only provides ``globalPos()``.
    """
    if hasattr(event, "globalPosition"):
        return event.globalPosition().toPoint()
    return event.globalPos()
