#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_wtss_extractor.py — Unit tests for extraction/wtss_extractor.py

Covers: collection_has_wtss, WTSS_COVERAGES, _parse_get_response,
extract_wtss_multi_points, _extract_wtss_single_point, cancel flow,
circuit breaker, constants.

Run: python3 -m pytest bdc_loader_plugin/tests/test_wtss_extractor.py -v
"""

import unittest
from datetime import datetime
from unittest.mock import patch


class TestWtssConstants(unittest.TestCase):
    """Test module-level constants and configuration."""

    def test_wtss_base_url(self):
        from bdc_loader_plugin.extraction.wtss_extractor import WTSS_BASE

        self.assertEqual(WTSS_BASE, "https://data.inpe.br/bdc/wtss")

    def test_wtss_v4_url(self):
        from bdc_loader_plugin.extraction.wtss_extractor import WTSS_V4

        self.assertIn("/v4", WTSS_V4)

    def test_default_workers_conservative(self):
        from bdc_loader_plugin.extraction.wtss_extractor import _DEFAULT_WTSS_WORKERS

        self.assertLessEqual(_DEFAULT_WTSS_WORKERS, 5)


class TestCollectionHasWtss(unittest.TestCase):
    """WTSS collection mapping."""

    def test_known_collections(self):
        from bdc_loader_plugin.extraction.wtss_extractor import collection_has_wtss

        self.assertTrue(collection_has_wtss("S2-16D-2"))
        self.assertTrue(collection_has_wtss("LANDSAT-16D-1"))
        self.assertTrue(collection_has_wtss("mod13q1-6.1"))
        self.assertTrue(collection_has_wtss("myd13q1-6.1"))
        self.assertTrue(collection_has_wtss("CBERS4-WFI-16D-2"))

    def test_unknown_collection(self):
        from bdc_loader_plugin.extraction.wtss_extractor import collection_has_wtss

        self.assertFalse(collection_has_wtss("UNKNOWN-COLLECTION"))
        self.assertFalse(collection_has_wtss(""))
        self.assertFalse(collection_has_wtss("S2-16D-3"))

    def test_all_nine_coverages(self):
        from bdc_loader_plugin.extraction.wtss_extractor import WTSS_COVERAGES

        self.assertEqual(len(WTSS_COVERAGES), 9)
        expected = {
            "S2-16D-2",
            "LANDSAT-16D-1",
            "CBERS4-MUX-2M-1",
            "CBERS4-WFI-16D-2",
            "CBERS-WFI-8D-1",
            "mod13q1-6.1",
            "myd13q1-6.1",
            "mod11a2-6.1",
            "myd11a2-6.1",
        }
        self.assertEqual(WTSS_COVERAGES, expected)


class TestExtractWtssSinglePoint(unittest.TestCase):
    """Test single-point WTSS extraction via HTTP GET."""

    @patch("bdc_loader_plugin.extraction.wtss_extractor._wtss_get")
    def test_basic_extraction(self, mock_get):
        from bdc_loader_plugin.extraction.wtss_extractor import _extract_wtss_single_point

        mock_get.return_value = {
            "result": {
                "timeline": ["2020-01-01", "2020-02-01", "2020-03-01"],
                "attributes": [
                    {"attribute": "NDVI", "values": [5000, 7000, 8000]},
                    {"attribute": "EVI", "values": [3000, 4000, -9999]},
                ],
            }
        }

        result = _extract_wtss_single_point("S2-16D-2", ["NDVI", "EVI"], -12.0, -45.0, "2020-01-01", "2020-03-31")

        self.assertIn("NDVI", result)
        self.assertIn("EVI", result)
        self.assertEqual(len(result["NDVI"]), 3)
        self.assertEqual(len(result["EVI"]), 2)  # -9999 filtered out
        self.assertEqual(result["NDVI"][0][1], 5000.0)
        self.assertIsInstance(result["NDVI"][0][0], datetime)

    @patch("bdc_loader_plugin.extraction.wtss_extractor._wtss_get")
    def test_all_nodata_filtered(self, mock_get):
        from bdc_loader_plugin.extraction.wtss_extractor import _extract_wtss_single_point

        mock_get.return_value = {
            "result": {"timeline": ["2020-01-01"], "attributes": [{"attribute": "NDVI", "values": [-9999]}]}
        }

        result = _extract_wtss_single_point("S2-16D-2", ["NDVI"], -12.0, -45.0, "2020-01-01", "2020-12-31")
        self.assertNotIn("NDVI", result)  # All filtered out

    @patch("bdc_loader_plugin.extraction.wtss_extractor._wtss_get")
    def test_sorted_output(self, mock_get):
        from bdc_loader_plugin.extraction.wtss_extractor import _extract_wtss_single_point

        mock_get.return_value = {
            "result": {
                "timeline": ["2020-03-01", "2020-01-01", "2020-02-01"],
                "attributes": [{"attribute": "NDVI", "values": [8000, 5000, 7000]}],
            }
        }

        result = _extract_wtss_single_point("S2-16D-2", ["NDVI"], -12.0, -45.0, "2020-01-01", "2020-12-31")
        dates = [d for d, v in result["NDVI"]]
        self.assertEqual(dates, sorted(dates))


class TestExtractWtssMultiPoints(unittest.TestCase):
    """Parallel extraction of several points."""

    @patch("bdc_loader_plugin.extraction.wtss_extractor._extract_wtss_single_point")
    def test_multi_points(self, mock_extract):
        from bdc_loader_plugin.extraction.wtss_extractor import extract_wtss_multi_points

        mock_extract.return_value = {"NDVI": [(datetime(2020, 1, 1), 0.5), (datetime(2020, 2, 1), 0.7)]}

        points = [
            (-45.0, -12.0, "P1", ["NDVI"]),
            (-46.0, -13.0, "P2", ["NDVI"]),
        ]

        results = extract_wtss_multi_points("S2-16D-2", points, "2020-01-01", "2020-12-31")

        self.assertEqual(len(results), 2)
        self.assertIn(0, results)
        self.assertIn(1, results)
        self.assertIn("NDVI", results[0])
        self.assertEqual(mock_extract.call_count, 2)

    @patch("bdc_loader_plugin.extraction.wtss_extractor._extract_wtss_single_point")
    def test_empty_points(self, mock_extract):
        from bdc_loader_plugin.extraction.wtss_extractor import extract_wtss_multi_points

        results = extract_wtss_multi_points("S2-16D-2", [], "2020-01-01", "2020-12-31")
        self.assertEqual(results, {})
        mock_extract.assert_not_called()

    @patch("bdc_loader_plugin.extraction.wtss_extractor._extract_wtss_single_point")
    def test_cancel_flag(self, mock_extract):
        from bdc_loader_plugin.extraction.wtss_extractor import extract_wtss_multi_points

        mock_extract.return_value = {"NDVI": [(datetime(2020, 1, 1), 0.5)]}

        points = [(-45.0, -12.0, f"P{i}", ["NDVI"]) for i in range(10)]
        results = extract_wtss_multi_points(
            "S2-16D-2",
            points,
            "2020-01-01",
            "2020-12-31",
            cancel_flag=lambda: True,
        )
        self.assertEqual(results, {})
        mock_extract.assert_not_called()

    def test_cancel_drops_the_points_still_queued(self):
        import threading
        import time

        from bdc_loader_plugin.extraction import wtss_extractor

        cancel = threading.Event()
        requested = []

        def _point(*args):
            requested.append(args)
            time.sleep(0.2)
            cancel.set()
            return {}

        points = [(-45.0, -12.0, f"P{i}", ["NDVI"]) for i in range(30)]
        with (
            patch.object(wtss_extractor, "_extract_wtss_single_point", side_effect=_point),
            patch.object(wtss_extractor, "_cb_is_open", return_value=False),
            patch.object(wtss_extractor, "_get_wtss_workers", return_value=3),
        ):
            wtss_extractor.extract_wtss_multi_points("S2-16D-2", points, "2020-01-01", "2020-12-31", cancel.is_set)

        self.assertLess(len(requested), 10)

    @patch("bdc_loader_plugin.extraction.wtss_extractor._extract_wtss_single_point")
    def test_progress_callback(self, mock_extract):
        from bdc_loader_plugin.extraction.wtss_extractor import extract_wtss_multi_points

        mock_extract.return_value = {"NDVI": [(datetime(2020, 1, 1), 0.5)]}
        callback_calls = []

        def cb(pt_idx, label, data):
            callback_calls.append((pt_idx, label))

        points = [(-45.0, -12.0, "P1", ["NDVI"]), (-46.0, -13.0, "P2", ["NDVI"])]
        extract_wtss_multi_points(
            "S2-16D-2",
            points,
            "2020-01-01",
            "2020-12-31",
            progress_callback=cb,
        )
        self.assertEqual(len(callback_calls), 2)

    @patch("bdc_loader_plugin.extraction.wtss_extractor._extract_wtss_single_point")
    def test_error_handling(self, mock_extract):
        from bdc_loader_plugin.extraction.wtss_extractor import extract_wtss_multi_points

        mock_extract.side_effect = Exception("Server error")

        points = [(-45.0, -12.0, "P1", ["NDVI"])]
        results = extract_wtss_multi_points("S2-16D-2", points, "2020-01-01", "2020-12-31")
        self.assertEqual(results[0], {})  # Empty dict on error


if __name__ == "__main__":
    unittest.main()
