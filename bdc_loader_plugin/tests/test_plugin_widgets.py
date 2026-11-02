#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_plugin_widgets.py — tests for the main plugin, widgets and vendored

Covers: BDCLoaderPlugin lifecycle, PointPickerTool, RangeBar,
vendored, edge cases, exceptions.

Run: python3 -m pytest bdc_loader_plugin/tests/test_plugin_widgets.py -v
"""

import os
import unittest
from unittest.mock import MagicMock, patch

from PyQt5.QtCore import Qt

# ── Plugin Principal Tests ────────────────────────────────────────────────────


class TestBDCLoaderPluginInit(unittest.TestCase):
    """Plugin start-up tests."""

    def test_plugin_init(self):
        from bdc_loader_plugin.bdc_loader_plugin import BDCLoaderPlugin

        iface = MagicMock()
        plugin = BDCLoaderPlugin(iface)
        self.assertEqual(plugin.iface, iface)
        self.assertIsNone(plugin.action_loader)
        self.assertIsNone(plugin.dialog)

    def test_plugin_dir_set(self):
        from bdc_loader_plugin.bdc_loader_plugin import BDCLoaderPlugin

        iface = MagicMock()
        plugin = BDCLoaderPlugin(iface)
        self.assertTrue(os.path.isdir(plugin.plugin_dir))

    def test_init_gui(self):
        from bdc_loader_plugin.bdc_loader_plugin import BDCLoaderPlugin

        iface = MagicMock()
        plugin = BDCLoaderPlugin(iface)
        plugin.initGui()
        self.assertIsNotNone(plugin.action_loader)
        self.assertIsNotNone(plugin.action_ts)
        # Two raster menu entries: Loader + Time Series
        self.assertEqual(iface.addPluginToRasterMenu.call_count, 2)

    def test_unload(self):
        from bdc_loader_plugin.bdc_loader_plugin import BDCLoaderPlugin

        iface = MagicMock()
        plugin = BDCLoaderPlugin(iface)
        plugin.initGui()
        plugin.unload()
        # Two raster menu entries removed: Loader + Time Series
        self.assertEqual(iface.removePluginRasterMenu.call_count, 2)

    def test_unload_with_dialog(self):
        from bdc_loader_plugin.bdc_loader_plugin import BDCLoaderPlugin

        iface = MagicMock()
        plugin = BDCLoaderPlugin(iface)
        plugin.initGui()

        # The dialog is open
        mock_dialog = MagicMock()
        mock_dialog._ts_panel = None
        plugin.dialog = mock_dialog

        plugin.unload()
        mock_dialog.close.assert_called_once()
        self.assertIsNone(plugin.dialog)

    def test_unload_with_ts_panel(self):
        from bdc_loader_plugin.bdc_loader_plugin import BDCLoaderPlugin

        iface = MagicMock()
        plugin = BDCLoaderPlugin(iface)
        plugin.initGui()

        mock_ts_panel = MagicMock()
        mock_chart_dock = MagicMock()
        mock_ts_panel.chart_dock = mock_chart_dock
        mock_dialog = MagicMock()
        mock_dialog._ts_panel = mock_ts_panel
        plugin.dialog = mock_dialog

        plugin.unload()
        iface.removeDockWidget.assert_called()
        mock_chart_dock.close.assert_called_once()

    def test_run_creates_dialog(self):
        from bdc_loader_plugin.bdc_loader_plugin import BDCLoaderPlugin

        iface = MagicMock()
        plugin = BDCLoaderPlugin(iface)
        main_dialog = MagicMock()

        with patch.dict("sys.modules", {"bdc_loader_plugin.ui.main_dialog": main_dialog}):
            plugin.run()

        main_dialog.BDCLoaderDialog.assert_called_once_with(iface, timeline_toolbar=plugin.timeline_toolbar)
        self.assertIs(plugin.dialog, main_dialog.BDCLoaderDialog.return_value)
        plugin.dialog.show.assert_called_once_with()

    def test_run_reuses_dialog(self):
        from bdc_loader_plugin.bdc_loader_plugin import BDCLoaderPlugin

        iface = MagicMock()
        plugin = BDCLoaderPlugin(iface)
        mock_dialog = MagicMock()
        plugin.dialog = mock_dialog

        # When dialog already exists, run() should reuse it
        with patch.dict("sys.modules", {"bdc_loader_plugin.ui.main_dialog": MagicMock()}):
            plugin.run()
        mock_dialog.show.assert_called_once()
        mock_dialog.raise_.assert_called_once()
        mock_dialog.activateWindow.assert_called_once()

    def test_unload_without_init_gui(self):
        """Unload without initGui does not raise."""
        from bdc_loader_plugin.bdc_loader_plugin import BDCLoaderPlugin

        iface = MagicMock()
        plugin = BDCLoaderPlugin(iface)
        plugin.action_loader = MagicMock()
        plugin.action_ts = MagicMock()
        plugin.unload()
        iface.removePluginRasterMenu.assert_any_call("&BDC Loader", plugin.action_loader)
        iface.removePluginRasterMenu.assert_any_call("&BDC Loader", plugin.action_ts)


# ── PointPickerTool Tests ─────────────────────────────────────────────────────


class TestPointPickerTool(unittest.TestCase):
    """Tests for the PointPickerTool widget."""

    def test_init(self):
        from bdc_loader_plugin.widgets.point_picker import PointPickerTool

        canvas = MagicMock()
        callback = MagicMock()
        tool = PointPickerTool(canvas, callback)
        self.assertEqual(tool._callback, callback)
        self.assertEqual(tool._canvas, canvas)

    def test_canvas_release_calls_callback(self):
        from bdc_loader_plugin.widgets.point_picker import PointPickerTool

        canvas = MagicMock()
        callback = MagicMock()
        tool = PointPickerTool(canvas, callback)

        event = MagicMock()
        tool.canvasReleaseEvent(event)
        callback.assert_called_once()

    def test_activate_sets_cursor(self):
        from bdc_loader_plugin.widgets.point_picker import PointPickerTool

        canvas = MagicMock()
        callback = MagicMock()
        tool = PointPickerTool(canvas, callback)
        tool.activate()
        canvas.setCursor.assert_called()

    def test_escape_unsets_maptool(self):
        from bdc_loader_plugin.widgets.point_picker import PointPickerTool

        canvas = MagicMock()
        callback = MagicMock()
        tool = PointPickerTool(canvas, callback)

        event = MagicMock()
        event.key.return_value = Qt.Key_Escape

        tool.keyPressEvent(event)

        canvas.unsetMapTool.assert_called_once_with(tool)
        event.accept.assert_called_once()

    def test_deactivate_callback_receives_reason(self):
        from bdc_loader_plugin.widgets.point_picker import PointPickerTool

        canvas = MagicMock()
        callback = MagicMock()
        on_deactivate = MagicMock()
        tool = PointPickerTool(canvas, callback, on_deactivate=on_deactivate)

        tool.cancel("escape")
        tool.deactivate()

        on_deactivate.assert_called_once_with("escape")

    def test_deactivate_safe(self):
        from bdc_loader_plugin.widgets.point_picker import PointPickerTool

        canvas = MagicMock()
        callback = MagicMock()
        tool = PointPickerTool(canvas, callback)
        # Works even when unsetCursor fails
        canvas.unsetCursor.side_effect = RuntimeError("Mock error")
        tool.deactivate()
        canvas.unsetCursor.assert_called_once_with()

    def test_clicks_are_ignored_while_loading(self):
        from bdc_loader_plugin.widgets.point_picker import PointPickerTool

        canvas = MagicMock()
        callback = MagicMock()
        tool = PointPickerTool(canvas, callback)
        tool.toMapCoordinates = MagicMock(return_value="point")

        tool.set_loading(True)
        canvas.setCursor.assert_called_with(Qt.WaitCursor)
        tool.canvasReleaseEvent(MagicMock())
        callback.assert_not_called()

        tool.set_loading(False)
        canvas.setCursor.assert_called_with(Qt.CrossCursor)
        tool.canvasReleaseEvent(MagicMock())
        callback.assert_called_once_with("point")

    def test_canvas_release_ignored_while_loading(self):
        from bdc_loader_plugin.widgets.point_picker import PointPickerTool

        canvas = MagicMock()
        callback = MagicMock()
        tool = PointPickerTool(canvas, callback)
        tool.set_loading(True)

        event = MagicMock()
        tool.canvasReleaseEvent(event)

        callback.assert_not_called()
        event.accept.assert_called_once()


# ── RangeBar Tests ────────────────────────────────────────────────────────────


class TestRangeBar(unittest.TestCase):
    """Tests for the RangeBar widget."""

    def test_init_defaults(self):
        from bdc_loader_plugin.widgets.range_slider import RangeBar

        bar = RangeBar()
        self.assertEqual(bar._min, 0)
        self.assertEqual(bar._max, 100)
        self.assertEqual(bar._start, 0)
        self.assertEqual(bar._end, 100)

    def test_set_range(self):
        from bdc_loader_plugin.widgets.range_slider import RangeBar

        bar = RangeBar()
        bar.set_range(10, 200)
        self.assertEqual(bar._min, 10)
        self.assertEqual(bar._max, 200)

    def test_set_values(self):
        from bdc_loader_plugin.widgets.range_slider import RangeBar

        bar = RangeBar()
        bar.set_range(0, 100)
        bar.set_values(20, 80)
        self.assertEqual(bar._start, 20)
        self.assertEqual(bar._end, 80)

    def test_set_values_clamped_to_range(self):
        from bdc_loader_plugin.widgets.range_slider import RangeBar

        bar = RangeBar()
        bar.set_range(0, 100)
        bar.set_values(-10, 150)
        self.assertEqual(bar._start, 0)
        self.assertEqual(bar._end, 100)

    def test_set_values_swapped(self):
        from bdc_loader_plugin.widgets.range_slider import RangeBar

        bar = RangeBar()
        bar.set_range(0, 100)
        bar.set_values(80, 20)
        self.assertEqual(bar._start, 20)
        self.assertEqual(bar._end, 80)

    def test_value_to_x_conversion(self):
        from bdc_loader_plugin.widgets.range_slider import RangeBar

        bar = RangeBar()
        bar.set_range(0, 100)
        x_min = bar._value_to_x(0)
        x_max = bar._value_to_x(100)
        self.assertLess(x_min, x_max)

    def test_x_to_value_conversion(self):
        from bdc_loader_plugin.widgets.range_slider import RangeBar

        bar = RangeBar()
        bar.set_range(0, 100)
        val = bar._x_to_value(bar._handle_width)
        self.assertEqual(val, 0)

    def test_same_min_max(self):
        from bdc_loader_plugin.widgets.range_slider import RangeBar

        bar = RangeBar()
        bar.set_range(50, 50)
        x = bar._value_to_x(50)
        self.assertEqual(x, bar._handle_width)

    def test_snap_to_year(self):
        from bdc_loader_plugin.widgets.range_slider import RangeBar

        bar = RangeBar()
        bar._min, bar._max = 0, 200
        bar.width = lambda: 214  # 0.93 px per unit between the 14 px handles
        bar._year_positions = [(0, 2020), (100, 2021), (200, 2022)]
        # 3 units from 1 January are under 4 px on screen: the handle snaps.
        self.assertEqual(bar._snap_to_year(103), 100)

    def test_snap_not_near_year(self):
        from bdc_loader_plugin.widgets.range_slider import RangeBar

        bar = RangeBar()
        bar._min, bar._max = 0, 200
        bar.width = lambda: 214
        bar._year_positions = [(0, 2020), (100, 2021)]
        # 10 units are 9 px away on screen: no snap.
        self.assertEqual(bar._snap_to_year(110), 110)
        self.assertEqual(bar._snap_to_year(50), 50)


# ── Install Dependencies Tests ────────────────────────────────────────────────


class TestInstallDependencies(unittest.TestCase):
    """Tests for vendored.py."""

    def test_ensure_pystac_client_returns_module(self):
        """With the vendored lib/, the module is returned."""
        from bdc_loader_plugin.vendored import ensure_pystac_client

        module = ensure_pystac_client()
        self.assertEqual(module.__name__, "bdc_loader_plugin.lib.pystac_client")
        self.assertTrue(hasattr(module, "Client"))
        # No unhandled exception


# ── Plugin Structure Tests ────────────────────────────────────────────────────


class TestPluginStructure(unittest.TestCase):
    """File layout of the plugin."""

    def setUp(self):
        self.plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_icon_exists(self):
        icon_path = os.path.join(self.plugin_dir, "icon.png")
        self.assertTrue(os.path.isfile(icon_path), "Missing icon.png")

    def test_metadata_has_content(self):
        meta_path = os.path.join(self.plugin_dir, "metadata.txt")
        with open(meta_path, "r") as f:
            content = f.read()
        self.assertIn("name=", content)
        self.assertIn("version=", content)


if __name__ == "__main__":
    unittest.main()
