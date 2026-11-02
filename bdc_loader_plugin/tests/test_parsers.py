#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_parsers.py — tests for stac/parsers.py

Covers: edge cases, exceptions, invalid types, every pattern,
every parsing function with extreme inputs.

Run: python3 -m pytest bdc_loader_plugin/tests/test_parsers.py -v
"""

import unittest
from unittest.mock import MagicMock


class TestHasValidTileSystemEdgeCases(unittest.TestCase):
    """Exhaustive tests for has_valid_tile_system."""

    def setUp(self):
        from bdc_loader_plugin.stac.parsers import has_valid_tile_system

        self.func = has_valid_tile_system

    def test_all_known_valid(self):
        valid = ["MGRS", "WRS2", "BDC_SM_V2", "BDC_MD_V2", "BDC_LG_V2", "STG", "CBERS4_MUX_GRID", "AMAZONIA1_WFI_GRID"]
        for grs in valid:
            self.assertTrue(self.func(grs), f"{grs} should be valid")

    def test_none_input(self):
        self.assertFalse(self.func(None))

    def test_empty_string(self):
        self.assertFalse(self.func(""))

    def test_unknown_grids(self):
        for g in ["UNKNOWN", "xyz", "wrs2", "mgrs", "bdc_sm_v2", "BDC"]:
            self.assertFalse(self.func(g), f"{g} should be invalid (case sensitive)")

    def test_whitespace(self):
        self.assertFalse(self.func(" MGRS"))
        self.assertFalse(self.func("MGRS "))

    def test_numeric_input(self):
        # Returns False instead of raising
        self.assertFalse(self.func(0))
        self.assertFalse(self.func(123))

    def test_boolean_input(self):
        self.assertFalse(self.func(True))
        self.assertFalse(self.func(False))


class TestBuildDisplayNameEdgeCases(unittest.TestCase):
    """Exhaustive tests for build_display_name."""

    def setUp(self):
        from bdc_loader_plugin.stac.parsers import build_display_name

        self.func = build_display_name

    def test_all_known_ids_from_fallback(self):
        from bdc_loader_plugin.stac.fallback import ID_TO_DISPLAY_NAME

        for cid, expected_name in ID_TO_DISPLAY_NAME.items():
            result = self.func(cid, "Anything", "any_type")
            self.assertEqual(result, expected_name)

    def test_unknown_cube(self):
        result = self.func("new-cube-1", "New Cube Title", "cube")
        self.assertIn("Cube", result)

    def test_unknown_collection(self):
        result = self.func("new-col-1", "New Collection", "collection")
        self.assertIn("Scenes", result)

    def test_unknown_mosaic(self):
        result = self.func("mos-1", "Mosaic Title", "mosaic")
        self.assertIn("Mosaic", result)

    def test_unknown_classification(self):
        result = self.func("cls-1", "Classification", "classification")
        self.assertIn("Classification", result)

    def test_unknown_type_fallback(self):
        result = self.func("unk-1", "Title", "custom_type")
        self.assertIn("Custom_Type", result)

    def test_empty_type(self):
        result = self.func("unk-1", "Title", "")
        self.assertIn("Data", result)

    def test_none_type(self):
        result = self.func("unk-1", "Title", None)
        self.assertIn("Data", result)

    def test_title_with_dash(self):
        result = self.func("x-1", "Main Title - Extra Info", "cube")
        self.assertIn("Main Title", result)
        self.assertNotIn("Extra Info", result)

    def test_none_title(self):
        result = self.func("x-1", None, "cube")
        self.assertIn("x-1", result)

    def test_empty_title(self):
        result = self.func("x-1", "", "cube")
        self.assertIn("x-1", result)

    def test_id_always_in_output_for_unknowns(self):
        result = self.func("my-unique-id", "T", "cube")
        self.assertIn("my-unique-id", result)


class TestFormatPlatformEdgeCases(unittest.TestCase):
    """Exhaustive tests for format_platform."""

    def setUp(self):
        from bdc_loader_plugin.stac.parsers import format_platform

        self.func = format_platform

    def test_none(self):
        self.assertEqual(self.func(None), "Unknown")

    def test_empty_string(self):
        self.assertEqual(self.func(""), "Unknown")

    def test_empty_list(self):
        self.assertEqual(self.func([]), "Unknown")

    def test_single_string(self):
        self.assertEqual(self.func("sentinel-2"), "Sentinel-2")

    def test_string_uppercase(self):
        self.assertEqual(self.func("LANDSAT"), "Landsat")

    def test_landsat_range(self):
        result = self.func(["landsat-5", "landsat-7", "landsat-8", "landsat-9"])
        self.assertEqual(result, "Landsat 5-9")

    def test_landsat_single(self):
        result = self.func(["landsat-8"])
        self.assertEqual(result, "Landsat 8-8")

    def test_sentinel_variants(self):
        result = self.func(["sentinel-2a", "sentinel-2b"])
        self.assertIn("Sentinel", result)
        self.assertIn("2A", result)
        self.assertIn("2B", result)

    def test_cbers_platforms(self):
        result = self.func(["cbers-4", "cbers-4a"])
        self.assertIn("CBERS", result)

    def test_mixed_platforms(self):
        result = self.func(["platform-a", "platform-b"])
        self.assertIn("Platform-A", result)

    def test_dict_with_code(self):
        result = self.func({"code": ["Terra", "Aqua"]})
        self.assertIn("Terra", result)
        self.assertIn("Aqua", result)

    def test_dict_empty_code(self):
        result = self.func({"code": []})
        self.assertEqual(result, "Unknown")

    def test_dict_no_code(self):
        result = self.func({"other": "value"})
        self.assertEqual(result, "Unknown")

    def test_numeric_input(self):
        result = self.func(42)
        self.assertEqual(result, "42")

    def test_list_with_non_string(self):
        result = self.func([123, 456])
        self.assertIsInstance(result, str)


class TestFormatCompositingEdgeCases(unittest.TestCase):
    """Exhaustive tests for format_compositing."""

    def setUp(self):
        from bdc_loader_plugin.stac.parsers import format_compositing

        self.func = format_compositing

    def test_collection_type_ignores_temporal(self):
        result = self.func({"step": "16", "unit": "day"}, "collection")
        self.assertEqual(result, "Individual scenes")

    def test_cube_with_step_day(self):
        self.assertEqual(self.func({"step": "16", "unit": "day"}, "cube"), "LCF 16 days")

    def test_cube_with_step_month(self):
        self.assertEqual(self.func({"step": "2", "unit": "month"}, "cube"), "LCF 2 months")

    def test_cube_with_step_year(self):
        self.assertEqual(self.func({"step": "1", "unit": "year"}, "cube"), "LCF 1 years")

    def test_cube_unknown_unit(self):
        result = self.func({"step": "8", "unit": "dekad"}, "cube")
        self.assertEqual(result, "LCF 8 dekad")

    def test_none_temporal(self):
        self.assertEqual(self.func(None, "cube"), "Individual scenes")

    def test_empty_dict(self):
        # {} is falsy in Python, so format_compositing treats it like None
        self.assertEqual(self.func({}, "cube"), "Individual scenes")

    def test_missing_step(self):
        result = self.func({"unit": "day"}, "cube")
        self.assertEqual(result, "Temporal composition")

    def test_missing_unit(self):
        result = self.func({"step": "16"}, "cube")
        self.assertEqual(result, "Temporal composition")


class TestExtractBandsFromAssetsEdgeCases(unittest.TestCase):
    """Exhaustive tests for extract_bands_from_assets."""

    def setUp(self):
        from bdc_loader_plugin.stac.parsers import extract_bands_from_assets

        self.func = extract_bands_from_assets

    def test_none_input(self):
        self.assertEqual(self.func(None), [])

    def test_empty_dict(self):
        self.assertEqual(self.func({}), [])

    def test_only_excluded_assets(self):
        from bdc_loader_plugin.stac.parsers import EXCLUDED_ASSETS

        assets = {name: {"type": "image/tiff; application=geotiff"} for name in list(EXCLUDED_ASSETS)[:5]}
        self.assertEqual(self.func(assets), [])

    def test_xml_assets_excluded(self):
        assets = {
            "B01": {"type": "image/tiff; application=geotiff"},
            "meta_xml": {"type": "image/tiff; application=geotiff"},
            "info.xml": {"type": "image/tiff; application=geotiff"},
        }
        result = self.func(assets)
        self.assertIn("B01", result)
        self.assertNotIn("meta_xml", result)
        self.assertNotIn("info.xml", result)

    def test_non_tiff_excluded(self):
        assets = {
            "B01": {"type": "image/tiff; application=geotiff"},
            "thumb": {"type": "image/png"},
            "doc": {"type": "application/json"},
        }
        result = self.func(assets)
        self.assertEqual(result, ["B01"])

    def test_application_geotiff_variant(self):
        assets = {
            "B01": {"type": "application/geotiff"},
        }
        result = self.func(assets)
        self.assertEqual(result, ["B01"])

    def test_sorted_output(self):
        assets = {
            "B12": {"type": "image/tiff"},
            "B02": {"type": "image/tiff"},
            "B08": {"type": "image/tiff"},
        }
        result = self.func(assets)
        self.assertEqual(result, ["B02", "B08", "B12"])

    def test_empty_type_field(self):
        assets = {"B01": {"type": ""}}
        self.assertEqual(self.func(assets), [])

    def test_missing_type_field(self):
        assets = {"B01": {"resolution": "10m"}}
        self.assertEqual(self.func(assets), [])

    def test_all_excluded_by_name(self):
        """Every name in EXCLUDED_ASSETS is excluded."""
        from bdc_loader_plugin.stac.parsers import EXCLUDED_ASSETS

        assets = {name: {"type": "image/tiff; application=geotiff"} for name in EXCLUDED_ASSETS}
        result = self.func(assets)
        self.assertEqual(result, [])


class TestExtractBandsFromAssetsLandsatSensorVariants(unittest.TestCase):
    """Fixtures for the landsat-2 collection, which mixes three Landsat
    sensor generations (TM, ETM+, OLI/OLI-2) under a single STAC collection ID, each
    naming its own cloud/atmospheric-opacity QA mask differently. Fixtures below are
    the real asset dicts (name -> type) from live STAC items, one per sensor:
      - LT05_L2SP_228061_20081121_20200828_02_T1  (Landsat 5, TM)
      - a Landsat 7 ETM+ scene from the same collection
      - a Landsat 8/9 OLI/OLI-2 scene from the same collection
    """

    TIFF = "image/tiff; application=geotiff; profile=cloud-optimized"

    TM_ASSETS = {
        "ang": "text/plain",
        "blue": TIFF,
        "green": TIFF,
        "lwir": TIFF,
        "mtl.json": "application/json",
        "mtl.txt": "text/plain",
        "mtl.xml": "application/xml",
        "nir08": TIFF,
        "qa_pixel": TIFF,
        "qa_radsat": TIFF,
        "red": TIFF,
        "sr_stac": "application/json",
        "st_atran": TIFF,
        "st_cdist": TIFF,
        "st_drad": TIFF,
        "st_emis": TIFF,
        "st_emsd": TIFF,
        "st_qa": TIFF,
        "st_stac": "application/json",
        "st_trad": TIFF,
        "st_urad": TIFF,
        "swir16": TIFF,
        "swir22": TIFF,
        "thumb_large.jpeg": "image/jpeg",
        "thumb_small.jpeg": "image/jpeg",
        "thumbnail": "image/png",
        "tm_atmos_opacity": TIFF,
        "tm_cloud_qa": TIFF,
    }

    ETM_ASSETS = {
        "ang": "text/plain",
        "blue": TIFF,
        "etm_atmos_opacity": TIFF,
        "etm_cloud_qa": TIFF,
        "green": TIFF,
        "lwir": TIFF,
        "mtl.json": "application/json",
        "mtl.txt": "text/plain",
        "mtl.xml": "application/xml",
        "nir08": TIFF,
        "qa_pixel": TIFF,
        "qa_radsat": TIFF,
        "red": TIFF,
        "sr_stac": "application/json",
        "st_atran": TIFF,
        "st_cdist": TIFF,
        "st_drad": TIFF,
        "st_emis": TIFF,
        "st_emsd": TIFF,
        "st_qa": TIFF,
        "st_stac": "application/json",
        "st_trad": TIFF,
        "st_urad": TIFF,
        "swir16": TIFF,
        "swir22": TIFF,
        "thumb_large.jpeg": "image/jpeg",
        "thumb_small.jpeg": "image/jpeg",
        "thumbnail": "image/png",
    }

    OLI_ASSETS = {
        "ang": "text/plain",
        "blue": TIFF,
        "coastal": TIFF,
        "green": TIFF,
        "lwir11": TIFF,
        "mtl.txt": "text/plain",
        "mtl.xml": "application/xml",
        "nir08": TIFF,
        "qa_aerosol": TIFF,
        "qa_pixel": TIFF,
        "qa_radsat": TIFF,
        "red": TIFF,
        "st_atran": TIFF,
        "st_cdist": TIFF,
        "st_drad": TIFF,
        "st_emis": TIFF,
        "st_emsd": TIFF,
        "st_qa": TIFF,
        "st_trad": TIFF,
        "st_urad": TIFF,
        "swir16": TIFF,
        "swir22": TIFF,
        "thumbnail": "image/png",
    }

    def _assets(self, flat):
        return {name: {"type": t} for name, t in flat.items()}

    def setUp(self):
        from bdc_loader_plugin.stac.parsers import extract_bands_from_assets

        self.func = extract_bands_from_assets

    def test_tm_no_qa_leak(self):
        """tm_cloud_qa/tm_atmos_opacity must never surface as selectable bands."""
        result = self.func(self._assets(self.TM_ASSETS))
        self.assertNotIn("tm_cloud_qa", result)
        self.assertNotIn("tm_atmos_opacity", result)
        self.assertEqual(result, sorted(["blue", "green", "lwir", "nir08", "red", "swir16", "swir22"]))

    def test_etm_no_qa_leak(self):
        """etm_cloud_qa/etm_atmos_opacity must never surface as selectable bands."""
        result = self.func(self._assets(self.ETM_ASSETS))
        self.assertNotIn("etm_cloud_qa", result)
        self.assertNotIn("etm_atmos_opacity", result)
        self.assertEqual(result, sorted(["blue", "green", "lwir", "nir08", "red", "swir16", "swir22"]))

    def test_oli_no_qa_leak(self):
        """qa_aerosol must never surface as a selectable band."""
        result = self.func(self._assets(self.OLI_ASSETS))
        self.assertNotIn("qa_aerosol", result)
        self.assertEqual(result, sorted(["blue", "coastal", "green", "lwir11", "nir08", "red", "swir16", "swir22"]))

    def test_common_bands_consistent_across_sensor_generations(self):
        """red/green/blue/nir08/swir16/swir22 must resolve identically regardless of
        which Landsat sensor generation produced the scene — this is what makes True
        Color / False Color / SWIR presets work for any item in landsat-2."""
        common = {"red", "green", "blue", "nir08", "swir16", "swir22"}
        for fixture in (self.TM_ASSETS, self.ETM_ASSETS, self.OLI_ASSETS):
            result = set(self.func(self._assets(fixture)))
            self.assertTrue(common.issubset(result), f"missing common bands in {sorted(result)}")

    def test_sensor_specific_bands_not_falsely_universal(self):
        """coastal and lwir11 are OLI/OLI-2-only (Landsat 8/9); TM/ETM+ scenes (4/5/7)
        genuinely lack them (single 'lwir' instead of split lwir11). This documents the
        real-world limitation that the picker's static per-collection band list can
        offer a band a specific item doesn't have — resolve_band() must then report it
        as unavailable rather than the plugin silently failing to load anything."""
        tm_bands = set(self.func(self._assets(self.TM_ASSETS)))
        etm_bands = set(self.func(self._assets(self.ETM_ASSETS)))
        oli_bands = set(self.func(self._assets(self.OLI_ASSETS)))
        self.assertNotIn("coastal", tm_bands)
        self.assertNotIn("coastal", etm_bands)
        self.assertIn("coastal", oli_bands)
        self.assertNotIn("lwir11", tm_bands)
        self.assertNotIn("lwir11", etm_bands)
        self.assertIn("lwir11", oli_bands)


class TestExtractResolutionEdgeCases(unittest.TestCase):
    """Exhaustive tests for extract_resolution."""

    def setUp(self):
        from bdc_loader_plugin.stac.parsers import extract_resolution

        self.func = extract_resolution

    def test_none(self):
        self.assertEqual(self.func(None), "")

    def test_empty_list(self):
        self.assertEqual(self.func([]), "")

    def test_single_integer_resolution(self):
        self.assertEqual(self.func([{"resolution_x": 10.0}]), "10m")

    def test_single_float_resolution(self):
        result = self.func([{"resolution_x": 10.5}])
        self.assertIn("10.5", result)

    def test_multiple_resolutions(self):
        bands = [{"resolution_x": 10.0}, {"resolution_x": 20.0}, {"resolution_x": 60.0}]
        result = self.func(bands)
        self.assertEqual(result, "10-60m")

    def test_duplicate_resolutions(self):
        bands = [{"resolution_x": 10.0}, {"resolution_x": 10.0}]
        self.assertEqual(self.func(bands), "10m")

    def test_gsd_fallback(self):
        bands = [{"gsd": 30.0}]
        self.assertEqual(self.func(bands), "30m")

    def test_resolution_x_preferred_over_gsd(self):
        bands = [{"resolution_x": 10.0, "gsd": 20.0}]
        self.assertEqual(self.func(bands), "10m")

    def test_zero_resolution_ignored(self):
        bands = [{"resolution_x": 0}]
        self.assertEqual(self.func(bands), "")

    def test_negative_resolution_ignored(self):
        bands = [{"resolution_x": -10.0}]
        self.assertEqual(self.func(bands), "")

    def test_no_resolution_keys(self):
        bands = [{"common_name": "nir"}]
        self.assertEqual(self.func(bands), "")


class TestExtractTileFromIdEdgeCases(unittest.TestCase):
    """Exhaustive tests for extract_tile_from_id."""

    def setUp(self):
        from bdc_loader_plugin.stac.parsers import extract_tile_from_id

        self.func = extract_tile_from_id

    # --- Null and empty inputs ---
    def test_none(self):
        self.assertEqual(self.func(None), "NA")

    def test_empty(self):
        self.assertEqual(self.func(""), "NA")

    def test_random_string(self):
        self.assertEqual(self.func("random_text"), "NA")

    # --- Sentinel-2 ---
    def test_sentinel_standard(self):
        self.assertEqual(self.func("S2A_MSIL2A_20230101T000000_T19MCP"), "19MCP")

    def test_sentinel_2b(self):
        self.assertEqual(self.func("S2B_MSIL2A_20230615T130000_T22KGA"), "22KGA")

    def test_sentinel_no_tile(self):
        result = self.func("S2A_MSIL2A_20230101T000000")
        self.assertEqual(result, "NA")

    # --- Landsat ---
    def test_landsat_l8(self):
        self.assertEqual(self.func("LC08_L2SP_219066_20230101"), "219066")

    def test_landsat_l9(self):
        self.assertEqual(self.func("LC09_L2SP_221067_20230201"), "221067")

    def test_landsat_invalid_path_row(self):
        result = self.func("LC08_L2SP_abc_20230101")
        self.assertEqual(result, "NA")

    # --- BDC Cube IDs ---
    def test_bdc_cube_s2_16d(self):
        result = self.func("S2-16D-2_002011_V2023-01-01_2023-01-16")
        self.assertEqual(result, "002011")

    def test_bdc_cube_landsat_16d(self):
        result = self.func("LANDSAT-16D-1_042024_V2023-01-01_2023-01-16")
        self.assertEqual(result, "042024")

    def test_bdc_cube_cbers_wfi(self):
        result = self.func("CBERS4-WFI-16D-2_002011_V2023-01-01_2023-01-16")
        # CBERS path matches first - returns path/row format
        self.assertIsInstance(result, str)

    # --- MODIS ---
    def test_modis_standard(self):
        self.assertEqual(self.func("mod13q1-6.1_h13v11_2023001"), "h13v11")

    def test_modis_uppercase(self):
        self.assertEqual(self.func("MOD13Q1_H13V11_2023001"), "h13v11")

    # --- CBERS/AMAZONIA ---
    def test_cbers_path_row(self):
        result = self.func("CBERS_4_MUX_20230101_155_123_L4")
        self.assertIn("/", result)

    def test_amazonia_path_row(self):
        result = self.func("AMAZONIA_1_WFI_20230101_036_018_L4")
        self.assertIn("/", result)

    def test_cbers_composite_keeps_real_path_row(self):
        result = self.func("CBERS_4_AWFI_20240520_160_135_L2_B_compose")
        self.assertEqual(result, "160/135")

    def test_cbers_mosaic_dates_are_not_path_row(self):
        result = self.func("MOSAIC-CBERS4A-PARAIBA-3M_V1_20200701_20200930_P20201001")
        self.assertEqual(result, "NA")

    def test_cbers_pca_scene_keeps_real_path_row(self):
        result = self.func("CBERS4A_WPM_PCA_RGB321_20260720_213_115")
        self.assertEqual(result, "213/115")

    # --- Special types ---
    def test_item_with_underscores_only(self):
        result = self.func("a_b_c")
        self.assertEqual(result, "NA")

    def test_item_with_no_underscores(self):
        result = self.func("simpleid")
        self.assertEqual(result, "NA")


class TestExtractTileFromItemEdgeCases(unittest.TestCase):
    """Exhaustive tests for extract_tile_from_item."""

    def setUp(self):
        from bdc_loader_plugin.stac.parsers import extract_tile_from_item

        self.func = extract_tile_from_item

    def test_bdc_tiles_property(self):
        item = MagicMock()
        item.properties = {"bdc:tiles": ["002011"]}
        item.id = "S2-16D-2_002011_V2023-01-01_2023-01-16"
        self.assertEqual(self.func(item), "002011")

    def test_bdc_tiles_empty_list(self):
        item = MagicMock()
        item.properties = {"bdc:tiles": []}
        item.id = "S2A_MSIL2A_20230101T000000_T19MCP"
        self.assertEqual(self.func(item), "19MCP")

    def test_row_path_properties(self):
        item = MagicMock()
        item.properties = {"row": "066", "path": "219"}
        item.id = "test_item"
        self.assertEqual(self.func(item), "219/066")

    def test_fallback_to_id_parsing(self):
        item = MagicMock()
        item.properties = {}
        item.id = "mod13q1-6.1_h13v11_2023001"
        self.assertEqual(self.func(item), "h13v11")

    def test_gridless_sentinel1_falls_back_to_real_item_id(self):
        item = MagicMock()
        item.properties = {}
        item.id = "S1A_IW_RTCH_1SDV_20260620_065050_0832F0_8892"
        self.assertEqual(self.func(item), item.id)

    def test_unknown_gridless_item_id_is_sanitized(self):
        item = MagicMock()
        item.properties = {}
        item.id = "../unsafe-scene"
        self.assertEqual(self.func(item), "unsafe-scene")

    def test_none_properties(self):
        item = MagicMock()
        item.properties = None
        item.id = "S2A_MSIL2A_20230101T000000_T19MCP"
        self.assertEqual(self.func(item), "19MCP")

    def test_no_properties_attr(self):
        """An item without properties (getattr default)."""
        item = MagicMock(spec=[])
        item.id = "test"
        # properties is {} through the getattr default
        result = self.func(item)
        self.assertIsInstance(result, str)


class TestFormatTileDisplayEdgeCases(unittest.TestCase):
    """Exhaustive tests for format_tile_display."""

    def setUp(self):
        from bdc_loader_plugin.stac.parsers import format_tile_display

        self.func = format_tile_display

    def test_mgrs(self):
        self.assertEqual(self.func("19MCP", "MGRS"), "MGRS 19MCP")

    def test_wrs2_6digit(self):
        result = self.func("219066", "WRS2")
        self.assertEqual(result, "WRS-2 219/066")

    def test_wrs2_non_6digit(self):
        result = self.func("21906", "WRS2")
        self.assertEqual(result, "WRS-2 21906")

    def test_stg_modis(self):
        self.assertEqual(self.func("h13v11", "STG"), "MODIS h13v11")

    def test_bdc_grid(self):
        result = self.func("002011", "BDC_SM_V2")
        self.assertEqual(result, "BDC 002011")

    def test_bdc_md_grid(self):
        result = self.func("042024", "BDC_MD_V2")
        self.assertEqual(result, "BDC 042024")

    def test_row_path_format(self):
        self.assertEqual(self.func("219/066", "CBERS4_MUX_GRID"), "ROW/PATH 219/066")

    def test_unknown_grid(self):
        result = self.func("12345", "UNKNOWN_GRID")
        self.assertEqual(result, "12345")


class TestRegexPatterns(unittest.TestCase):
    """Exhaustive tests for every regex pattern."""

    def setUp(self):
        from bdc_loader_plugin.stac.parsers import (
            MGRS_PATTERN,
            ROW_PATH_PATTERN,
            STG_PATTERN,
            TILE_PATTERN,
            WRS2_PATTERN,
        )

        self.tile = TILE_PATTERN
        self.mgrs = MGRS_PATTERN
        self.wrs2 = WRS2_PATTERN
        self.stg = STG_PATTERN
        self.rowpath = ROW_PATH_PATTERN

    # TILE_PATTERN: exactly 6 digits
    def test_tile_valid(self):
        for t in ["000000", "002011", "999999", "123456"]:
            self.assertIsNotNone(self.tile.match(t), f"TILE should accept {t}")

    def test_tile_invalid(self):
        for t in ["00000", "0000000", "abcdef", "12345a", ""]:
            self.assertIsNone(self.tile.match(t), f"TILE should not accept {t}")

    # MGRS_PATTERN: 2 digits + 3 uppercase letters
    def test_mgrs_valid(self):
        for m in ["19MCP", "22KGA", "01ABC", "99ZZZ"]:
            self.assertIsNotNone(self.mgrs.match(m), f"MGRS should accept {m}")

    def test_mgrs_invalid(self):
        for m in ["1MCP", "19mc", "19MCPE", "19MC", "ABCDE", ""]:
            self.assertIsNone(self.mgrs.match(m), f"MGRS should not accept {m}")

    # WRS2_PATTERN: exactly 6 digits (same as TILE for matching)
    def test_wrs2_valid(self):
        for w in ["219066", "001001", "999999"]:
            self.assertIsNotNone(self.wrs2.match(w), f"WRS2 should accept {w}")

    def test_wrs2_invalid(self):
        for w in ["21906", "2190660", "219/066"]:
            self.assertIsNone(self.wrs2.match(w), f"WRS2 should not accept {w}")

    # STG_PATTERN: h##v## (case insensitive)
    def test_stg_valid(self):
        for s in ["h13v11", "H13V11", "h00v00", "h99v99"]:
            self.assertIsNotNone(self.stg.match(s), f"STG should accept {s}")

    def test_stg_invalid(self):
        for s in ["h1v1", "h13v1", "hh13v11", "13v11", ""]:
            self.assertIsNone(self.stg.match(s), f"STG should not accept {s}")

    # ROW_PATH_PATTERN: 1-to-3 digits path/row (e.g. 219/066, 32/14, 040_015)
    def test_rowpath_valid(self):
        for r in ["219/066", "001/001", "999/999", "32/14", "040_015", "40-15"]:
            self.assertIsNotNone(self.rowpath.match(r), f"ROWPATH should accept {r}")

    def test_rowpath_invalid(self):
        for r in ["219066", "2190/066", "219/0660", ""]:
            self.assertIsNone(self.rowpath.match(r), f"ROWPATH should not accept {r}")


class TestExcludedAssets(unittest.TestCase):
    """Consistency of the EXCLUDED_ASSETS list."""

    def test_common_qa_excluded(self):
        from bdc_loader_plugin.stac.parsers import EXCLUDED_ASSETS

        expected_excluded = ["thumbnail", "qa_pixel", "qa_aerosol", "CMASK", "SCL"]
        for name in expected_excluded:
            self.assertIn(name, EXCLUDED_ASSETS, f"{name} should be excluded")

    def test_landsat_sensor_qa_variants_excluded(self):
        """tm_cloud_qa/tm_atmos_opacity (TM) and etm_cloud_qa/etm_atmos_opacity (ETM+)
        are the per-sensor equivalents of sr_cloud_qa/sr_atmos_opacity (OLI) in the
        landsat-2 collection, which mixes Landsat 4/5 (TM), 7 (ETM+) and 8/9 (OLI) under one ID."""
        from bdc_loader_plugin.stac.parsers import EXCLUDED_ASSETS

        for name in ["tm_cloud_qa", "tm_atmos_opacity", "etm_cloud_qa", "etm_atmos_opacity"]:
            self.assertIn(name, EXCLUDED_ASSETS, f"{name} should be excluded")

    def test_no_valid_bands_excluded(self):
        from bdc_loader_plugin.stac.parsers import EXCLUDED_ASSETS

        valid_bands = [
            "B01",
            "B02",
            "B03",
            "B04",
            "B05",
            "B06",
            "B07",
            "B08",
            "B8A",
            "B09",
            "B11",
            "B12",
            "NDVI",
            "EVI",
            "NBR",
            "red",
            "green",
            "blue",
            "nir08",
        ]
        for band in valid_bands:
            self.assertNotIn(band, EXCLUDED_ASSETS, f"{band} should not be excluded")


if __name__ == "__main__":
    unittest.main()
