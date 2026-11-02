#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_large_inputs.py — Behaviour with many tiles, many points and compiled patterns.

All I/O is mocked.

Run: python3 -m pytest bdc_loader_plugin/tests/test_large_inputs.py -v
"""

import os
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch


class TestGiantMosaicVRT(unittest.TestCase):
    """VRT task construction for large mosaics."""

    def _make_mosaic_task(self, n_tiles, n_bands=3):
        """Create a VRT task dict simulating n_tiles per band."""
        import tempfile

        base_dir = tempfile.gettempdir()
        href_groups = []
        for b_idx in range(n_bands):
            band_hrefs = [f"/vsicurl/https://data.inpe.br/cog/tile_{t}_B{b_idx:02d}.tif" for t in range(n_tiles)]
            href_groups.append(band_hrefs)

        return {
            "vrt_path": os.path.join(base_dir, "test_mosaic.vrt"),
            "hrefs": [],
            "href_groups": href_groups,
            "separate": True,
            "mixed_res": False,
            "tile": "mosaic_2023-06-15",
            "tile_safe": "mosaic_2023-06-15",
            "layer_name": "test_mosaic_B04_B08_NDVI",
            "band_desc": "Mosaic RGB B04_B08_NDVI",
            "cutline_path": None,
            "group_name": "S2-16D-2 / mosaic",
        }

    @patch("bdc_loader_plugin.core.vrt_builder.gdal")
    def test_build_single_vrt_with_many_sources(self, mock_gdal):
        """build_single_vrt handles a task with 200 sources per band."""
        mock_gdal.BuildVRT.return_value = MagicMock()
        mock_gdal.BuildVRTOptions.return_value = MagicMock()

        from bdc_loader_plugin.core.vrt_builder import build_single_vrt

        result = build_single_vrt(self._make_mosaic_task(200, n_bands=3))

        self.assertEqual(result[0], "ok")


class TestWTSSManyPoints(unittest.TestCase):
    """WTSS extraction with many points."""

    def setUp(self):
        import bdc_loader_plugin.extraction.wtss_extractor as wtss_mod

        with wtss_mod._cb_lock:
            wtss_mod._cb_state.clear()

    @patch("bdc_loader_plugin.extraction.wtss_extractor._extract_wtss_single_point")
    def test_cancel_during_large_extraction(self, mock_extract):
        """Cancel flag interrupts a 100-point extraction midway."""
        call_count = [0]
        cancel = [False]

        def _extract(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] >= 10:
                cancel[0] = True
            return {"NDVI": [(datetime(2023, 1, 1), 5000.0)]}

        mock_extract.side_effect = _extract
        from bdc_loader_plugin.extraction.wtss_extractor import extract_wtss_multi_points

        points_bands = [(float(-45 + i * 0.01), float(-12 + i * 0.01), f"P{i}", ["NDVI"]) for i in range(100)]
        results = extract_wtss_multi_points(
            "S2-16D-2", points_bands, "2023-01-01", "2023-12-31", cancel_flag=lambda: cancel[0]
        )
        self.assertLess(len(results), 100)


class TestParserPatterns(unittest.TestCase):
    def test_all_patterns_compiled(self):
        """Every pattern is precompiled (not a raw string)."""
        import re

        from bdc_loader_plugin.stac.parsers import (
            MGRS_PATTERN,
            ROW_PATH_PATTERN,
            STG_PATTERN,
            TILE_PATTERN,
            WRS2_PATTERN,
        )

        for name, pattern in [
            ("TILE", TILE_PATTERN),
            ("MGRS", MGRS_PATTERN),
            ("WRS2", WRS2_PATTERN),
            ("STG", STG_PATTERN),
            ("ROW_PATH", ROW_PATH_PATTERN),
        ]:
            self.assertIsInstance(pattern, re.Pattern, f"{name} should be a precompiled regex Pattern")


if __name__ == "__main__":
    unittest.main()
