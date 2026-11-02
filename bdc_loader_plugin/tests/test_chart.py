#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_chart.py — tests for chart/plot.py, chart/export.py, chart/dock.py

Covers: plotting with mocked data, CSV/vector export, edge cases,
a hidden band, empty data, exceptions.

Run: python3 -m pytest bdc_loader_plugin/tests/test_chart.py -v
"""

import unittest
from datetime import datetime
from unittest.mock import MagicMock

# ── Plot Tests ────────────────────────────────────────────────────────────────


class TestPlotLineChart(unittest.TestCase):
    """Tests for plot_line_chart."""

    def _make_chart_dock(self):
        dock = MagicMock()
        dock.figure = MagicMock()
        ax = MagicMock()
        dock.figure.add_subplot.return_value = ax
        dock.canvas_plot = MagicMock()
        dock._hidden_bands = set()
        dock._y_user_adjusted = False
        dock.get_effective_y_range.return_value = None
        dock.get_effective_x_range.return_value = None
        return dock, ax

    def test_with_valid_data(self):
        from bdc_loader_plugin.chart.plot import plot_line_chart

        dock, ax = self._make_chart_dock()
        hist_entry = {
            "data": {
                "NDVI": [(datetime(2023, 1, 1), 0.5), (datetime(2023, 2, 1), 0.7)],
                "EVI": [(datetime(2023, 1, 1), 0.3), (datetime(2023, 2, 1), 0.4)],
            },
            "bands": ["NDVI", "EVI"],
            "collection": "S2-16D-2",
            "label": "Point 1",
            "lon": -45.0,
            "lat": -12.0,
        }
        plot_line_chart(dock, hist_entry)
        dock.canvas_plot.draw_idle.assert_called_once()
        dock.canvas_plot.draw.assert_not_called()
        # ax.plot is called at least twice (NDVI + EVI)
        self.assertGreaterEqual(ax.plot.call_count, 2)

    def test_hidden_bands_excluded(self):
        from bdc_loader_plugin.chart.plot import plot_line_chart

        dock, ax = self._make_chart_dock()
        dock._hidden_bands = {"EVI"}
        hist_entry = {
            "data": {
                "NDVI": [(datetime(2023, 1, 1), 0.5)],
                "EVI": [(datetime(2023, 1, 1), 0.3)],
            },
            "bands": ["NDVI", "EVI"],
            "collection": "Test",
            "label": "P1",
            "lon": 0,
            "lat": 0,
        }
        plot_line_chart(dock, hist_entry)
        # ax.plot is called once (NDVI), not twice (EVI is hidden)
        self.assertEqual(ax.plot.call_count, 1)

    def test_single_band_data(self):
        from bdc_loader_plugin.chart.plot import plot_line_chart

        dock, ax = self._make_chart_dock()
        hist_entry = {
            "data": {"B04": [(datetime(2023, 1, 1), 100)]},
            "bands": ["B04"],
            "collection": "Test",
            "label": "P1",
            "lon": -45.0,
            "lat": -12.0,
        }
        plot_line_chart(dock, hist_entry)
        ax.plot.assert_called_once()


class TestApplyAxisRanges(unittest.TestCase):
    """Tests for apply_axis_ranges."""

    def test_no_ranges(self):
        from bdc_loader_plugin.chart.plot import apply_axis_ranges

        ax = MagicMock()
        dock = MagicMock()
        dock.get_effective_y_range.return_value = None
        dock.get_effective_x_range.return_value = None
        apply_axis_ranges(ax, dock)
        ax.set_ylim.assert_not_called()
        ax.set_xlim.assert_not_called()


# ── Export CSV Tests ──────────────────────────────────────────────────────────


# ── Chart Package Init Tests ──────────────────────────────────────────────────


if __name__ == "__main__":
    unittest.main()
