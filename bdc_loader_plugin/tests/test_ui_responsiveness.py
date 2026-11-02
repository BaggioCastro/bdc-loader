#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_ui_responsiveness.py — UI freeze detection and responsiveness tests.

Simulates scenarios that could block the main thread / QGIS event loop:
- Signal flood from rapid slider/widget updates
- ThreadPoolExecutor completion loops that block while waiting
- Progress callback frequency during large extractions
- Concurrent extraction + cancel race conditions
- Large result widget population overhead

All tests run without a real event loop — they measure algorithmic overhead
and timing that would cause visible UI freezes (>100ms latency).

Run: python3 -m pytest bdc_loader_plugin/tests/test_ui_responsiveness.py -v
"""

import threading
import time
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

# UI freeze threshold — anything over this blocks QGIS repaint
_UI_FREEZE_THRESHOLD_MS = 100  # milliseconds


def _ms(elapsed):
    return elapsed * 1000


# ═══════════════════════════════════════════════════════════════════════════
# PART 1: Signal flood from rapid widget updates
# ═══════════════════════════════════════════════════════════════════════════


class TestSignalFloodResilience(unittest.TestCase):
    """Rapid signal emissions (slider drag, combo changes) must not queue-block."""

    def test_chart_range_flood_coalesces_without_sync_replots(self):
        """Rapid range movement schedules one bounded refresh instead of full replots."""
        from bdc_loader_plugin.chart.dock import ChartDock

        dock = MagicMock()
        dock._axis_refresh_timer.isActive.side_effect = [False] + [True] * 199
        dock._schedule_axis_refresh = lambda: ChartDock._schedule_axis_refresh(dock)

        for index in range(200):
            ChartDock._on_y_range_changed(dock, float(index), float(index + 100))

        dock._parent_panel._replot_current.assert_not_called()
        dock._axis_refresh_timer.start.assert_called_once()

    def test_rgb_control_flood_defers_replot_until_timer_fires(self):
        """Rapid RGB spin changes update state but never redraw synchronously."""
        from bdc_loader_plugin.chart.dock import ChartDock

        dock = MagicMock()
        dock._schedule_deferred_replot = lambda *_args: ChartDock._schedule_deferred_replot(dock)
        for _ in range(100):
            ChartDock._on_rgb_spin_changed(dock)

        dock._parent_panel._replot_current.assert_not_called()
        self.assertEqual(dock._replot_debounce_timer.start.call_count, 100)

        ChartDock._fire_deferred_replot(dock)
        dock._parent_panel._replot_current.assert_called_once()


class TestChartBackgroundOperations(unittest.TestCase):
    """Network/stat operations started from chart interactions must return immediately."""

    @staticmethod
    def _wait(event):
        if not event.wait(2):
            raise AssertionError("background callback did not finish")

    def test_wtss_health_check_does_not_block_ui_thread(self):
        from bdc_loader_plugin.core.ts_visualization import TSVisualization

        finished = threading.Event()
        panel = TSVisualization.__new__(TSVisualization)
        panel._set_wtss_indicator = lambda *_args: finished.set()

        def slow_status():
            time.sleep(0.2)
            return True, 200.0

        with (
            patch("bdc_loader_plugin.core.ts_visualization.get_wtss_status", side_effect=slow_status),
            patch("bdc_loader_plugin.core.ts_visualization._invoke_on_ui_thread", side_effect=lambda cb: cb()),
        ):
            started = time.perf_counter()
            panel._check_wtss_status()
            returned_ms = _ms(time.perf_counter() - started)
            self._wait(finished)

        self.assertLess(returned_ms, _UI_FREEZE_THRESHOLD_MS)

    def test_rgb_replot_needs_no_network(self):
        """With every band in the entry, the RGB chart is drawn at once, without a request."""
        from bdc_loader_plugin.core.ts_visualization import TSVisualization

        day = datetime(2023, 1, 1)
        entry = {
            "collection": "S2-16D-2",
            "lon": -45.0,
            "lat": -12.0,
            "start": "2023-01-01",
            "end": "2023-12-31",
            "bands": ["red", "green", "blue"],
            "data": {b: [(day, 1000.0)] for b in ("red", "green", "blue")},
        }
        panel = TSVisualization.__new__(TSVisualization)
        panel.chart_dock = MagicMock()
        panel.chart_dock.line_mode_btn.isChecked.return_value = False
        panel.chart_dock.rgb_r_combo.currentData.return_value = "red"
        panel.chart_dock.rgb_g_combo.currentData.return_value = "green"
        panel.chart_dock.rgb_b_combo.currentData.return_value = "blue"
        panel._rgb_bands_downloading = False
        panel._fetch_additional_bands = MagicMock()
        with (
            patch("bdc_loader_plugin.core.ts_visualization.plot_rgb_dots") as plot,
            patch("threading.Thread") as thread,
        ):
            started = time.perf_counter()
            panel._plot_result(entry)
            returned_ms = _ms(time.perf_counter() - started)

        self.assertLess(returned_ms, _UI_FREEZE_THRESHOLD_MS)
        plot.assert_called_once_with(panel.chart_dock, entry)
        thread.assert_not_called()
        panel._fetch_additional_bands.assert_not_called()

    def test_additional_band_fetch_does_not_block_combo_change(self):
        from bdc_loader_plugin.core.ts_bands import TSBandManager

        finished = threading.Event()
        panel = TSBandManager.__new__(TSBandManager)
        panel._cancel_extraction = threading.Event()
        panel._rgb_bands_downloading = False
        panel._replot_current = lambda: finished.set()
        panel._set_status = MagicMock()
        panel._update_rgb_combos = MagicMock()
        panel.chart_dock = MagicMock()
        panel._point_items = MagicMock(return_value=[MagicMock()])
        entry = {
            "collection": "S2-16D-2",
            "lon": -45.0,
            "lat": -12.0,
            "start": "2023-01-01",
            "end": "2023-12-31",
            "bands": [],
            "data": {},
        }

        def slow_extract(*_args, **_kwargs):
            time.sleep(0.2)
            return {0: {"B02": [(datetime(2023, 1, 1), 3000.0)]}}, 0

        with (
            patch("bdc_loader_plugin.core.ts_bands.collection_has_wtss", return_value=False),
            patch("bdc_loader_plugin.core.ts_bands.collection_band_info", return_value={}),
            patch("bdc_loader_plugin.core.ts_bands.extract_points_timeseries", side_effect=slow_extract),
            patch("bdc_loader_plugin.core.ts_bands._invoke_on_ui_thread", side_effect=lambda cb: cb()),
        ):
            started = time.perf_counter()
            panel._fetch_additional_bands(entry, ["B02"])
            returned_ms = _ms(time.perf_counter() - started)
            self._wait(finished)

        self.assertLess(returned_ms, _UI_FREEZE_THRESHOLD_MS)
        self.assertIn("B02", entry["data"])

    def test_chart_date_click_does_not_block_during_item_search(self):
        """A slow STAC lookup started by a chart click must not hold the UI handler."""
        from bdc_loader_plugin.core.ts_visualization import TSVisualization

        finished = threading.Event()
        clicked_date = datetime(2023, 1, 1)
        entry = {
            "collection": "S2-16D-2",
            "lon": -45.0,
            "lat": -12.0,
            "bands": ["B04"],
            "data": {"B04": [(clicked_date, 5000.0)]},
        }
        panel = TSVisualization.__new__(TSVisualization)
        panel._history = [entry]
        panel._current_viz_index = 0
        panel._hist_settings = {"vrt_mode": "single", "vrt_single_band": "B04"}
        panel.chart_dock = MagicMock()
        panel.chart_dock.rgb_mode_btn.isChecked.return_value = False
        panel._get_rgb_for_collection = MagicMock(return_value=None)
        panel._search_items = lambda *_args: (time.sleep(0.2), [])[1]
        panel._set_status = MagicMock(
            side_effect=lambda text, *_args, **_kwargs: finished.set() if text.startswith("No image") else None
        )

        with patch("bdc_loader_plugin.core.ts_visualization._invoke_on_ui_thread", side_effect=lambda cb: cb()):
            started = time.perf_counter()
            panel._on_chart_date_clicked(clicked_date)
            returned_ms = _ms(time.perf_counter() - started)
            self._wait(finished)

        self.assertLess(returned_ms, _UI_FREEZE_THRESHOLD_MS)

    def test_chart_vrt_worker_preserves_rgb_band_order(self):
        """The background builder keeps the selected RGB order and separate-band VRT."""
        from bdc_loader_plugin.core.ts_visualization import TSVisualization

        panel = TSVisualization.__new__(TSVisualization)
        item = MagicMock()
        item.id = "S2_ITEM"
        item.assets = {
            "red": MagicMock(href="https://example/red.tif"),
            "green": MagicMock(href="https://example/green.tif"),
            "blue": MagicMock(href="https://example/blue.tif"),
        }
        panel._search_items = MagicMock(return_value=[item])

        with (
            patch("bdc_loader_plugin.stac.parsers.extract_tile_from_item", return_value="T22/ABC"),
            patch(
                "bdc_loader_plugin.core.ts_visualization.build_vrt_layer_name_candidates",
                return_value=["candidate"],
            ),
            patch("bdc_loader_plugin.core.ts_visualization.build_vrt_layer_name", return_value="rgb-layer"),
            patch("bdc_loader_plugin.core.ts_visualization.os.makedirs"),
            patch("bdc_loader_plugin.core.ts_visualization.gdal.BuildVRTOptions", return_value="options") as opts,
            patch("bdc_loader_plugin.core.ts_visualization.gdal.BuildVRT", return_value=MagicMock()) as build,
        ):
            result = panel._build_chart_vrt_request(
                "S2-16D-2",
                -45.0,
                -12.0,
                "2023-01-01",
                ["red", "green", "blue"],
                set(),
                "/tmp/vrt-test",
                "stac",
            )

        self.assertEqual(result["status"], "built")
        opts.assert_called_once_with(resampleAlg="nearest", separate=True)
        self.assertEqual(
            build.call_args.args[1],
            [
                "/vsicurl/https://example/red.tif",
                "/vsicurl/https://example/green.tif",
                "/vsicurl/https://example/blue.tif",
            ],
        )

    def test_chart_vrt_worker_reports_unavailable_band_without_building(self):
        """An unavailable selection reports the band instead of creating a broken VRT."""
        from bdc_loader_plugin.core.ts_visualization import TSVisualization

        panel = TSVisualization.__new__(TSVisualization)
        item = MagicMock()
        item.id = "S1_ITEM"
        item.assets = {"Gamma0_VV": MagicMock(href="https://example/vv.tif")}
        panel._search_items = MagicMock(return_value=[item])

        with (
            patch("bdc_loader_plugin.stac.parsers.extract_tile_from_item", return_value="T22ABC"),
            patch(
                "bdc_loader_plugin.core.ts_visualization.build_vrt_layer_name_candidates",
                return_value=["candidate"],
            ),
            patch("bdc_loader_plugin.core.ts_visualization.build_vrt_layer_name", return_value="s1-layer"),
            patch("bdc_loader_plugin.core.ts_visualization.gdal.BuildVRT") as build,
        ):
            result = panel._build_chart_vrt_request(
                "S1-RTC",
                -45.0,
                -12.0,
                "2023-01-01",
                ["Gamma0_HH"],
                set(),
                "/tmp/vrt-test",
                "stac",
            )

        self.assertEqual(result, {"status": "missing_band", "band": "Gamma0_HH"})
        build.assert_not_called()

    def test_chart_vrt_completion_prefers_latest_pending_click(self):
        """A completed stale click is not activated when a newer date is pending."""
        from bdc_loader_plugin.core.ts_visualization import TSVisualization

        panel = TSVisualization.__new__(TSVisualization)
        first = datetime(2023, 1, 1)
        latest = datetime(2023, 2, 1)
        panel._chart_vrt_running = True
        panel._chart_vrt_pending = latest
        panel._on_chart_date_clicked = MagicMock()
        panel._set_status = MagicMock()

        panel._finish_chart_vrt_request(first, {"status": "no_items", "date_str": "2023-01-01"})

        panel._on_chart_date_clicked.assert_called_once_with(latest)
        panel._set_status.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════
# PART 2: ThreadPoolExecutor completion loop latency
# ═══════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════
# PART 3: Progress callback frequency
# ═══════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════
# PART 4: Cancel race conditions
# ═══════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════
# PART 5: Large result widget overhead
# ═══════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════
# PART 6: Concurrent extraction operations
# ═══════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════
# PART 7: VRT generation pipeline timing
# ═══════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════
# PART 8: Tile pattern / parser under load
# ═══════════════════════════════════════════════════════════════════════════


class TestParserUnderLoad(unittest.TestCase):
    """STAC parsers remain fast under heavy usage patterns."""

    def test_extract_tile_pattern_1000_items(self):
        """Extracting tile from 1000 items is fast."""
        from bdc_loader_plugin.stac.parsers import extract_tile_from_item

        items = []
        for i in range(1000):
            item = MagicMock()
            item.id = f"S2-16D-2_022024_2023-{(i % 12) + 1:02d}-15"
            item.properties = {}
            items.append(item)

        t0 = time.perf_counter()
        tiles = [extract_tile_from_item(item) for item in items]
        elapsed_ms = _ms(time.perf_counter() - t0)

        self.assertEqual(len(tiles), 1000)
        self.assertLess(elapsed_ms, 200, f"1000 tile extractions: {elapsed_ms:.0f}ms")


if __name__ == "__main__":
    unittest.main()
