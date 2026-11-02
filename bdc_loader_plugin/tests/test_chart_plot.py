#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_chart_plot.py — Tests for chart/plot.py functions.

Covers: plot_line_chart, plot_rgb_dots, apply_axis_ranges, BAND_COLORS.

Run: python3 -m pytest bdc_loader_plugin/tests/test_chart_plot.py -v
"""

import unittest
from datetime import datetime
from unittest.mock import MagicMock


def _make_chart_dock(**overrides):
    """Build a mock chart dock with reasonable defaults."""
    dock = MagicMock()
    dock.figure = MagicMock()
    dock.canvas_plot = MagicMock()
    dock._hidden_bands = set()
    dock._y_user_adjusted = False
    dock._x_user_adjusted = False
    dock._rgb_user_adjusted = False
    dock.get_effective_y_range.return_value = None
    dock.get_effective_x_range.return_value = None
    dock.get_rgb_params.return_value = (0, 10000, 40, 2, 98)
    dock.rgb_r_combo = MagicMock()
    dock.rgb_g_combo.currentData.return_value = "green"
    dock.rgb_r_combo.currentData.return_value = "red"
    dock.rgb_b_combo = MagicMock()
    dock.rgb_b_combo.currentData.return_value = "blue"
    dock.rgb_y_combo = MagicMock()
    dock.rgb_y_combo.currentData.return_value = None
    dock._rgb_min_spin = MagicMock()
    dock._rgb_max_spin = MagicMock()
    for key, val in overrides.items():
        setattr(dock, key, val)
    return dock


def _make_hist_entry(**overrides):
    """Build a minimal history entry dict."""
    entry = {
        "collection": "S2-16D-2",
        "label": "Point_1",
        "lon": -45.0,
        "lat": -12.0,
        "start": "2023-01-01",
        "end": "2023-12-31",
        "bands": ["NDVI", "EVI"],
        "data": {
            "NDVI": [
                (datetime(2023, 1, 1), 5000.0),
                (datetime(2023, 2, 1), 6000.0),
                (datetime(2023, 3, 1), 7000.0),
            ],
            "EVI": [
                (datetime(2023, 1, 1), 3000.0),
                (datetime(2023, 2, 1), 4000.0),
                (datetime(2023, 3, 1), 5000.0),
            ],
        },
        "id": 1,
    }
    entry.update(overrides)
    return entry


class TestBandColors(unittest.TestCase):
    """Tests for BAND_COLORS constant."""

    def test_at_least_ten_colors(self):
        from bdc_loader_plugin.chart.plot import BAND_COLORS

        self.assertGreaterEqual(len(BAND_COLORS), 10)

    def test_all_hex_colors(self):
        from bdc_loader_plugin.chart.plot import BAND_COLORS

        for color in BAND_COLORS:
            self.assertTrue(color.startswith("#"), f"Not hex: {color}")
            self.assertEqual(len(color), 7, f"Invalid hex length: {color}")


class TestApplyAxisRanges(unittest.TestCase):
    """Tests for apply_axis_ranges."""

    def test_none_dock(self):
        from bdc_loader_plugin.chart.plot import apply_axis_ranges

        ax = MagicMock()
        apply_axis_ranges(ax, None)
        ax.set_ylim.assert_not_called()

    def test_y_range_applied(self):
        from bdc_loader_plugin.chart.plot import apply_axis_ranges

        ax = MagicMock()
        dock = MagicMock()
        dock.get_effective_y_range.return_value = (100, 9000)
        dock.get_effective_x_range.return_value = None
        apply_axis_ranges(ax, dock)
        ax.set_ylim.assert_called_once_with(100, 9000)

    def test_x_range_applied(self):
        from bdc_loader_plugin.chart.plot import apply_axis_ranges

        ax = MagicMock()
        dock = MagicMock()
        dock.get_effective_y_range.return_value = None
        dock.get_effective_x_range.return_value = (10000, 20000)
        apply_axis_ranges(ax, dock)
        ax.set_xlim.assert_called_once()


class TestPlotLineChart(unittest.TestCase):
    """Tests for plot_line_chart."""

    def test_basic_plot(self):
        from bdc_loader_plugin.chart.plot import plot_line_chart

        dock = _make_chart_dock()
        ax = MagicMock()
        dock.figure.add_subplot.return_value = ax

        entry = _make_hist_entry()
        plot_line_chart(dock, entry)

        dock.figure.clear.assert_called_once()
        ax.plot.assert_called()
        dock.canvas_plot.draw_idle.assert_called_once()
        dock.canvas_plot.draw.assert_not_called()

    def test_empty_data(self):
        from bdc_loader_plugin.chart.plot import plot_line_chart

        dock = _make_chart_dock()
        ax = MagicMock()
        dock.figure.add_subplot.return_value = ax

        entry = _make_hist_entry(data={}, bands=[])
        plot_line_chart(dock, entry)

        # Should show "No valid data" text
        ax.text.assert_called_once()
        dock.canvas_plot.draw_idle.assert_called_once()
        dock.canvas_plot.draw.assert_not_called()

    def test_hidden_bands_excluded(self):
        from bdc_loader_plugin.chart.plot import plot_line_chart

        dock = _make_chart_dock()
        dock._hidden_bands = {"NDVI"}
        ax = MagicMock()
        dock.figure.add_subplot.return_value = ax

        entry = _make_hist_entry()
        plot_line_chart(dock, entry)

        # Only EVI should be plotted
        self.assertEqual(ax.plot.call_count, 1)

    def test_all_bands_hidden(self):
        from bdc_loader_plugin.chart.plot import plot_line_chart

        dock = _make_chart_dock()
        dock._hidden_bands = {"NDVI", "EVI"}
        ax = MagicMock()
        dock.figure.add_subplot.return_value = ax

        entry = _make_hist_entry()
        plot_line_chart(dock, entry)

        ax.text.assert_called_once()

    def test_user_adjusted_y_applies_ranges(self):
        from bdc_loader_plugin.chart.plot import plot_line_chart

        dock = _make_chart_dock()
        dock._y_user_adjusted = True
        dock.get_effective_y_range.return_value = (1000, 8000)
        dock.get_effective_x_range.return_value = None
        ax = MagicMock()
        dock.figure.add_subplot.return_value = ax

        entry = _make_hist_entry()
        plot_line_chart(dock, entry)

        ax.set_ylim.assert_called_with(1000, 8000)


class TestPlotRgbDots(unittest.TestCase):
    """Tests for plot_rgb_dots."""

    def _make_rgb_entry(self):
        """Data with 3 RGB bands sharing common dates."""
        dates = [datetime(2023, 1, 1), datetime(2023, 2, 1), datetime(2023, 3, 1)]
        return _make_hist_entry(
            bands=["red", "green", "blue"],
            data={
                "red": [(d, 2000 + i * 1000) for i, d in enumerate(dates)],
                "green": [(d, 3000 + i * 500) for i, d in enumerate(dates)],
                "blue": [(d, 1500 + i * 800) for i, d in enumerate(dates)],
            },
        )

    def test_basic_rgb_scatter(self):
        from bdc_loader_plugin.chart.plot import plot_rgb_dots

        dock = _make_chart_dock()
        ax = MagicMock()
        dock.figure.add_subplot.return_value = ax

        entry = self._make_rgb_entry()
        plot_rgb_dots(dock, entry)

        # Should have scatter calls (shadow + core = 2)
        self.assertEqual(ax.scatter.call_count, 2)
        dock.canvas_plot.draw_idle.assert_called_once()
        dock.canvas_plot.draw.assert_not_called()

    def test_missing_bands_shows_message(self):
        from bdc_loader_plugin.chart.plot import plot_rgb_dots

        dock = _make_chart_dock()
        dock.rgb_r_combo.currentData.return_value = None
        ax = MagicMock()
        dock.figure.add_subplot.return_value = ax

        entry = self._make_rgb_entry()
        plot_rgb_dots(dock, entry)

        ax.text.assert_called_once()
        dock.canvas_plot.draw_idle.assert_called_once()
        dock.canvas_plot.draw.assert_not_called()

    def test_no_common_dates_shows_message(self):
        from bdc_loader_plugin.chart.plot import plot_rgb_dots

        dock = _make_chart_dock()
        ax = MagicMock()
        dock.figure.add_subplot.return_value = ax

        entry = _make_hist_entry(
            bands=["red", "green", "blue"],
            data={
                "red": [(datetime(2023, 1, 1), 5000)],
                "green": [(datetime(2023, 2, 1), 5000)],  # different date
                "blue": [(datetime(2023, 3, 1), 5000)],  # different date
            },
        )
        plot_rgb_dots(dock, entry)

        ax.text.assert_called_once()

    def test_auto_stretch_fills_spinboxes(self):
        from bdc_loader_plugin.chart.plot import plot_rgb_dots

        dock = _make_chart_dock()
        ax = MagicMock()
        dock.figure.add_subplot.return_value = ax

        plot_rgb_dots(dock, self._make_rgb_entry())

        # The automatic range is shown in the Min/Max spinboxes
        dock._rgb_min_spin.setValue.assert_called()
        dock._rgb_max_spin.setValue.assert_called()

    def test_y_band_decoupled(self):
        from bdc_loader_plugin.chart.plot import plot_rgb_dots

        dock = _make_chart_dock()
        dock.rgb_y_combo.currentData.return_value = "NDVI"
        ax = MagicMock()
        dock.figure.add_subplot.return_value = ax

        dates = [datetime(2023, 1, 1), datetime(2023, 2, 1)]
        entry = _make_hist_entry(
            bands=["red", "green", "blue", "NDVI"],
            data={
                "red": [(d, 2000 + i * 1000) for i, d in enumerate(dates)],
                "green": [(d, 3000 + i * 500) for i, d in enumerate(dates)],
                "blue": [(d, 1500 + i * 800) for i, d in enumerate(dates)],
                "NDVI": [(d, 5000 + i * 1000) for i, d in enumerate(dates)],
            },
        )
        plot_rgb_dots(dock, entry)

        self.assertEqual(ax.scatter.call_count, 2)

    def test_user_adjusted_rgb_keeps_spinboxes(self):
        from bdc_loader_plugin.chart.plot import plot_rgb_dots

        dock = _make_chart_dock()
        dock._rgb_user_adjusted = True
        ax = MagicMock()
        dock.figure.add_subplot.return_value = ax

        plot_rgb_dots(dock, self._make_rgb_entry())

        # A manual Min/Max is not overwritten by the automatic range
        dock._rgb_min_spin.setValue.assert_not_called()


if __name__ == "__main__":
    unittest.main()
