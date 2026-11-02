#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_ts_stability.py — Download stability and data integrity tests.

Covers: WTSS→STAC fallback, extract_time_series entry creation, history merge,
_load_collections_from_plugin fallback, circuit breaker integration,
_fetch_additional_bands WTSS/STAC paths, data integrity on partial failures.

Run: python3 -m pytest bdc_loader_plugin/tests/test_ts_stability.py -v
"""

import unittest
from unittest.mock import MagicMock, patch

# ── Circuit breaker integration ──────────────────────────────────────────────


class TestCircuitBreakerIntegration(unittest.TestCase):
    """Circuit breaker protecting WTSS from cascading failures."""

    def setUp(self):
        import bdc_loader_plugin.extraction.wtss_extractor as mod

        self._mod = mod
        self._orig_state = dict(mod._cb_state)
        mod._cb_state.clear()

    def tearDown(self):
        self._mod._cb_state.clear()
        self._mod._cb_state.update(self._orig_state)

    def test_cb_resets_on_success(self):
        for _ in range(3):
            self._mod._cb_failure("TEST-COL")
        self._mod._cb_success("TEST-COL")
        self.assertEqual(self._mod._cb_state["TEST-COL"]["failures"], 0)


# ── WTSS → STAC fallback stability ──────────────────────────────────────────


class TestWtssToStacFallback(unittest.TestCase):
    """Verify WTSS→STAC fallback works correctly for missing bands."""

    def test_wtss_server_error_returns_empty(self):
        """RuntimeError from WTSS → {} for that point."""
        with patch("bdc_loader_plugin.extraction.wtss_extractor._cb_is_open", return_value=False):
            with patch("bdc_loader_plugin.extraction.wtss_extractor._extract_wtss_single_point") as mock_ext:
                mock_ext.side_effect = RuntimeError("WTSS 503")
                from bdc_loader_plugin.extraction.wtss_extractor import extract_wtss_multi_points

                points = [(-45.0, -12.0, "P1", ["B04"])]
                results = extract_wtss_multi_points("S2-16D-2", points, "2023-01-01", "2023-12-31")

        self.assertEqual(results[0], {})


# ── _parse_get_response stability ────────────────────────────────────────────


# ── _load_collections_from_plugin fallback ───────────────────────────────────


class TestLoadCollectionsFallback(unittest.TestCase):
    """_load_collections_from_plugin fallback to offline collections."""

    def _make_manager(self):
        from bdc_loader_plugin.core.ts_collections import TSCollectionManager

        mgr = TSCollectionManager.__new__(TSCollectionManager)
        mgr._collections = {}
        mgr._band_info = {}
        mgr._visible_ids = set()
        mgr._stac_client = None
        mgr._set_status = MagicMock()
        mgr.ts_collection_combo = MagicMock()
        mgr.ts_collection_combo.currentIndex.return_value = -1
        mgr.ts_collection_combo.count.return_value = 0
        return mgr

    @patch("bdc_loader_plugin.stac.client.requests.get")
    @patch("bdc_loader_plugin.core.ts_collections.QCoreApplication.processEvents")
    def test_http_success_populates_collections(self, mock_events, mock_get):
        """Successful HTTP GET populates _collections."""
        mgr = self._make_manager()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "collections": [
                {
                    "id": "S2-16D-2",
                    "title": "Sentinel-2 (COG)",
                    "bdc:type": "cube",
                    "item_assets": {"B04": {"type": "image/tiff; application=geotiff; profile=cloud-optimized"}},
                    "extent": {"temporal": {"interval": [["2017-01-01", "2024-01-01"]]}},
                    "summaries": {"eo:bands": [{"name": "B04", "common_name": "red"}]},
                    "bdc:grs": "BDC_SM_V2",
                }
            ]
        }

        # Need to handle the ThreadPoolExecutor that wraps requests.get
        mock_get.return_value = mock_resp

        mgr._populate_collection_combo = MagicMock()
        mgr._load_collections_from_plugin()

        self.assertGreater(len(mgr._collections), 0)
        # Must hit the /collections endpoint, not the STAC
        # root landing page (root has no "collections" key -> silent empty catalog).
        requested_url = mock_get.call_args[0][0]
        self.assertTrue(requested_url.rstrip("/").endswith("collections"), requested_url)

    @patch("bdc_loader_plugin.stac.client.requests.get")
    @patch("bdc_loader_plugin.core.ts_collections.QCoreApplication.processEvents")
    def test_cog_product_families_populate_collections(self, mock_events, mock_get):
        """Sentinel-1/3 and Charter COGs use the normal collection path; mosaics
        are dropped since they have no regular temporal axis for WTSS."""
        mgr = self._make_manager()
        ids = ["mosaic-s2-brazil-3m-1", "sentinel-1-rtc-1", "s3-olci-rrs-water-1", "charter-wfi-1"]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "collections": [
                {
                    "id": collection_id,
                    "title": collection_id,
                    "bdc:type": "mosaic" if collection_id.startswith("mosaic-") else "collection",
                    "item_assets": {"visual": {"type": "image/tiff; application=geotiff; profile=cloud-optimized"}},
                    "extent": {"temporal": {"interval": [["2024-01-01", "2024-12-31"]]}},
                }
                for collection_id in ids
            ]
        }
        mock_get.return_value = mock_resp
        mgr._populate_collection_combo = MagicMock()

        mgr._load_collections_from_plugin()

        loaded_ids = {config["id"] for config in mgr._collections.values()}
        self.assertEqual(loaded_ids, set(ids) - {"mosaic-s2-brazil-3m-1"})

    @patch("bdc_loader_plugin.stac.client.requests.get")
    @patch("bdc_loader_plugin.core.ts_collections.QCoreApplication.processEvents")
    def test_http_failure_uses_fallback(self, mock_events, mock_get):
        """HTTP error → fallback to FALLBACK_COLLECTIONS."""
        mgr = self._make_manager()
        mock_get.side_effect = ConnectionError("Network unreachable")
        mgr._populate_collection_combo = MagicMock()

        mgr._load_collections_from_plugin()

        self._assert_fallback_loaded(mgr)

    @patch("bdc_loader_plugin.stac.client.requests.get")
    @patch("bdc_loader_plugin.core.ts_collections.QCoreApplication.processEvents")
    def test_a_server_without_image_collections_uses_fallback(self, mock_events, mock_get):
        mgr = self._make_manager()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"collections": [], "links": []}
        mock_get.return_value = mock_resp
        mgr._populate_collection_combo = MagicMock()

        mgr._load_collections_from_plugin()

        self._assert_fallback_loaded(mgr)

    def _assert_fallback_loaded(self, mgr):
        from bdc_loader_plugin.stac.fallback import FALLBACK_COLLECTIONS

        self.assertEqual(set(mgr._collections), set(FALLBACK_COLLECTIONS))
        self.assertGreater(len(mgr._collections), 0)
        last_status = mgr._set_status.call_args[0]
        self.assertIn("(offline)", last_status[0])
        self.assertEqual(last_status[1], "warning")


# ── _find_existing_entry & merge stability ───────────────────────────────────


class TestHistoryMergeStability(unittest.TestCase):
    """Verify existing entries are merged, not duplicated."""

    def _make_engine(self, history):
        from bdc_loader_plugin.core.ts_extraction import TSExtractionEngine

        eng = TSExtractionEngine.__new__(TSExtractionEngine)
        eng._history = history
        return eng

    def test_find_with_near_coords(self):
        """Floating-point tolerance for coordinate matching."""
        entry = {
            "lon": -45.123456,
            "lat": -12.654321,
            "collection": "S2-16D-2",
            "start": "2023-01-01",
            "end": "2023-12-31",
        }
        eng = self._make_engine([entry])
        # Within 1e-6
        found = eng._find_existing_entry(-45.1234565, -12.6543215, "S2-16D-2", "2023-01-01", "2023-12-31")
        self.assertIs(found, entry)
        # Outside 1e-6
        not_found = eng._find_existing_entry(-45.1235, -12.6543, "S2-16D-2", "2023-01-01", "2023-12-31")
        self.assertIsNone(not_found)

    def test_different_date_range_not_merged(self):
        """Different start/end dates → separate entry."""
        entry = {
            "lon": -45.0,
            "lat": -12.0,
            "collection": "S2-16D-2",
            "start": "2023-01-01",
            "end": "2023-06-30",
        }
        eng = self._make_engine([entry])
        found = eng._find_existing_entry(-45.0, -12.0, "S2-16D-2", "2023-01-01", "2023-12-31")
        self.assertIsNone(found)


# ── _read_single_pixel stability ─────────────────────────────────────────────


# ── estimate_band_stats stability ────────────────────────────────────────────


# ── estimate_rgb_stats stability ─────────────────────────────────────────────


# ── WTSS workers config ─────────────────────────────────────────────────────


if __name__ == "__main__":
    unittest.main()
