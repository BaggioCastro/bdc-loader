"""Tests for the PyQt5/PyQt6 compatibility helpers."""

from types import SimpleNamespace

from bdc_loader_plugin.qt_compat import event_global_pos


def test_event_global_pos_uses_global_position_when_available():
    """PyQt6 events only expose globalPosition(), a QPointF converted with toPoint()."""
    point = object()
    event = SimpleNamespace(globalPosition=lambda: SimpleNamespace(toPoint=lambda: point))

    assert event_global_pos(event) is point


def test_event_global_pos_falls_back_to_global_pos():
    """PyQt5 events only expose globalPos(), which already returns a QPoint."""
    point = object()
    event = SimpleNamespace(globalPos=lambda: point)

    assert event_global_pos(event) is point
