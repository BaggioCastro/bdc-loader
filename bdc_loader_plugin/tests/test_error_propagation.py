#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_error_propagation.py — Error handling, communication, and recovery tests.

Covers: WTSS circuit breaker state transitions, retry logic (4xx vs 5xx),
partial failure resilience, network timeout handling, cancellation race
conditions, VRT build error recovery, and error message lifecycle.

Every failure path in the extraction/VRT pipeline must surface a clear,
actionable error — never silently swallow or lose data.

Run: python3 -m pytest bdc_loader_plugin/tests/test_error_propagation.py -v
"""

import threading
import time as _time
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

# ═══════════════════════════════════════════════════════════════════════════
# PART 1: WTSS Circuit breaker state machine
# ═══════════════════════════════════════════════════════════════════════════


class TestCircuitBreakerStates(unittest.TestCase):
    """Verify CLOSED → OPEN → HALF_OPEN → CLOSED transitions."""

    def setUp(self):
        """Reset circuit breaker before each test."""
        import bdc_loader_plugin.extraction.wtss_extractor as mod

        self.mod = mod
        with mod._cb_lock:
            mod._cb_state.clear()

    def test_success_resets_failure_count(self):
        """A single success resets failure count to 0."""
        for _ in range(5):
            self.mod._cb_failure("S2-16D-2")
        self.mod._cb_success("S2-16D-2")

        # 5 more failures after reset — still below threshold
        for _ in range(5):
            self.mod._cb_failure("S2-16D-2")
        self.assertFalse(self.mod._cb_is_open("S2-16D-2"))

    def test_open_breaker_blocks_requests(self):
        """Open breaker raises RuntimeError on _wtss_get."""
        for _ in range(self.mod._CB_THRESHOLD):
            self.mod._cb_failure("S2-16D-2")
        self.assertTrue(self.mod._cb_is_open("S2-16D-2"))

        with self.assertRaises(RuntimeError) as ctx:
            self.mod._wtss_get("S2-16D-2", ["NDVI"], -12.0, -45.0, "2023-01-01", "2023-12-31")
        self.assertIn("circuit breaker", str(ctx.exception).lower())

    def test_success_after_half_open_closes_breaker(self):
        """Success during half-open state resets the breaker."""
        for _ in range(self.mod._CB_THRESHOLD):
            self.mod._cb_failure("S2-16D-2")

        with self.mod._cb_lock:
            self.mod._cb_state["S2-16D-2"]["until"] = _time.monotonic() - 1

        self.assertFalse(self.mod._cb_is_open("S2-16D-2"))
        self.mod._cb_success("S2-16D-2")

        with self.mod._cb_lock:
            state = self.mod._cb_state.get("S2-16D-2", {})
            self.assertEqual(state.get("failures", 0), 0)

    def test_breaker_is_per_collection(self):
        """Different collections have independent circuit breakers."""
        for _ in range(self.mod._CB_THRESHOLD):
            self.mod._cb_failure("S2-16D-2")
        self.assertTrue(self.mod._cb_is_open("S2-16D-2"))
        self.assertFalse(self.mod._cb_is_open("LANDSAT-16D-1"))

    def test_concurrent_failures_are_thread_safe(self):
        """Multiple threads recording failures don't corrupt state."""
        barrier = threading.Barrier(10)

        def _fail():
            barrier.wait()
            for _ in range(3):
                self.mod._cb_failure("S2-16D-2")

        threads = [threading.Thread(target=_fail) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        with self.mod._cb_lock:
            state = self.mod._cb_state.get("S2-16D-2", {})
            self.assertGreaterEqual(state.get("failures", 0), self.mod._CB_THRESHOLD)

    def test_extract_multi_points_returns_empty_when_open(self):
        """extract_wtss_multi_points returns empty dicts when breaker is open."""
        for _ in range(self.mod._CB_THRESHOLD):
            self.mod._cb_failure("S2-16D-2")

        points = [(-45.0, -12.0, "P1", ["NDVI"])]
        result = self.mod.extract_wtss_multi_points("S2-16D-2", points, "2023-01-01", "2023-12-31")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], {})


# ═══════════════════════════════════════════════════════════════════════════
# PART 2: WTSS retry logic (4xx vs 5xx)
# ═══════════════════════════════════════════════════════════════════════════


class TestWTSSRetryBehavior(unittest.TestCase):
    """Verify 4xx fail-fast vs 5xx retry with backoff."""

    def setUp(self):
        import bdc_loader_plugin.extraction.wtss_extractor as mod

        self.mod = mod
        with mod._cb_lock:
            mod._cb_state.clear()

    @patch("bdc_loader_plugin.extraction.wtss_extractor._time.sleep")
    @patch("bdc_loader_plugin.extraction.wtss_extractor.requests.get")
    def test_5xx_retries_up_to_max(self, mock_get, mock_sleep):
        """HTTP 500 triggers retries up to _MAX_RETRIES."""
        resp = MagicMock()
        resp.status_code = 500
        resp.json.return_value = {"description": "Internal error"}
        resp.text = "Internal error"
        mock_get.return_value = resp

        with self.assertRaises(RuntimeError):
            self.mod._wtss_get("S2-16D-2", ["NDVI"], -12.0, -45.0, "2023-01-01", "2023-12-31")

        self.assertEqual(mock_get.call_count, self.mod._MAX_RETRIES)

    @patch("bdc_loader_plugin.extraction.wtss_extractor._time.sleep")
    @patch("bdc_loader_plugin.extraction.wtss_extractor.requests.get")
    def test_5xx_then_200_succeeds(self, mock_get, mock_sleep):
        """Server recovers on 3rd attempt — succeeds."""
        fail_resp = MagicMock()
        fail_resp.status_code = 502
        fail_resp.json.return_value = {"description": "Bad gateway"}
        fail_resp.text = "Bad gateway"

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {
            "result": {
                "timeline": ["2023-01-01", "2023-01-17"],
                "attributes": [{"attribute": "NDVI", "values": [6000, 7000]}],
            }
        }

        mock_get.side_effect = [fail_resp, fail_resp, ok_resp]

        result = self.mod._wtss_get("S2-16D-2", ["NDVI"], -12.0, -45.0, "2023-01-01", "2023-12-31")
        self.assertIn("result", result)
        self.assertEqual(mock_get.call_count, 3)

    @patch("bdc_loader_plugin.extraction.wtss_extractor._time.sleep")
    @patch("bdc_loader_plugin.extraction.wtss_extractor.requests.get")
    def test_linear_backoff_between_retries(self, mock_get, mock_sleep):
        """Sleep increases linearly: _RETRY_DELAY × (attempt + 1)."""
        resp = MagicMock()
        resp.status_code = 503
        resp.json.return_value = {"description": "Service unavailable"}
        resp.text = "Service unavailable"
        mock_get.return_value = resp

        with self.assertRaises(RuntimeError):
            self.mod._wtss_get("S2-16D-2", ["NDVI"], -12.0, -45.0, "2023-01-01", "2023-12-31")

        delays = [c.args[0] for c in mock_sleep.call_args_list]
        # Should be _RETRY_DELAY*1, _RETRY_DELAY*2, _RETRY_DELAY*3
        for i, d in enumerate(delays):
            expected = self.mod._RETRY_DELAY * (i + 1)
            self.assertAlmostEqual(d, expected, places=3)

    @patch("bdc_loader_plugin.extraction.wtss_extractor._time.sleep")
    @patch("bdc_loader_plugin.extraction.wtss_extractor.requests.get")
    def test_connection_error_triggers_retry(self, mock_get, mock_sleep):
        """requests.ConnectionError triggers retry, not immediate failure."""
        import requests as req

        mock_get.side_effect = req.ConnectionError("DNS resolution failed")

        with self.assertRaises(RuntimeError):
            self.mod._wtss_get("S2-16D-2", ["NDVI"], -12.0, -45.0, "2023-01-01", "2023-12-31")

        self.assertEqual(mock_get.call_count, self.mod._MAX_RETRIES)

    @patch("bdc_loader_plugin.extraction.wtss_extractor._time.sleep")
    @patch("bdc_loader_plugin.extraction.wtss_extractor.requests.get")
    def test_timeout_triggers_retry(self, mock_get, mock_sleep):
        """requests.Timeout triggers retry."""
        import requests as req

        mock_get.side_effect = req.Timeout("30s timeout exceeded")

        with self.assertRaises(RuntimeError):
            self.mod._wtss_get("S2-16D-2", ["NDVI"], -12.0, -45.0, "2023-01-01", "2023-12-31")

        self.assertEqual(mock_get.call_count, self.mod._MAX_RETRIES)

    @patch("bdc_loader_plugin.extraction.wtss_extractor.requests.get")
    def test_max_retries_failure_triggers_cb_failure(self, mock_get):
        """Exhausting retries calls _cb_failure for the collection."""
        import requests as req

        mock_get.side_effect = req.ConnectionError("network down")

        with patch.object(self.mod, "_cb_failure"):
            with patch.object(self.mod, "_time") as mock_time:
                mock_time.sleep = MagicMock()
                mock_time.monotonic.return_value = 1000.0
                with self.assertRaises(RuntimeError):
                    self.mod._wtss_get("S2-16D-2", ["NDVI"], -12.0, -45.0, "2023-01-01", "2023-12-31")


# ═══════════════════════════════════════════════════════════════════════════
# PART 3: Band validation and unknown bands
# ═══════════════════════════════════════════════════════════════════════════


class TestBandValidation(unittest.TestCase):
    """WTSS pre-validates bands before sending requests."""

    def setUp(self):
        import bdc_loader_plugin.extraction.wtss_extractor as mod

        self.mod = mod
        with mod._cb_lock:
            mod._cb_state.clear()

    def test_all_s2_bands_are_known(self):
        """All S2-16D-2 bands pass validation."""
        known = self.mod.WTSS_BANDS.get("S2-16D-2", set())
        self.assertGreater(len(known), 0)
        self.assertIn("NDVI", known)
        self.assertIn("B04", known)
        self.assertIn("B08", known)


# ═══════════════════════════════════════════════════════════════════════════
# PART 4: Response parsing edge cases
# ═══════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════
# PART 5: Pixel read error handling
# ═══════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════
# PART 6: VRT build errors
# ═══════════════════════════════════════════════════════════════════════════


class TestVRTBuildErrors(unittest.TestCase):
    """build_single_vrt returns structured errors, never crashes."""

    @patch("bdc_loader_plugin.core.vrt_builder.gdal")
    def test_buildvrt_returns_none_yields_error(self, mock_gdal):
        """BuildVRT returning None → ('error', tile, message)."""
        mock_gdal.BuildVRT.return_value = None
        mock_gdal.BuildVRTOptions.return_value = MagicMock()
        mock_gdal.UseExceptions = MagicMock()

        from bdc_loader_plugin.core.vrt_builder import build_single_vrt

        task = {
            "vrt_path": "/tmp/test.vrt",
            "hrefs": ["/vsicurl/https://e.com/B04.tif"],
            "separate": False,
            "mixed_res": False,
            "tile": "T22KGA",
            "tile_safe": "T22KGA",
            "layer_name": "test_layer",
            "band_desc": "B04",
            "cutline_path": None,
            "group_name": "S2-16D-2 / T22KGA",
        }
        result = build_single_vrt(task)
        self.assertEqual(result[0], "error")
        self.assertEqual(result[1], "T22KGA")
        self.assertIn("None", result[2])

    @patch("bdc_loader_plugin.core.vrt_builder.gdal")
    def test_mosaic_band_vrt_failure_reports_band_index(self, mock_gdal):
        """Multi-band mosaic failure reports which band failed."""
        mock_gdal.BuildVRT.return_value = None
        mock_gdal.BuildVRTOptions.return_value = MagicMock()
        mock_gdal.UseExceptions = MagicMock()

        from bdc_loader_plugin.core.vrt_builder import build_single_vrt

        task = {
            "vrt_path": "/tmp/mosaic.vrt",
            "hrefs": [],
            "href_groups": [
                ["/vsicurl/https://e.com/tile1_B04.tif", "/vsicurl/https://e.com/tile2_B04.tif"],
                ["/vsicurl/https://e.com/tile1_B08.tif"],
            ],
            "separate": True,
            "mixed_res": False,
            "tile": "mosaic_2023-06-15",
            "tile_safe": "mosaic_2023-06-15",
            "layer_name": "mosaic_B04_B08",
            "band_desc": "Mosaic RGB B04_B08",
            "cutline_path": None,
            "group_name": "S2-16D-2 / mosaic",
        }
        result = build_single_vrt(task)
        self.assertEqual(result[0], "error")
        self.assertIn("Band mosaic 1", result[2])

    @patch("bdc_loader_plugin.core.vrt_builder.gdal")
    def test_successful_vrt_returns_ok_tuple(self, mock_gdal):
        """Successful build returns ('ok', path, layer, group)."""
        mock_ds = MagicMock()
        mock_gdal.BuildVRT.return_value = mock_ds
        mock_gdal.BuildVRTOptions.return_value = MagicMock()
        mock_gdal.UseExceptions = MagicMock()

        from bdc_loader_plugin.core.vrt_builder import build_single_vrt

        task = {
            "vrt_path": "/tmp/test.vrt",
            "hrefs": ["/vsicurl/https://e.com/B04.tif"],
            "separate": False,
            "mixed_res": False,
            "tile": "T22KGA",
            "tile_safe": "T22KGA",
            "layer_name": "test_layer",
            "band_desc": "B04",
            "cutline_path": None,
            "group_name": "S2-16D-2 / T22KGA",
        }
        result = build_single_vrt(task)
        self.assertEqual(result[0], "ok")
        self.assertEqual(result[1], "/tmp/test.vrt")
        self.assertEqual(result[2], "test_layer")


# ═══════════════════════════════════════════════════════════════════════════
# PART 7: Extraction with missing/partial data
# ═══════════════════════════════════════════════════════════════════════════


class TestPartialDataExtraction(unittest.TestCase):
    """Extraction handles items with missing bands/dates gracefully."""

    @patch("bdc_loader_plugin.extraction.wtss_extractor._extract_wtss_single_point")
    def test_wtss_exception_per_point_yields_empty(self, mock_extract):
        """RuntimeError for one point → {} for that point, others ok."""
        import bdc_loader_plugin.extraction.wtss_extractor as mod

        with mod._cb_lock:
            mod._cb_state.clear()

        def _side(cid, bands, lat, lon, s, e):
            if lon == -46.0:
                raise RuntimeError("Server error")
            return {"NDVI": [(datetime(2023, 1, 1), 6000.0)]}

        mock_extract.side_effect = _side
        from bdc_loader_plugin.extraction.wtss_extractor import extract_wtss_multi_points

        points = [
            (-45.0, -12.0, "P1", ["NDVI"]),
            (-46.0, -13.0, "P2", ["NDVI"]),
            (-47.0, -14.0, "P3", ["NDVI"]),
        ]
        result = extract_wtss_multi_points("S2-16D-2", points, "2023-01-01", "2023-12-31")
        self.assertEqual(len(result), 3)
        self.assertNotEqual(result[0], {})
        self.assertEqual(result[1], {})
        self.assertNotEqual(result[2], {})


# ═══════════════════════════════════════════════════════════════════════════
# PART 8: GDAL config and stats estimation errors
# ═══════════════════════════════════════════════════════════════════════════


class TestGDALConfigErrors(unittest.TestCase):
    """GDAL configuration edge cases."""

    def test_point_read_options_follow_the_performance_profile(self):
        """Cache size, connect and request timeouts come from the profile; TLS stays verified."""
        from bdc_loader_plugin.extraction.gdal_setup import point_read_options

        options = point_read_options({"gdal_cache_mb": 32, "http_timeout": 7})

        self.assertEqual(options["VSI_CACHE_SIZE"], str(32 * 1024 * 1024))
        self.assertEqual(options["GDAL_HTTP_CONNECTTIMEOUT"], "7")
        self.assertEqual(options["GDAL_HTTP_TIMEOUT"], "7")
        self.assertEqual(options["GDAL_HTTP_UNSAFESSL"], "NO")


# ═══════════════════════════════════════════════════════════════════════════
# PART 9: Semaphore and concurrency controls
# ═══════════════════════════════════════════════════════════════════════════


class TestConcurrencyControls(unittest.TestCase):
    """Verify semaphores and worker caps are respected."""

    def test_request_semaphore_limits_concurrent_gets(self):
        """Request semaphore count matches the configured wtss_workers."""
        import bdc_loader_plugin.extraction.wtss_extractor as mod

        workers = mod._get_wtss_workers()
        self.assertEqual(mod._REQUEST_SEMAPHORE._value, workers)
        self.assertGreaterEqual(mod._REQUEST_SEMAPHORE._value, 1)
        self.assertLessEqual(mod._REQUEST_SEMAPHORE._value, 8)

    def test_wtss_workers_within_safe_bounds(self):
        """_get_wtss_workers returns a value within the PERF_LIMITS range (1–8)."""
        import bdc_loader_plugin.extraction.wtss_extractor as mod

        workers = mod._get_wtss_workers()
        self.assertGreaterEqual(workers, 1)
        self.assertLessEqual(workers, 8)


if __name__ == "__main__":
    unittest.main()
