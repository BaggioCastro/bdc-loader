#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_client_fallback.py — tests for stac/client.py and stac/fallback.py

Covers: constants, fetch with mocked requests, fallback data integrity,
cross-validation between fallback and parsers, network exceptions.

Run: python3 -m pytest bdc_loader_plugin/tests/test_client_fallback.py -v
"""

import unittest
from unittest.mock import MagicMock, patch

# ── STAC Client Tests ────────────────────────────────────────────────────────


class TestClientConstants(unittest.TestCase):
    """Constants of the client."""

    def test_stac_url_format(self):
        from bdc_loader_plugin.stac.client import STAC_URL

        self.assertTrue(STAC_URL.startswith("https://"))
        self.assertIn("stac", STAC_URL.lower())

    def test_bdc_doc_url_format(self):
        from bdc_loader_plugin.stac.client import BDC_DOC_URL

        self.assertTrue(BDC_DOC_URL.startswith("https://"))

    def test_supported_ids_known_collections(self):
        from bdc_loader_plugin.stac.client import SUPPORTED_COLLECTION_IDS

        expected = ["S2-16D-2", "S2_L2A-1", "LANDSAT-16D-1", "landsat-2"]
        for cid in expected:
            self.assertIn(cid, SUPPORTED_COLLECTION_IDS)

    def test_grs_to_grid_known_mappings(self):
        from bdc_loader_plugin.stac.client import GRS_TO_GRID

        self.assertEqual(GRS_TO_GRID["MGRS"], "MGRS")
        self.assertEqual(GRS_TO_GRID["WRS2"], "WRS2")
        self.assertIn("BDC_SM_V2", GRS_TO_GRID)


class TestCollectionCompatibility(unittest.TestCase):
    """Collection filtering follows advertised GeoTIFF/COG capabilities."""

    @staticmethod
    def _collection(collection_id, bdc_type="collection", media_type="image/tiff; profile=cloud-optimized"):
        return {
            "id": collection_id,
            "title": collection_id,
            "bdc:type": bdc_type,
            "item_assets": {"visual": {"type": media_type}},
        }

    def test_accepts_live_cog_product_families(self):
        from bdc_loader_plugin.stac.client import is_supported_image_collection

        collections = [
            self._collection("mosaic-s2-brazil-3m-1", bdc_type="mosaic"),
            self._collection("sentinel-1-rtc-1"),
            self._collection("s3-olci-rrs-water-1"),
            self._collection("charter-wfi-1"),
        ]

        self.assertTrue(all(is_supported_image_collection(collection) for collection in collections))

    def test_accepts_cog_declared_only_by_asset_media_type(self):
        from bdc_loader_plugin.stac.client import collection_is_cog, is_supported_image_collection

        collection = self._collection("mime-only-cog")

        self.assertTrue(collection_is_cog(collection))
        self.assertTrue(is_supported_image_collection(collection))

    def test_rejects_non_geotiff_asset_collections(self):
        from bdc_loader_plugin.stac.client import is_supported_image_collection

        for media_type in ("application/zip", "application/netcdf", "application/wmo-GRIB2"):
            with self.subTest(media_type=media_type):
                collection = self._collection("unsupported", bdc_type="cube", media_type=media_type)
                self.assertFalse(is_supported_image_collection(collection))

    def test_preserves_cube_without_item_assets(self):
        from bdc_loader_plugin.stac.client import is_supported_image_collection

        self.assertTrue(is_supported_image_collection({"id": "legacy-cube", "bdc:type": "cube"}))


class TestCollectionAssetAvailability(unittest.TestCase):
    """Collection asset checks use a cheap fast path and paginate only if needed."""

    @staticmethod
    def _response(features, links=None):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "features": features,
            "links": links or [],
        }
        return response

    @patch("bdc_loader_plugin.stac.client.requests.get")
    def test_first_item_with_all_assets_uses_one_request(self, mock_get):
        from bdc_loader_plugin.stac.client import fetch_collection_asset_names

        mock_get.return_value = self._response([{"assets": {"B02": {}, "B03": {}, "B04": {}}}])

        result = fetch_collection_asset_names("optical", ["B02", "B03", "B04"])

        self.assertEqual(result, {"B02", "B03", "B04"})
        mock_get.assert_called_once()
        self.assertEqual(mock_get.call_args.kwargs["params"], {"limit": 1})

    @patch("bdc_loader_plugin.stac.client.requests.get")
    def test_missing_first_item_asset_triggers_paginated_union(self, mock_get):
        from bdc_loader_plugin.stac.client import DEFAULT_MAX_ITEMS, fetch_collection_asset_names

        next_url = "https://stac.example.test/items?page=2"
        mock_get.side_effect = [
            self._response([{"assets": {"Gamma0_VV": {}}}]),
            self._response(
                [{"assets": {"Gamma0_VV": {}}}],
                [{"rel": "next", "href": next_url}],
            ),
            self._response([{"assets": {"Gamma0_HH": {}}}]),
        ]

        result = fetch_collection_asset_names(
            "sentinel-1-rtc-1",
            ["Gamma0_HH", "Gamma0_VV"],
        )

        self.assertEqual(result, {"Gamma0_HH", "Gamma0_VV"})
        self.assertEqual(mock_get.call_count, 3)
        self.assertEqual(mock_get.call_args_list[1].kwargs["params"], {"limit": DEFAULT_MAX_ITEMS})
        self.assertEqual(mock_get.call_args_list[2].args[0], next_url)

    @patch("bdc_loader_plugin.stac.client.requests.get")
    def test_scan_stops_at_the_page_budget_and_says_so(self, mock_get):
        """landsat-2 advertises lwir, which only old scenes carry: never page the whole catalogue."""
        from bdc_loader_plugin.stac.client import fetch_collection_asset_names

        endless = self._response([{"assets": {"lwir11": {}}}], [{"rel": "next", "href": "?page=n"}])
        pages = iter(range(1000))

        def _page(url, params=None, timeout=None):
            next(pages)
            endless.json.return_value = {
                "features": [{"assets": {"lwir11": {}}}],
                "links": [{"rel": "next", "href": f"?page={mock_get.call_count}"}],
            }
            return endless

        mock_get.side_effect = _page

        result = fetch_collection_asset_names("landsat-2", ["lwir", "lwir11"], max_pages=3)

        self.assertEqual(result, {"lwir11"})
        self.assertFalse(result.complete)
        self.assertEqual(mock_get.call_count, 4)

    @patch("bdc_loader_plugin.stac.client.requests.get")
    def test_finished_scan_is_complete(self, mock_get):
        from bdc_loader_plugin.stac.client import fetch_collection_asset_names

        mock_get.return_value = self._response([{"assets": {"B02": {}}}])

        self.assertTrue(fetch_collection_asset_names("optical", ["B02", "B03"]).complete)


# ── Fallback Data Integrity Tests ─────────────────────────────────────────────


class TestFallbackBandInfo(unittest.TestCase):
    """Integrity and structure of FALLBACK_BAND_INFO."""

    def setUp(self):
        from bdc_loader_plugin.stac.fallback import FALLBACK_BAND_INFO

        self.data = FALLBACK_BAND_INFO

    def test_not_empty(self):
        self.assertGreater(len(self.data), 0)

    def test_all_keys_are_collection_ids(self):
        from bdc_loader_plugin.stac.client import SUPPORTED_COLLECTION_IDS

        for cid in self.data:
            self.assertIn(
                cid, SUPPORTED_COLLECTION_IDS, f"FALLBACK_BAND_INFO key '{cid}' not in SUPPORTED_COLLECTION_IDS"
            )

    def test_band_info_structure(self):
        """Every band has common_name, wavelength and resolution."""
        for cid, bands in self.data.items():
            self.assertIsInstance(bands, dict, f"{cid} bands should be dict")
            for band_name, info in bands.items():
                self.assertIn("common_name", info, f"{cid}/{band_name} missing common_name")
                self.assertIn("wavelength", info, f"{cid}/{band_name} missing wavelength")
                self.assertIn("resolution", info, f"{cid}/{band_name} missing resolution")

    def test_resolution_format(self):
        """Resolution ends with 'm'."""
        for cid, bands in self.data.items():
            for band_name, info in bands.items():
                res = info["resolution"]
                self.assertTrue(res.endswith("m"), f"{cid}/{band_name} resolution '{res}' should end with 'm'")


class TestFallbackCollections(unittest.TestCase):
    """Integrity of FALLBACK_COLLECTIONS."""

    def setUp(self):
        from bdc_loader_plugin.stac.fallback import FALLBACK_COLLECTIONS

        self.data = FALLBACK_COLLECTIONS

    def test_not_empty(self):
        self.assertGreater(len(self.data), 0)

    def test_required_fields(self):
        required = ["id", "temporal", "bands", "grid", "type", "resolution", "compositing", "platform", "doc_url"]
        for name, col in self.data.items():
            for field in required:
                self.assertIn(field, col, f"Missing '{field}' in collection '{name}'")

    def test_temporal_is_tuple_of_two(self):
        for name, col in self.data.items():
            t = col["temporal"]
            self.assertIsInstance(t, tuple, f"temporal in '{name}' should be tuple")
            self.assertEqual(len(t), 2, f"temporal in '{name}' should have 2 elements")

    def test_type_values(self):
        valid_types = {"cube", "collection", "mosaic", "classification"}
        for name, col in self.data.items():
            self.assertIn(col["type"], valid_types, f"Invalid type in '{name}'")

    def test_doc_urls_are_valid(self):
        for name, col in self.data.items():
            self.assertTrue(col["doc_url"].startswith("https://"), f"Invalid doc_url in '{name}'")

    def test_ids_are_unique(self):
        ids = [col["id"] for col in self.data.values()]
        self.assertEqual(len(ids), len(set(ids)), "Duplicate IDs in FALLBACK_COLLECTIONS")


class TestFallbackGridUrls(unittest.TestCase):
    """FALLBACK_GRID_URLS."""

    def setUp(self):
        from bdc_loader_plugin.stac.fallback import FALLBACK_GRID_URLS

        self.data = FALLBACK_GRID_URLS

    def test_not_empty(self):
        self.assertGreater(len(self.data), 0)

    def test_all_urls_are_valid(self):
        for grid, url in self.data.items():
            self.assertTrue(url.startswith("https://"), f"Grid '{grid}' URL should start with https://")

    def test_known_grids_present(self):
        for grid in ["BDC_LG_V2", "BDC_MD_V2", "BDC_SM_V2", "MGRS", "WRS2"]:
            self.assertIn(grid, self.data, f"Missing grid URL for '{grid}'")


class TestFallbackRGBPresets(unittest.TestCase):
    """FALLBACK_RGB_PRESETS."""

    def setUp(self):
        from bdc_loader_plugin.stac.fallback import FALLBACK_RGB_PRESETS

        self.data = FALLBACK_RGB_PRESETS

    def test_not_empty(self):
        self.assertGreater(len(self.data), 0)

    def test_rgb_presets_reference_valid_bands(self):
        """The bands of the presets exist in FALLBACK_BAND_INFO."""
        from bdc_loader_plugin.stac.fallback import FALLBACK_BAND_INFO, FALLBACK_COLLECTIONS

        for col_name, presets in self.data.items():
            # Find the collection ID
            col_info = FALLBACK_COLLECTIONS.get(col_name, {})
            cid = col_info.get("id", "")
            if cid not in FALLBACK_BAND_INFO:
                continue
            valid_bands = set(FALLBACK_BAND_INFO[cid].keys())
            for preset_name, bands in presets.items():
                for band in bands:
                    self.assertIn(
                        band,
                        valid_bands,
                        f"Band '{band}' in preset '{preset_name}' for '{col_name}' "
                        f"not found in FALLBACK_BAND_INFO['{cid}']",
                    )


class TestIdToDisplayName(unittest.TestCase):
    """ID_TO_DISPLAY_NAME."""

    def setUp(self):
        from bdc_loader_plugin.stac.fallback import ID_TO_DISPLAY_NAME

        self.data = ID_TO_DISPLAY_NAME

    def test_not_empty(self):
        self.assertGreater(len(self.data), 0)

    def test_maps_to_fallback_collections(self):
        from bdc_loader_plugin.stac.fallback import FALLBACK_COLLECTIONS

        for cid, display_name in self.data.items():
            self.assertIn(
                display_name,
                FALLBACK_COLLECTIONS,
                f"Display name '{display_name}' for ID '{cid}' not in FALLBACK_COLLECTIONS",
            )

    def test_all_fallback_ids_have_display_name(self):
        from bdc_loader_plugin.stac.fallback import FALLBACK_COLLECTIONS

        for name, col in FALLBACK_COLLECTIONS.items():
            cid = col["id"]
            self.assertIn(cid, self.data, f"ID '{cid}' from FALLBACK_COLLECTIONS should have a display name")


# ── Cross-validation Tests ────────────────────────────────────────────────────


class TestCrossValidation(unittest.TestCase):
    """Cross-checks between modules."""

    def test_supported_ids_match_fallback(self):
        """Every ID of FALLBACK_COLLECTIONS is in SUPPORTED_COLLECTION_IDS."""
        from bdc_loader_plugin.stac.client import SUPPORTED_COLLECTION_IDS
        from bdc_loader_plugin.stac.fallback import FALLBACK_COLLECTIONS

        for name, col in FALLBACK_COLLECTIONS.items():
            cid = col["id"]
            self.assertIn(cid, SUPPORTED_COLLECTION_IDS, f"'{cid}' from fallback not in SUPPORTED_COLLECTION_IDS")

    def test_stac_modules_import(self):
        import importlib

        for name in ("client", "fallback", "parsers"):
            module = importlib.import_module(f"bdc_loader_plugin.stac.{name}")
            self.assertEqual(module.__name__, f"bdc_loader_plugin.stac.{name}")


if __name__ == "__main__":
    unittest.main()
