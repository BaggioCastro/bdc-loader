#!/usr/bin/env python3
"""Interaction contracts for chart range locking and portable dock dragging."""

import unittest
from unittest.mock import MagicMock, patch


class TestChartRangeLock(unittest.TestCase):
    def test_lock_captures_current_x_and_y_ranges(self):
        from bdc_loader_plugin.chart.dock import ChartDock

        dock = ChartDock.__new__(ChartDock)
        dock.y_range_bar = MagicMock()
        dock.x_range_bar = MagicMock()
        dock.y_range_bar.get_view_range.return_value = (-25.0, 900.0)
        dock.x_range_bar.get_view_range.return_value = (100.0, 200.0)
        dock.range_lock_btn = MagicMock()

        dock._on_range_lock_toggled(True)

        self.assertTrue(dock._range_locked)
        self.assertEqual(dock._y_range, (-25.0, 900.0))
        self.assertEqual(dock._x_range, (100.0, 200.0))
        self.assertTrue(dock._y_user_adjusted)
        self.assertTrue(dock._x_user_adjusted)

    def test_series_reset_does_not_discard_locked_range(self):
        from bdc_loader_plugin.chart.dock import ChartDock

        dock = ChartDock.__new__(ChartDock)
        dock._range_locked = True
        dock._y_range = (10.0, 20.0)
        dock._x_range = (30.0, 40.0)
        dock.y_range_bar = MagicMock()
        dock.x_range_bar = MagicMock()

        dock.reset_axis_ranges()

        self.assertEqual(dock._y_range, (10.0, 20.0))
        self.assertEqual(dock._x_range, (30.0, 40.0))
        dock.y_range_bar.reset.assert_not_called()

    def test_unlock_restores_dynamic_range_and_replots(self):
        from bdc_loader_plugin.chart.dock import ChartDock

        dock = ChartDock.__new__(ChartDock)
        dock._range_locked = True
        dock.range_lock_btn = MagicMock()
        dock.reset_axis_ranges = MagicMock()
        dock._parent_panel = MagicMock()

        dock._on_range_lock_toggled(False)

        dock.reset_axis_ranges.assert_called_once_with(force=True)
        dock._parent_panel._replot_current.assert_called_once()

    def test_locked_range_remains_available_outside_next_series_extent(self):
        from bdc_loader_plugin.chart.dock import ChartDock

        dock = ChartDock.__new__(ChartDock)
        dock._range_locked = True
        dock._y_range = (-100.0, 100.0)
        dock._x_range = None
        dock._y_user_adjusted = True
        dock._x_user_adjusted = False
        dock.y_range_bar = MagicMock()
        dock.x_range_bar = MagicMock()

        dock.update_axis_ranges_from_data([], [10.0, 20.0])

        dock.y_range_bar.set_data_range.assert_called_once_with(-100.0, 100.0)
        dock.y_range_bar.set_view_range.assert_called_once_with(-100.0, 100.0)


class TestChartModeRows(unittest.TestCase):
    def test_the_row_that_goes_hides_before_the_other_shows(self):
        """Shown together for a moment, the two rows make QGIS grow the dock for good."""
        from bdc_loader_plugin.chart.dock import ChartDock

        calls = []
        dock = ChartDock.__new__(ChartDock)
        dock.line_config_widget = MagicMock()
        dock.rgb_config_widget = MagicMock()
        dock.line_config_widget.setVisible.side_effect = lambda v: calls.append(("line", v))
        dock.rgb_config_widget.setVisible.side_effect = lambda v: calls.append(("rgb", v))

        dock.set_rgb_mode(True)
        dock.set_rgb_mode(False)

        self.assertEqual(calls, [("line", False), ("rgb", True), ("rgb", False), ("line", True)])


class _Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __sub__(self, other):
        return _Point(self.x - other.x, self.y - other.y)

    def manhattanLength(self):
        return abs(self.x) + abs(self.y)


class TestPortableChartDockDragging(unittest.TestCase):
    def test_title_drag_uses_platform_system_move_when_available(self):
        from PyQt5.QtCore import Qt

        from bdc_loader_plugin.chart.dock_widgets import _DraggableDockTitleBar

        dock = MagicMock()
        dock.mapToGlobal.return_value = _Point(80, 80)
        dock.isFloating.return_value = False
        dock.windowHandle.return_value.startSystemMove.return_value = True
        title = _DraggableDockTitleBar(dock)

        press = MagicMock()
        press.button.return_value = Qt.LeftButton
        press.globalPosition.return_value.toPoint.return_value = _Point(100, 100)
        title.mousePressEvent(press)

        move = MagicMock()
        move.buttons.return_value = Qt.LeftButton
        move.globalPosition.return_value.toPoint.return_value = _Point(130, 130)
        with patch("bdc_loader_plugin.chart.dock.QApplication.startDragDistance", return_value=10):
            title.mouseMoveEvent(move)

        dock.setFloating.assert_called_once_with(True)
        dock.windowHandle.return_value.startSystemMove.assert_called_once()
