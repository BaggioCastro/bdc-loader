#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_wtss_coverage.py — Extended tests for extraction/wtss_extractor.py

Covers: _parse_get_response, _wtss_get, circuit breaker (_cb_success,
_cb_failure, _cb_is_open), get_wtss_status — pure logic and network mocks.

Run: python3 -m pytest bdc_loader_plugin/tests/test_wtss_coverage.py -v
"""

import time
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch


class TestParseGetResponse(unittest.TestCase):
    """Tests for _parse_get_response — pure dict parsing, no mocking."""

    def test_normal_response(self):
        from bdc_loader_plugin.extraction.wtss_extractor import _parse_get_response

        data = {
            "result": {
                "timeline": ["2023-01-01", "2023-01-17", "2023-02-02"],
                "attributes": [
                    {"attribute": "NDVI", "values": [6258, 7100, 5500]},
                    {"attribute": "EVI", "values": [4000, 4500, 3800]},
                ],
            }
        }
        result = _parse_get_response(data, ["NDVI", "EVI"])
        self.assertIn("NDVI", result)
        self.assertIn("EVI", result)
        self.assertEqual(len(result["NDVI"]), 3)
        self.assertEqual(result["NDVI"][0][1], 6258.0)
        self.assertIsInstance(result["NDVI"][0][0], datetime)

    def test_sorted_by_date(self):
        from bdc_loader_plugin.extraction.wtss_extractor import _parse_get_response

        data = {
            "result": {
                "timeline": ["2023-03-01", "2023-01-01", "2023-02-01"],
                "attributes": [
                    {"attribute": "NDVI", "values": [8000, 6000, 7000]},
                ],
            }
        }
        result = _parse_get_response(data, ["NDVI"])
        dates = [d for d, v in result["NDVI"]]
        self.assertEqual(dates, sorted(dates))

    def test_nodata_filtered(self):
        from bdc_loader_plugin.extraction.wtss_extractor import _parse_get_response

        data = {
            "result": {
                "timeline": ["2023-01-01", "2023-02-01"],
                "attributes": [
                    {"attribute": "NDVI", "values": [6000, -9999]},
                ],
            }
        }
        result = _parse_get_response(data, ["NDVI"])
        self.assertEqual(len(result["NDVI"]), 1)
        self.assertEqual(result["NDVI"][0][1], 6000.0)

    def test_none_values_filtered(self):
        from bdc_loader_plugin.extraction.wtss_extractor import _parse_get_response

        data = {
            "result": {
                "timeline": ["2023-01-01", "2023-02-01"],
                "attributes": [
                    {"attribute": "NDVI", "values": [5000, None]},
                ],
            }
        }
        result = _parse_get_response(data, ["NDVI"])
        self.assertEqual(len(result["NDVI"]), 1)

    def test_empty_timeline(self):
        from bdc_loader_plugin.extraction.wtss_extractor import _parse_get_response

        data = {"result": {"timeline": [], "attributes": []}}
        result = _parse_get_response(data, ["NDVI"])
        self.assertEqual(result, {})

    def test_missing_result_block(self):
        from bdc_loader_plugin.extraction.wtss_extractor import _parse_get_response

        result = _parse_get_response({}, ["NDVI"])
        self.assertEqual(result, {})

    def test_band_not_in_response(self):
        from bdc_loader_plugin.extraction.wtss_extractor import _parse_get_response

        data = {
            "result": {
                "timeline": ["2023-01-01"],
                "attributes": [
                    {"attribute": "EVI", "values": [4000]},
                ],
            }
        }
        result = _parse_get_response(data, ["NDVI"])
        self.assertNotIn("NDVI", result)

    def test_invalid_date_skipped(self):
        from bdc_loader_plugin.extraction.wtss_extractor import _parse_get_response

        data = {
            "result": {
                "timeline": ["bad_date", "2023-01-01"],
                "attributes": [
                    {"attribute": "NDVI", "values": [5000, 6000]},
                ],
            }
        }
        result = _parse_get_response(data, ["NDVI"])
        self.assertEqual(len(result["NDVI"]), 1)
        self.assertEqual(result["NDVI"][0][1], 6000.0)

    def test_all_nodata_returns_empty(self):
        from bdc_loader_plugin.extraction.wtss_extractor import _parse_get_response

        data = {
            "result": {
                "timeline": ["2023-01-01"],
                "attributes": [
                    {"attribute": "NDVI", "values": [-9999]},
                ],
            }
        }
        result = _parse_get_response(data, ["NDVI"])
        self.assertNotIn("NDVI", result)


class TestCircuitBreaker(unittest.TestCase):
    """Tests for circuit breaker functions."""

    def setUp(self):
        import bdc_loader_plugin.extraction.wtss_extractor as mod

        self.mod = mod
        # Reset circuit breaker state
        with mod._cb_lock:
            mod._cb_state.clear()

    def test_cb_success_resets(self):
        cid = "TEST-COL-1"
        self.mod._cb_state[cid] = {"failures": 3, "until": 0.0}
        self.mod._cb_success(cid)
        self.assertEqual(self.mod._cb_state[cid]["failures"], 0)

    def test_cb_success_noop_unknown(self):
        self.mod._cb_success("UNKNOWN")
        self.assertNotIn("UNKNOWN", self.mod._cb_state)

    def test_cb_failure_increments(self):
        cid = "TEST-COL-1"
        self.mod._cb_failure(cid)
        self.assertEqual(self.mod._cb_state[cid]["failures"], 1)
        self.mod._cb_failure(cid)
        self.assertEqual(self.mod._cb_state[cid]["failures"], 2)

    def test_cb_opens_after_threshold(self):
        cid = "TEST-COL-1"
        for _ in range(self.mod._CB_THRESHOLD):
            self.mod._cb_failure(cid)
        # Should be open now
        self.assertTrue(self.mod._cb_is_open(cid))

    def test_cb_not_open_below_threshold(self):
        cid = "TEST-COL-1"
        for _ in range(self.mod._CB_THRESHOLD - 1):
            self.mod._cb_failure(cid)
        self.assertFalse(self.mod._cb_is_open(cid))

    def test_cb_closes_after_cooldown(self):
        cid = "TEST-COL-1"
        for _ in range(self.mod._CB_THRESHOLD):
            self.mod._cb_failure(cid)
        self.assertTrue(self.mod._cb_is_open(cid))

        # Simulate time passing beyond cooldown
        with self.mod._cb_lock:
            self.mod._cb_state[cid]["until"] = time.monotonic() - 1
        self.assertFalse(self.mod._cb_is_open(cid))

    def test_cb_is_open_unknown_collection(self):
        self.assertFalse(self.mod._cb_is_open("UNKNOWN"))


class TestGetWtssStatus(unittest.TestCase):
    """Tests for get_wtss_status network check."""

    @patch("bdc_loader_plugin.extraction.wtss_extractor.requests.get")
    def test_online(self, mock_get):
        from bdc_loader_plugin.extraction.wtss_extractor import get_wtss_status

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp
        online, ms = get_wtss_status()
        self.assertTrue(online)
        self.assertGreater(ms, 0)

    @patch("bdc_loader_plugin.extraction.wtss_extractor.requests.get")
    def test_server_error(self, mock_get):
        from bdc_loader_plugin.extraction.wtss_extractor import get_wtss_status

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_get.return_value = mock_resp
        online, ms = get_wtss_status()
        self.assertFalse(online)

    @patch("bdc_loader_plugin.extraction.wtss_extractor.requests.get")
    def test_connection_error(self, mock_get):
        import requests

        from bdc_loader_plugin.extraction.wtss_extractor import get_wtss_status

        mock_get.side_effect = requests.ConnectionError("unreachable")
        online, ms = get_wtss_status()
        self.assertFalse(online)
        self.assertEqual(ms, 0.0)


class TestWtssGet(unittest.TestCase):
    """Tests for _wtss_get with mocked network."""

    def setUp(self):
        import bdc_loader_plugin.extraction.wtss_extractor as mod

        with mod._cb_lock:
            mod._cb_state.clear()

    @patch("bdc_loader_plugin.extraction.wtss_extractor.requests.get")
    def test_success(self, mock_get):
        from bdc_loader_plugin.extraction.wtss_extractor import _wtss_get

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"result": {"timeline": ["2023-01-01"]}}
        mock_get.return_value = mock_resp
        result = _wtss_get("S2-16D-2", ["NDVI"], -12.0, -45.0, "2023-01-01", "2023-12-31")
        self.assertIn("result", result)

    @patch("bdc_loader_plugin.extraction.wtss_extractor.requests.get")
    def test_4xx_raises(self, mock_get):
        from bdc_loader_plugin.extraction.wtss_extractor import _wtss_get

        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {"description": "bad param"}
        mock_get.return_value = mock_resp
        with self.assertRaises(RuntimeError):
            _wtss_get("S2-16D-2", ["NDVI"], -12.0, -45.0, "2023-01-01", "2023-12-31")

    @patch("bdc_loader_plugin.extraction.wtss_extractor.requests.get")
    def test_invalid_bands_raises(self, mock_get):
        from bdc_loader_plugin.extraction.wtss_extractor import _wtss_get

        # Requesting bands not known for the collection
        with self.assertRaises(RuntimeError):
            _wtss_get("S2-16D-2", ["FAKE_BAND"], -12.0, -45.0, "2023-01-01", "2023-12-31")

    def test_circuit_breaker_open_raises(self):
        import bdc_loader_plugin.extraction.wtss_extractor as mod
        from bdc_loader_plugin.extraction.wtss_extractor import _wtss_get

        # Force circuit breaker open
        with mod._cb_lock:
            mod._cb_state["S2-16D-2"] = {"failures": 10, "until": time.monotonic() + 999}
        with self.assertRaises(RuntimeError):
            _wtss_get("S2-16D-2", ["NDVI"], -12.0, -45.0, "2023-01-01", "2023-12-31")


class TestWtssBands(unittest.TestCase):
    """Tests for WTSS_BANDS completeness."""

    def test_all_coverages_have_bands(self):
        from bdc_loader_plugin.extraction.wtss_extractor import WTSS_BANDS, WTSS_COVERAGES

        for cov in WTSS_COVERAGES:
            self.assertIn(cov, WTSS_BANDS, f"Missing bands for {cov}")
            self.assertGreater(len(WTSS_BANDS[cov]), 0, f"Empty bands for {cov}")

    def test_s2_has_ndvi(self):
        from bdc_loader_plugin.extraction.wtss_extractor import WTSS_BANDS

        self.assertIn("NDVI", WTSS_BANDS["S2-16D-2"])

    def test_landsat_has_ndvi(self):
        from bdc_loader_plugin.extraction.wtss_extractor import WTSS_BANDS

        self.assertIn("NDVI", WTSS_BANDS["LANDSAT-16D-1"])


if __name__ == "__main__":
    unittest.main()
