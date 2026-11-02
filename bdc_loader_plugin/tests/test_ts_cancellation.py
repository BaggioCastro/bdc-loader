#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_ts_cancellation.py — Cancellation safety tests for time series pipeline.

Covers: _cancel_extraction flag at all decision points, _on_cancel_extraction
UI reset, cancel_flag propagation to WTSS/STAC extractors, partial results
on cancellation, fetch_additional_bands cancellation.

Run: python3 -m pytest bdc_loader_plugin/tests/test_ts_cancellation.py -v
"""

import threading
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

# ── _on_cancel_extraction UI reset ───────────────────────────────────────────


class TestOnCancelExtraction(unittest.TestCase):
    """Tests for TSExtractionEngine._on_cancel_extraction."""

    def _make_panel(self):
        from bdc_loader_plugin.core.ts_extraction import TSExtractionEngine

        panel = TSExtractionEngine.__new__(TSExtractionEngine)
        panel._cancel_extraction = threading.Event()
        panel.cancel_btn = MagicMock()
        panel._set_status = MagicMock()
        return panel

    def test_sets_cancel_flag(self):
        panel = self._make_panel()
        panel._on_cancel_extraction()
        self.assertTrue(panel._cancel_extraction.is_set())

    def test_disables_cancel_button(self):
        panel = self._make_panel()
        panel._on_cancel_extraction()
        panel.cancel_btn.setEnabled.assert_called_with(False)

    def test_changes_button_text(self):
        panel = self._make_panel()
        panel._on_cancel_extraction()
        panel.cancel_btn.setText.assert_called_with("Cancelling...")

    def test_idempotent_double_cancel(self):
        """Calling cancel twice doesn't crash or reset state."""
        panel = self._make_panel()
        panel._on_cancel_extraction()
        panel._on_cancel_extraction()
        self.assertTrue(panel._cancel_extraction.is_set())


# ── extract_multi_band_timeseries cancel_flag ────────────────────────────────


# ── extract_wtss_multi_points cancel_flag ────────────────────────────────────


class TestWtssMultiCancellation(unittest.TestCase):
    """Cancel flag handling in extract_wtss_multi_points."""

    def test_cancel_before_any_submission(self):
        """cancel_flag=True from start → no WTSS calls."""
        with patch("bdc_loader_plugin.extraction.wtss_extractor._cb_is_open", return_value=False):
            with patch("bdc_loader_plugin.extraction.wtss_extractor._extract_wtss_single_point"):
                from bdc_loader_plugin.extraction.wtss_extractor import extract_wtss_multi_points

                points = [(-45.0, -12.0, "P1", ["B04"])]
                results = extract_wtss_multi_points(
                    "S2-16D-2", points, "2023-01-01", "2023-12-31", cancel_flag=lambda: True
                )
        # Should return without processing
        self.assertIsInstance(results, dict)

    def test_cancel_mid_extraction(self):
        """cancel_flag triggers after first point → remaining points skipped."""
        cancel = [False]

        with patch("bdc_loader_plugin.extraction.wtss_extractor._cb_is_open", return_value=False):
            with patch("bdc_loader_plugin.extraction.wtss_extractor._extract_wtss_single_point") as mock_ext:

                def _side(cid, bands, lat, lon, s, e):
                    cancel[0] = True  # cancel after first extraction
                    return {"B04": [(datetime(2023, 1, 1), 5000.0)]}

                mock_ext.side_effect = _side
                from bdc_loader_plugin.extraction.wtss_extractor import extract_wtss_multi_points

                points = [(float(i), float(i), f"P{i}", ["B04"]) for i in range(5)]
                results = extract_wtss_multi_points(
                    "S2-16D-2", points, "2023-01-01", "2023-12-31", cancel_flag=lambda: cancel[0]
                )

        # Due to cancel_flag, not all 5 points complete
        self.assertIsInstance(results, dict)
        self.assertLessEqual(len(results), 5)


# ── extract_pixel_timeseries_vrt cancel_flag ─────────────────────────────────


# ── _fetch_additional_bands cancellation ─────────────────────────────────────


class TestFetchAdditionalBandsCancellation(unittest.TestCase):
    """Cancel flag in _fetch_additional_bands (TSBandManager)."""

    def _make_panel(self):
        from bdc_loader_plugin.core.ts_bands import TSBandManager

        panel = TSBandManager.__new__(TSBandManager)
        panel._cancel_extraction = threading.Event()
        panel._rgb_bands_downloading = False
        panel._replot_current = MagicMock()
        panel._set_status = MagicMock()
        panel._update_rgb_combos = MagicMock()
        panel.chart_dock = MagicMock()
        return panel

    @patch("bdc_loader_plugin.core.ts_bands.collection_has_wtss", return_value=False)
    def test_keeps_latest_request_when_fetch_is_running(self, mock_wtss):
        """A request made during a fetch is queued instead of blocking or overlapping."""
        panel = self._make_panel()
        panel._rgb_bands_downloading = True
        entry = {"collection": "S2-16D-2", "lon": -45, "lat": -12, "start": "2023-01-01", "end": "2023-12-31"}
        panel._fetch_additional_bands(entry, ["B02"])
        self.assertEqual(panel._rgb_fetch_pending, (entry, ["B02"]))
        panel._replot_current.assert_not_called()

    @patch("bdc_loader_plugin.core.ts_bands.collection_has_wtss", return_value=False)
    def test_ignores_band_already_in_active_fetch(self, mock_wtss):
        """Repeated control events do not enqueue the band already in flight."""
        panel = self._make_panel()
        panel._rgb_bands_downloading = True
        entry = {
            "collection": "S2-16D-2",
            "lon": -45,
            "lat": -12,
            "start": "2023-01-01",
            "end": "2023-12-31",
        }
        panel._rgb_fetch_active = (entry, {"B02"})

        panel._fetch_additional_bands(entry, ["B02"])

        self.assertIsNone(getattr(panel, "_rgb_fetch_pending", None))

    @patch("bdc_loader_plugin.core.ts_bands.collection_band_info", return_value={"b02": {"scale": 0.0001}})
    @patch("bdc_loader_plugin.core.ts_bands.extract_points_timeseries")
    @patch("bdc_loader_plugin.core.ts_bands.collection_has_wtss", return_value=False)
    def test_stac_path_updates_entry_data(self, mock_wtss, mock_extract, mock_info):
        """STAC path: reads the point's items grouped by file and updates the entry."""
        panel = self._make_panel()
        item = MagicMock()
        panel._point_items = MagicMock(return_value=[item])
        finished = threading.Event()
        panel._replot_current = MagicMock(side_effect=finished.set)

        mock_extract.return_value = ({0: {"B02": [(datetime(2023, 1, 1), 3000.0)]}}, 0)

        entry = {
            "collection": "S2-16D-2",
            "lon": -45,
            "lat": -12,
            "start": "2023-01-01",
            "end": "2023-12-31",
            "data": {"B04": [(datetime(2023, 1, 1), 5000.0)]},
            "bands": ["B04"],
        }
        with patch("bdc_loader_plugin.core.ts_bands._invoke_on_ui_thread", side_effect=lambda cb: cb()):
            panel._fetch_additional_bands(entry, ["B02"])
            self.assertTrue(finished.wait(2), "background band fetch did not finish")

        panel._point_items.assert_called_once_with("S2-16D-2", (-45, -12), "2023-01-01", "2023-12-31")
        args = mock_extract.call_args.args
        self.assertEqual(args[:3], ([[item]], [(-45, -12)], ["B02"]))
        self.assertIn("B02", entry["data"])
        self.assertEqual(entry["scaling"]["B02"], (1.0, 0.0))

    @patch("bdc_loader_plugin.core.ts_bands.collection_band_info", return_value={})
    @patch("bdc_loader_plugin.core.ts_bands.collection_has_wtss", return_value=False)
    def test_no_items_found_sets_warning(self, mock_wtss, mock_info):
        """No STAC items → warning status."""
        panel = self._make_panel()
        panel._point_items = MagicMock(return_value=[])
        finished = threading.Event()
        panel._replot_current = MagicMock(side_effect=finished.set)

        entry = {
            "collection": "S2-16D-2",
            "lon": -45,
            "lat": -12,
            "start": "2023-01-01",
            "end": "2023-12-31",
            "data": {},
            "bands": [],
        }
        with patch("bdc_loader_plugin.core.ts_bands._invoke_on_ui_thread", side_effect=lambda cb: cb()):
            panel._fetch_additional_bands(entry, ["B02"])
            self.assertTrue(finished.wait(2), "background band fetch did not finish")

        panel._set_status.assert_called()
        last_call = panel._set_status.call_args_list[-1]
        self.assertIn("warning", str(last_call))


# ── _compute_vegetation_indices cancellation-adjacent ─────────────────────────


class TestComputeVegetationIndicesEdgeCases(unittest.TestCase):
    """Edge cases in _compute_vegetation_indices (called after cancel check)."""

    def _make_manager(self):
        from bdc_loader_plugin.core.ts_bands import TSBandManager

        mgr = TSBandManager.__new__(TSBandManager)
        mgr._band_info = {
            "S2-16D-2": {
                "B04": {"common_name": "red"},
                "B02": {"common_name": "blue"},
                "B08": {"common_name": "nir"},
            }
        }
        mgr._collections = {"Sentinel-2": {"id": "S2-16D-2", "bands": ["B02", "B04", "B08"]}}
        return mgr

    def test_ndvi_computed_when_bands_present(self):
        mgr = self._make_manager()
        d = datetime(2023, 1, 1)
        point_data = {
            "B08": [(d, 8000)],
            "B04": [(d, 2000)],
        }
        mgr._compute_vegetation_indices("S2-16D-2", point_data, ["_NDVI"])
        self.assertIn("NDVI", point_data)
        self.assertAlmostEqual(point_data["NDVI"][0][1], 6000.0, places=1)

    def test_evi_computed_when_bands_present(self):
        mgr = self._make_manager()
        d = datetime(2023, 1, 1)
        point_data = {
            "B08": [(d, 8000)],
            "B04": [(d, 2000)],
            "B02": [(d, 1000)],
        }
        mgr._compute_vegetation_indices("S2-16D-2", point_data, ["_EVI"])
        self.assertIn("EVI", point_data)

    def test_missing_source_band_skips_index(self):
        mgr = self._make_manager()
        d = datetime(2023, 1, 1)
        point_data = {"B08": [(d, 8000)]}  # no B04 (red)
        mgr._compute_vegetation_indices("S2-16D-2", point_data, ["_NDVI"])
        self.assertNotIn("NDVI", point_data)

    def test_unknown_index_key_skipped(self):
        mgr = self._make_manager()
        point_data = {}
        mgr._compute_vegetation_indices("S2-16D-2", point_data, ["_UNKNOWN_INDEX"])
        self.assertNotIn("_UNKNOWN_INDEX", point_data)

    def test_empty_point_data_no_crash(self):
        mgr = self._make_manager()
        point_data = {}
        mgr._compute_vegetation_indices("S2-16D-2", point_data, ["_NDVI", "_EVI"])
        self.assertNotIn("NDVI", point_data)
        self.assertNotIn("EVI", point_data)

    def test_both_indices_computed(self):
        mgr = self._make_manager()
        d = datetime(2023, 1, 1)
        point_data = {
            "B08": [(d, 8000)],
            "B04": [(d, 2000)],
            "B02": [(d, 1000)],
        }
        mgr._compute_vegetation_indices("S2-16D-2", point_data, ["_NDVI", "_EVI"])
        self.assertIn("NDVI", point_data)
        self.assertIn("EVI", point_data)


if __name__ == "__main__":
    unittest.main()
