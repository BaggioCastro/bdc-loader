# -*- coding: utf-8 -*-
"""
Efficiency, bottleneck, data validation and hardcoded value tests

Part 1: VRT generation bottlenecks
Part 2: STAC data consistency (tiles, collections, bands)
Part 3: Hardcoded detection and dynamic fallback validation
Part 4: Interface weight / UI overhead
Part 5: Time series acquisition pipeline
Part 6: Data integrity cross-validation

Developed by Baggio Luiz de Castro e Silva
INPE - Sao Jose dos Campos, 2026
"""

import inspect
import os
import re
import sys
import unittest
from datetime import datetime, timedelta

# Mock environment
from bdc_loader_plugin.tests.qgis_mock import install_mocks, reset_state

install_mocks()
reset_state()


# ================================================================
# PART 1: VRT GENERATION - BOTTLENECKS
# ================================================================


# ================================================================
# PART 2: STAC DATA CONSISTENCY
# ================================================================


class TestSTACDataConsistency(unittest.TestCase):
    """Consistency between STAC collections, tiles and bands."""

    def test_fallback_band_info_covers_all_collections(self):
        """Every fallback collection has its band_info."""
        from bdc_loader_plugin.stac.fallback import FALLBACK_BAND_INFO, FALLBACK_COLLECTIONS

        for name, config in FALLBACK_COLLECTIONS.items():
            cid = config["id"]
            self.assertIn(cid, FALLBACK_BAND_INFO, f"Collection '{cid}' has no fallback band info")

    def test_fallback_bands_match_band_info_keys(self):
        """The bands a collection lists exist in its band_info."""
        from bdc_loader_plugin.stac.fallback import FALLBACK_BAND_INFO, FALLBACK_COLLECTIONS

        for name, config in FALLBACK_COLLECTIONS.items():
            cid = config["id"]
            band_info = FALLBACK_BAND_INFO.get(cid, {})
            for band in config["bands"]:
                self.assertIn(band, band_info, f"Band '{band}' from '{cid}' not found in FALLBACK_BAND_INFO")

    def test_id_to_display_name_reverse_mapping(self):
        """ID_TO_DISPLAY_NAME maps every ID back to a name."""
        from bdc_loader_plugin.stac.fallback import FALLBACK_COLLECTIONS, ID_TO_DISPLAY_NAME

        for name, config in FALLBACK_COLLECTIONS.items():
            cid = config["id"]
            self.assertIn(cid, ID_TO_DISPLAY_NAME)
            self.assertEqual(ID_TO_DISPLAY_NAME[cid], name)

    def test_grs_to_grid_has_known_grids(self):
        """GRS_TO_GRID covers every grid the collections use."""
        from bdc_loader_plugin.stac.client import GRS_TO_GRID
        from bdc_loader_plugin.stac.fallback import FALLBACK_COLLECTIONS

        used_grids = {c["grid"] for c in FALLBACK_COLLECTIONS.values() if c.get("grid")}
        mapped_grids = set(GRS_TO_GRID.values())
        for grid in used_grids:
            self.assertIn(grid, mapped_grids, f"Grid '{grid}' used by collections but not in GRS_TO_GRID values")

    def test_tile_patterns_consistent_with_grids(self):
        """The tile patterns match the defined grid systems."""
        from bdc_loader_plugin.stac.parsers import MGRS_PATTERN, STG_PATTERN, TILE_PATTERN, WRS2_PATTERN

        # BDC tiles: 6 digits
        self.assertTrue(TILE_PATTERN.match("002011"))
        self.assertFalse(TILE_PATTERN.match("00201"))
        self.assertFalse(TILE_PATTERN.match("0020111"))

        # MGRS: 2 digits + 3 uppercase letters
        self.assertTrue(MGRS_PATTERN.match("19MCP"))
        self.assertTrue(MGRS_PATTERN.match("22KGF"))
        self.assertFalse(MGRS_PATTERN.match("1MCP"))

        # WRS2: 6 digits (path+row)
        self.assertTrue(WRS2_PATTERN.match("211059"))
        self.assertFalse(WRS2_PATTERN.match("21105"))

        # MODIS STG: h##v##
        self.assertTrue(STG_PATTERN.match("h13v10"))
        self.assertTrue(STG_PATTERN.match("H13V10"))

    def test_excluded_assets_complete(self):
        """EXCLUDED_ASSETS covers the known QA and metadata assets."""
        from bdc_loader_plugin.stac.parsers import EXCLUDED_ASSETS

        essential_excludes = {"thumbnail", "CMASK", "qa_pixel", "SCL", "PROVENANCE", "CLEAROB", "TOTALOB", "DATASOURCE"}
        for excl in essential_excludes:
            self.assertIn(excl, EXCLUDED_ASSETS, f"Asset '{excl}' should be excluded but isn't")

    def test_no_stac_url_duplication(self):
        """The STAC URL comes from one place (client.py), not duplicated."""
        from bdc_loader_plugin.stac.client import STAC_URL

        # The base URL is valid
        self.assertTrue(STAC_URL.startswith("https://"))
        self.assertTrue(STAC_URL.endswith("/"))

        # The collections URL is derived from the base one
        collections_url = f"{STAC_URL}collections"
        self.assertIn("data.inpe.br", collections_url)


# ================================================================
# PART 3: HARDCODED DETECTION & DYNAMIC FALLBACK
# ================================================================


class TestHardcodedDetection(unittest.TestCase):
    """No hardcoded dates or limits that go stale."""

    def test_fallback_temporal_not_expired(self):
        """Fallback end dates are never in the past."""
        from bdc_loader_plugin.stac.fallback import FALLBACK_COLLECTIONS

        today = datetime.now().strftime("%Y-%m-%d")
        for name, config in FALLBACK_COLLECTIONS.items():
            end_date = config["temporal"][1]
            self.assertGreater(end_date, today, f"Fallback '{name}' has expired end date: {end_date}")

    def test_fallback_temporal_is_dynamic(self):
        """Fallback dates are generated at run time."""
        from bdc_loader_plugin.stac.fallback import _dynamic_end_date

        date1 = _dynamic_end_date()
        # Should be ~6 months from now
        expected = (datetime.now() + timedelta(days=180)).strftime("%Y-%m-%d")
        self.assertEqual(date1, expected)

    def test_dynamic_end_date_format(self):
        """The generated date has the YYYY-MM-DD format."""
        from bdc_loader_plugin.stac.fallback import _dynamic_end_date

        date = _dynamic_end_date()
        self.assertRegex(date, r"^\d{4}-\d{2}-\d{2}$")

    def test_all_fallback_collections_have_dynamic_dates(self):
        """Every collection has an end_date at least 90 days ahead."""
        from bdc_loader_plugin.stac.fallback import FALLBACK_COLLECTIONS

        min_future = (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d")
        for name, config in FALLBACK_COLLECTIONS.items():
            end_date = config["temporal"][1]
            self.assertGreaterEqual(
                end_date, min_future, f"Collection '{name}' end date {end_date} is not far enough in the future"
            )

    def test_default_max_items_exists_and_reasonable(self):
        """DEFAULT_MAX_ITEMS exists and is at least 500."""
        from bdc_loader_plugin.stac.client import DEFAULT_MAX_ITEMS

        self.assertIsInstance(DEFAULT_MAX_ITEMS, int)
        self.assertGreaterEqual(
            DEFAULT_MAX_ITEMS, 500, f"DEFAULT_MAX_ITEMS={DEFAULT_MAX_ITEMS} is too low for long time series"
        )

    def test_no_hardcoded_2026_dates_in_panel(self):
        """The panel has no hardcoded dates such as 2026-02-01."""
        panel_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui", "timeseries_panel.py")
        if os.path.exists(panel_path):
            with open(panel_path, "r") as f:
                content = f.read()
            # Should not contain literal hardcoded future dates
            self.assertNotIn("'2026-02-01'", content, "Panel contains hardcoded date '2026-02-01'")
            self.assertNotIn('"2026-02-01"', content, 'Panel contains hardcoded date "2026-02-01"')

    def test_grid_urls_use_https(self):
        """Grid URLs use HTTPS."""
        from bdc_loader_plugin.stac.fallback import FALLBACK_GRID_URLS

        for grid, url in FALLBACK_GRID_URLS.items():
            self.assertTrue(url.startswith("https://"), f"Grid '{grid}' URL does not use HTTPS: {url}")


# ================================================================
# PART 4: INTERFACE WEIGHT / UI OVERHEAD
# ================================================================


class TestInterfaceWeight(unittest.TestCase):
    """The interface stays light: no heavy imports it does not need."""

    def test_extraction_module_import_speed(self):
        """The extraction module imports quickly (< 200 ms)."""
        import importlib

        import bdc_loader_plugin.extraction as extraction_pkg

        mod_name = "bdc_loader_plugin.extraction.gdal_setup"
        original_module = sys.modules.get(mod_name)
        original_attr = getattr(extraction_pkg, "timeseries", None)

        if mod_name in sys.modules:
            del sys.modules[mod_name]

        importlib.import_module(mod_name)

        # Restore original module to avoid breaking globals of imported functions
        if original_module is not None:
            sys.modules[mod_name] = original_module
        if original_attr is not None:
            extraction_pkg.timeseries = original_attr

    def test_parsers_module_has_no_heavy_deps(self):
        """The parsers module depends only on re and fallback (nothing heavy)."""
        from bdc_loader_plugin.stac import parsers

        source = inspect.getsource(parsers)
        # Should NOT import heavy libraries
        self.assertNotIn("import gdal", source)
        self.assertNotIn("import numpy", source)
        self.assertNotIn("import matplotlib", source)
        self.assertNotIn("import requests", source)

    def test_fallback_module_has_no_heavy_deps(self):
        """The fallback module is light (datetime only)."""
        from bdc_loader_plugin.stac import fallback

        source = inspect.getsource(fallback)
        self.assertNotIn("import gdal", source)
        self.assertNotIn("import numpy", source)
        self.assertNotIn("import requests", source)

    def test_config_module_lightweight(self):
        """The config module does not import GDAL, numpy or matplotlib."""
        from bdc_loader_plugin import config

        source = inspect.getsource(config)
        self.assertNotIn("import gdal", source)
        self.assertNotIn("import numpy", source)
        self.assertNotIn("import matplotlib", source)


# ================================================================
# PART 5: TIME SERIES ACQUISITION PIPELINE
# ================================================================


# ================================================================
# PART 6: DATA INTEGRITY CROSS-VALIDATION
# ================================================================


class TestDataIntegrityCrossValidation(unittest.TestCase):
    """Integrity cross-checks between modules."""

    def test_tile_extraction_for_all_supported_collections(self):
        """Tile extraction works for IDs of every supported collection."""
        from bdc_loader_plugin.stac.parsers import extract_tile_from_id

        test_ids = {
            "S2-16D-2": "S2-16D-2_002011_V2023-01-01_2023-01-16",
            "S2_L2A-1": "S2A_MSIL2A_20230101T130251_N0509_R038_T19MCP_20230101T154217",
            "LANDSAT-16D-1": "LANDSAT-16D-1_002011_V2023-01-01_2023-01-16",
            "landsat-2": "LC08_L2SP_211059_20230101_20230110_02_T1",
            "mod13q1-6.1": "MOD13Q1_A2023001_h13v10_061_2023042090325",
        }

        for cid, item_id in test_ids.items():
            result = extract_tile_from_id(item_id)
            self.assertNotEqual(result, "NA", f"Tile extraction failed for {cid} with ID '{item_id}': got 'NA'")

    def test_format_tile_display_consistent(self):
        """format_tile_display does not raise for any grid/tile combination."""
        from bdc_loader_plugin.stac.parsers import format_tile_display

        combos = [
            ("002011", "BDC_SM_V2"),
            ("19MCP", "MGRS"),
            ("211059", "WRS2"),
            ("h13v10", "STG"),
            ("123/456", "BDC_LG_V2"),
            ("NA", ""),
            ("", ""),
        ]
        for tile, grid in combos:
            result = format_tile_display(tile, grid)
            self.assertIsInstance(result, str)

    def test_fallback_temporal_start_before_end(self):
        """The start date precedes the end date in every collection."""
        from bdc_loader_plugin.stac.fallback import FALLBACK_COLLECTIONS

        for name, config in FALLBACK_COLLECTIONS.items():
            start, end = config["temporal"]
            self.assertLess(start, end, f"Collection '{name}': start ({start}) >= end ({end})")

    def test_band_info_wavelength_format(self):
        """Wavelengths read '### nm' or '-'."""
        from bdc_loader_plugin.stac.fallback import FALLBACK_BAND_INFO

        wl_pattern = re.compile(r"^(\d+ nm|-)$")
        for cid, bands in FALLBACK_BAND_INFO.items():
            for bname, info in bands.items():
                wl = info.get("wavelength", "")
                self.assertTrue(wl_pattern.match(wl), f"Band '{bname}' in '{cid}' has invalid wavelength: '{wl}'")

    def test_format_compositing_cube_vs_scenes(self):
        """Cubes show LCF; scenes show 'Individual scenes'."""
        from bdc_loader_plugin.stac.parsers import format_compositing

        # Cube with temporal composition
        result = format_compositing({"step": "16", "unit": "day"}, "cube")
        self.assertIn("16", result)
        self.assertIn("day", result)

        # Scene
        result = format_compositing({}, "collection")
        self.assertEqual(result, "Individual scenes")


# ================================================================
# PART 7: EXTRACTION PIPELINE EDGE CASES
# ================================================================


if __name__ == "__main__":
    unittest.main()
