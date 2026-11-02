#!/usr/bin/env python3
"""Interaction contracts shared by the plugin sliders."""

import unittest
import unittest.mock
from unittest.mock import MagicMock


class TestRangeBarClicking(unittest.TestCase):
    def test_single_slider_track_click_jumps_to_position(self):
        from PyQt5.QtCore import Qt

        from bdc_loader_plugin.widgets.range_slider import JumpSlider

        slider = JumpSlider(Qt.Horizontal)
        slider.setRange(0, 100)
        handle = MagicMock()
        handle.contains.return_value = False
        slider._style_rects = lambda: (MagicMock(), handle)
        slider._value_from_position = lambda pos: 75
        event = MagicMock()
        event.button.return_value = Qt.LeftButton

        slider.mousePressEvent(event)

        self.assertEqual(slider.value(), 75)

    def test_a_press_on_the_handle_does_not_move_it(self):
        from PyQt5.QtCore import Qt

        from bdc_loader_plugin.widgets.range_slider import JumpSlider

        slider = JumpSlider(Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(40)
        handle = MagicMock()
        handle.contains.return_value = True
        slider._style_rects = lambda: (MagicMock(), handle)
        slider._value_from_position = lambda pos: 75
        event = MagicMock()
        event.button.return_value = Qt.LeftButton

        slider.mousePressEvent(event)

        self.assertEqual(slider.value(), 40)

    def test_single_slider_uses_open_and_closed_hand_during_drag(self):
        from PyQt5.QtCore import Qt

        from bdc_loader_plugin.widgets.range_slider import JumpSlider

        slider = JumpSlider(Qt.Horizontal)
        slider.setCursor = MagicMock()
        press = MagicMock()
        press.button.return_value = Qt.LeftButton
        press.pos.return_value.x.return_value = 300

        slider.mousePressEvent(press)

        self.assertTrue(slider._mouse_dragging)
        slider.setCursor.assert_called_with(Qt.ClosedHandCursor)

        release = MagicMock()
        release.button.return_value = Qt.LeftButton
        release.buttons.return_value = 0
        slider.mouseReleaseEvent(release)

        self.assertFalse(slider._mouse_dragging)
        slider.setCursor.assert_called_with(Qt.OpenHandCursor)

    def test_single_slider_recovers_if_mouse_release_was_lost(self):
        from PyQt5.QtCore import Qt

        from bdc_loader_plugin.widgets.range_slider import JumpSlider

        slider = JumpSlider(Qt.Horizontal)
        slider.setCursor = MagicMock()
        handle = MagicMock()
        handle.contains.return_value = True
        slider._style_rects = lambda: (MagicMock(), handle)
        slider._mouse_dragging = True
        move = MagicMock()
        move.buttons.return_value = 0

        slider.mouseMoveEvent(move)

        self.assertFalse(slider._mouse_dragging)
        slider.setCursor.assert_called_with(Qt.OpenHandCursor)

    def test_single_slider_shows_where_a_press_acts(self):
        from PyQt5.QtCore import Qt

        from bdc_loader_plugin.widgets.range_slider import JumpSlider

        slider = JumpSlider(Qt.Horizontal)
        slider.setCursor = MagicMock()
        handle = MagicMock()
        slider._style_rects = lambda: (MagicMock(), handle)
        move = MagicMock()
        move.buttons.return_value = 0

        handle.contains.return_value = True
        slider.mouseMoveEvent(move)
        slider.setCursor.assert_called_with(Qt.OpenHandCursor)
        handle.contains.return_value = False
        slider.mouseMoveEvent(move)
        slider.setCursor.assert_called_with(Qt.PointingHandCursor)

    def test_date_range_track_click_moves_nearest_handle(self):
        from PyQt5.QtCore import Qt

        from bdc_loader_plugin.widgets.range_slider import RangeBar

        bar = RangeBar()
        bar.set_range(0, 100)
        bar.set_values(20, 80)
        event = MagicMock()
        event.button.return_value = Qt.LeftButton
        event.pos.return_value.x.return_value = 250
        event.pos.return_value.y.return_value = bar._bar_y + bar._bar_height / 2

        bar.mousePressEvent(event)

        self.assertEqual(bar._dragging, "end")
        self.assertLess(bar._end, 80)
        bar.rangeChanged.emit.assert_called()

    def test_pressing_date_handle_does_not_jump_before_pointer_moves(self):
        from PyQt5.QtCore import Qt

        from bdc_loader_plugin.widgets.range_slider import RangeBar

        bar = RangeBar()
        bar.set_range(0, 100)
        bar.set_values(20, 80)
        bar.rangeChanged.emit.reset_mock()
        self.addCleanup(bar.rangeChanged.emit.reset_mock)
        bar.dragFinished.emit.reset_mock()
        self.addCleanup(bar.dragFinished.emit.reset_mock)
        start_x = bar._value_to_x(20)
        event = MagicMock()
        event.button.return_value = Qt.LeftButton
        event.pos.return_value.x.return_value = start_x + 4
        event.pos.return_value.y.return_value = bar._bar_y + bar._bar_height / 2

        bar.mousePressEvent(event)

        self.assertEqual(bar._dragging, "start")
        self.assertEqual((bar._start, bar._end), (20, 80))
        self.assertEqual(bar._drag_offset, 4)
        bar.rangeChanged.emit.assert_not_called()
        event.accept.assert_called_once()

        release = MagicMock()
        release.button.return_value = Qt.LeftButton
        release.buttons.return_value = 0
        bar.mouseReleaseEvent(release)
        bar.dragFinished.emit.assert_not_called()

    def test_date_handle_drag_preserves_grab_offset(self):
        from PyQt5.QtCore import Qt

        from bdc_loader_plugin.widgets.range_slider import RangeBar

        bar = RangeBar()
        bar.set_range(0, 100)
        bar.set_values(20, 80)
        bar.rangeChanged.emit.reset_mock()
        self.addCleanup(bar.rangeChanged.emit.reset_mock)
        start_x = bar._value_to_x(20)
        press = MagicMock()
        press.button.return_value = Qt.LeftButton
        press.pos.return_value.x.return_value = start_x + 4
        press.pos.return_value.y.return_value = bar._bar_y + bar._bar_height / 2
        bar.mousePressEvent(press)

        move = MagicMock()
        move.pos.return_value.x.return_value = start_x + 44
        move.buttons.return_value = Qt.LeftButton
        bar.mouseMoveEvent(move)

        expected = bar._x_to_value(start_x + 40)
        self.assertEqual(bar._start, expected)
        bar.rangeChanged.emit.assert_called_once_with(expected, 80)

    def test_date_drag_recovers_if_mouse_release_was_lost(self):
        from PyQt5.QtCore import Qt

        from bdc_loader_plugin.widgets.range_slider import RangeBar

        bar = RangeBar()
        bar.set_range(0, 100)
        bar.set_values(20, 80)
        bar.rangeChanged.emit.reset_mock()
        self.addCleanup(bar.rangeChanged.emit.reset_mock)
        bar.dragFinished.emit.reset_mock()
        self.addCleanup(bar.dragFinished.emit.reset_mock)
        press = MagicMock()
        press.button.return_value = Qt.LeftButton
        press.pos.return_value.x.return_value = 250
        press.pos.return_value.y.return_value = bar._bar_y + bar._bar_height / 2
        bar.mousePressEvent(press)
        values_after_press = (bar._start, bar._end)

        move = MagicMock()
        move.pos.return_value.x.return_value = bar._value_to_x(40)
        move.buttons.return_value = 0

        bar.mouseMoveEvent(move)

        self.assertFalse(bar.is_dragging)
        self.assertEqual((bar._start, bar._end), values_after_press)
        bar.dragFinished.emit.assert_called_once()

    def test_date_drag_release_emits_finished_once(self):
        from PyQt5.QtCore import Qt

        from bdc_loader_plugin.widgets.range_slider import RangeBar

        bar = RangeBar()
        bar.set_range(0, 100)
        bar.set_values(20, 80)
        bar.rangeChanged.emit.reset_mock()
        self.addCleanup(bar.rangeChanged.emit.reset_mock)
        bar.dragFinished.emit.reset_mock()
        self.addCleanup(bar.dragFinished.emit.reset_mock)
        press = MagicMock()
        press.button.return_value = Qt.LeftButton
        press.pos.return_value.x.return_value = 250
        press.pos.return_value.y.return_value = bar._bar_y + bar._bar_height / 2
        bar.mousePressEvent(press)

        event = MagicMock()
        event.button.return_value = Qt.LeftButton
        event.buttons.return_value = 0

        bar.mouseReleaseEvent(event)
        bar.mouseReleaseEvent(event)

        self.assertFalse(bar.is_dragging)
        bar.dragFinished.emit.assert_called_once()
        event.accept.assert_called()

    def test_date_range_click_above_or_below_bar_is_ignored(self):
        """Clicks in the widget's dead space (reserved for tick labels/tooltips
        above and below the drawn bar) must not move a handle — only clicks on
        the bar itself do."""
        from PyQt5.QtCore import Qt

        from bdc_loader_plugin.widgets.range_slider import RangeBar

        bar = RangeBar()
        bar.set_range(0, 100)
        bar.set_values(20, 80)
        event = MagicMock()
        event.button.return_value = Qt.LeftButton
        event.pos.return_value.x.return_value = 250
        event.pos.return_value.y.return_value = bar._bar_y - 20

        bar.mousePressEvent(event)

        self.assertIsNone(bar._dragging)
        self.assertEqual((bar._start, bar._end), (20, 80))
        bar.rangeChanged.emit.assert_not_called()

    def test_overlapped_date_handles_can_separate_by_track_click(self):
        from PyQt5.QtCore import Qt

        from bdc_loader_plugin.widgets.range_slider import RangeBar

        bar = RangeBar()
        bar.set_range(0, 100)
        bar.set_values(50, 50)
        event = MagicMock()
        event.button.return_value = Qt.LeftButton
        event.pos.return_value.x.return_value = 150
        event.pos.return_value.y.return_value = bar._bar_y + bar._bar_height / 2

        bar.mousePressEvent(event)

        self.assertEqual(bar._dragging, "start")
        self.assertLess(bar._start, bar._end)

    def test_chart_range_track_click_moves_nearest_handle(self):
        from PyQt5.QtCore import Qt

        from bdc_loader_plugin.widgets.range_bar import AxisRangeBar

        bar = AxisRangeBar(orientation="horizontal")
        bar.set_data_range(0.0, 100.0)
        bar.set_view_range(20.0, 80.0)
        event = MagicMock()
        event.button.return_value = Qt.LeftButton
        event.pos.return_value.x.return_value = 250
        event.pos.return_value.y.return_value = bar.height() // 2

        bar.mousePressEvent(event)

        self.assertEqual(bar._dragging, "max")
        self.assertLess(bar._view_max, 80.0)
        bar.rangeChanged.emit.assert_called()

    def test_chart_range_click_above_or_below_bar_is_ignored(self):
        from PyQt5.QtCore import Qt

        from bdc_loader_plugin.widgets.range_bar import AxisRangeBar

        bar = AxisRangeBar(orientation="horizontal")
        bar.set_data_range(0.0, 100.0)
        bar.set_view_range(20.0, 80.0)
        event = MagicMock()
        event.button.return_value = Qt.LeftButton
        event.pos.return_value.x.return_value = 250
        event.pos.return_value.y.return_value = 0

        bar.mousePressEvent(event)

        self.assertIsNone(bar._dragging)
        self.assertEqual((bar._view_min, bar._view_max), (20.0, 80.0))
        bar.rangeChanged.emit.assert_not_called()

    def test_chart_range_handles_never_share_the_same_position(self):
        from bdc_loader_plugin.widgets.range_bar import AxisRangeBar

        bar = AxisRangeBar(orientation="horizontal")
        bar.set_data_range(0.0, 100.0)

        bar.set_view_range(50.0, 50.0)

        self.assertLess(bar._view_min, bar._view_max)


class TestResultDateFilterScheduling(unittest.TestCase):
    def test_a_drag_of_the_date_bar_filters_live(self):
        from bdc_loader_plugin.core.filters import ResultFilter

        owner = MagicMock()
        owner.filter_range_slider.range_bar.is_dragging = True

        ResultFilter._on_filter_range_changed(owner, 10, 20)
        ResultFilter._on_filter_range_changed_from_edit(owner, MagicMock())

        self.assertEqual(owner._schedule_filter_update.call_args_list, [unittest.mock.call(), unittest.mock.call()])

    def test_a_typed_date_waits_and_the_end_of_a_drag_applies_at_once(self):
        from bdc_loader_plugin.core.filters import ResultFilter

        owner = MagicMock()
        owner.filter_range_slider.range_bar.is_dragging = False
        ResultFilter._on_filter_range_changed_from_edit(owner, MagicMock())
        owner._schedule_filter_update.assert_called_once_with(wait_ms=400)

        owner._schedule_filter_update.reset_mock()
        ResultFilter._on_filter_range_drag_finished(owner)
        owner._schedule_filter_update.assert_called_once_with(wait_ms=0)


class TestRangeBarGrabArea(unittest.TestCase):
    """The hand cursor shows exactly where a press grabs a handle without moving it."""

    def _bar(self):
        from bdc_loader_plugin.widgets.range_slider import RangeBar

        bar = RangeBar()
        bar.width = lambda: 414
        bar._min, bar._max, bar._start, bar._end = 0, 400, 100, 300
        bar.setCursor = MagicMock()
        return bar

    def _event(self, x, y):
        from PyQt5.QtCore import Qt

        event = MagicMock()
        event.pos.return_value.x.return_value = x
        event.pos.return_value.y.return_value = y
        event.buttons.return_value = 0
        event.button.return_value = Qt.LeftButton
        return event

    def test_hover_and_press_share_one_area(self):
        from PyQt5.QtCore import Qt

        bar = self._bar()
        handle_x = bar._value_to_x(bar._start)
        center_y = bar._bar_y + bar._bar_height / 2
        for dx, dy, grabbed in ((0, 0, True), (9, 9, True), (12, 0, False), (0, 14, False)):
            event = self._event(handle_x + dx, center_y + dy)
            self.assertEqual(bar._handle_under(event) == "start", grabbed, (dx, dy))
            bar.mouseMoveEvent(event)
            shown = bar.setCursor.call_args[0][0]
            self.assertEqual(shown == Qt.OpenHandCursor, grabbed, (dx, dy))

    def test_a_press_on_the_handle_keeps_its_date(self):
        bar = self._bar()
        handle_x = bar._value_to_x(bar._start)
        bar.mousePressEvent(self._event(handle_x + 8, bar._bar_y + bar._bar_height / 2))
        self.assertEqual(bar._start, 100)
        self.assertEqual(bar._dragging, "start")
