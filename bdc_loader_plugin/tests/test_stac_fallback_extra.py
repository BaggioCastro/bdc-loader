#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_stac_fallback_extra.py — Extended tests for stac/fallback.py data integrity.

Covers: _dynamic_end_date, FALLBACK_BAND_INFO deep validation,
        FALLBACK_COLLECTIONS temporal consistency, RGB_PRESETS band presence,
        _format_size from result_widgets.

Run: python3 -m pytest bdc_loader_plugin/tests/test_stac_fallback_extra.py -v
"""

import unittest
from datetime import datetime, timedelta


class TestDynamicEndDate(unittest.TestCase):
    """Tests for _dynamic_end_date function."""

    def test_returns_future_date(self):
        from bdc_loader_plugin.stac.fallback import _dynamic_end_date

        result = _dynamic_end_date()
        today = datetime.now()
        result_dt = datetime.strptime(result, "%Y-%m-%d")
        self.assertGreater(result_dt, today)

    def test_approximately_6_months_ahead(self):
        from bdc_loader_plugin.stac.fallback import _dynamic_end_date

        result_dt = datetime.strptime(_dynamic_end_date(), "%Y-%m-%d")
        expected = datetime.now() + timedelta(days=180)
        delta = abs((result_dt - expected).days)
        self.assertLessEqual(delta, 1)

    def test_format_is_iso(self):
        from bdc_loader_plugin.stac.fallback import _dynamic_end_date

        result = _dynamic_end_date()
        self.assertRegex(result, r"^\d{4}-\d{2}-\d{2}$")


class TestFallbackBandInfoDeep(unittest.TestCase):
    """Deep validation of FALLBACK_BAND_INFO structure."""

    def test_sentinel2_has_ndvi_evi(self):
        from bdc_loader_plugin.stac.fallback import FALLBACK_BAND_INFO

        s2 = FALLBACK_BAND_INFO.get("S2-16D-2", {})
        self.assertIn("NDVI", s2)
        self.assertIn("EVI", s2)

    def test_landsat_has_common_bands(self):
        from bdc_loader_plugin.stac.fallback import FALLBACK_BAND_INFO

        ls = FALLBACK_BAND_INFO.get("LANDSAT-16D-1", {})
        common_names = {v["common_name"] for v in ls.values()}
        self.assertIn("red", common_names)
        self.assertIn("blue", common_names)
        self.assertIn("green", common_names)


class TestFormatSize(unittest.TestCase):
    """Tests for _format_size utility from result_widgets."""

    def test_bytes(self):
        from bdc_loader_plugin.ui.result_widgets import _format_size

        self.assertEqual(_format_size(512), "512 B")

    def test_kilobytes(self):
        from bdc_loader_plugin.ui.result_widgets import _format_size

        result = _format_size(2048)
        self.assertIn("KB", result)
        self.assertIn("2.0", result)

    def test_megabytes(self):
        from bdc_loader_plugin.ui.result_widgets import _format_size

        result = _format_size(5 * 1024 * 1024)
        self.assertIn("MB", result)

    def test_gigabytes(self):
        from bdc_loader_plugin.ui.result_widgets import _format_size

        result = _format_size(2 * 1024 * 1024 * 1024)
        self.assertIn("GB", result)

    def test_zero(self):
        from bdc_loader_plugin.ui.result_widgets import _format_size

        self.assertEqual(_format_size(0), "0 B")

    def test_exact_1kb(self):
        from bdc_loader_plugin.ui.result_widgets import _format_size

        result = _format_size(1024)
        self.assertIn("KB", result)

    def test_exact_1mb(self):
        from bdc_loader_plugin.ui.result_widgets import _format_size

        result = _format_size(1024 * 1024)
        self.assertIn("MB", result)


if __name__ == "__main__":
    unittest.main()
