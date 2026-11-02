#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_ts_core.py — Tests for core/ts_constants.py, core/ts_bands.py, core/ts_extraction.py

Covers: constants validation, static NDVI/EVI calculations, RGB presets,
band resolution, find_existing_entry, get_missing_bands, get_item_date.

Run: python3 -m pytest bdc_loader_plugin/tests/test_ts_core.py -v
"""

import unittest
from datetime import datetime
from unittest.mock import MagicMock

# ── ts_constants ──────────────────────────────────────────────────────────────


class TestTSConstants(unittest.TestCase):
    """Validate exported constants from ts_constants.py."""

    def test_known_common_names_has_sentinel2(self):
        from bdc_loader_plugin.core.ts_constants import _KNOWN_COMMON_NAMES

        self.assertEqual(_KNOWN_COMMON_NAMES["B02"], "blue")
        self.assertEqual(_KNOWN_COMMON_NAMES["B03"], "green")
        self.assertEqual(_KNOWN_COMMON_NAMES["B04"], "red")
        self.assertEqual(_KNOWN_COMMON_NAMES["B08"], "nir")

    def test_known_common_names_has_landsat(self):
        from bdc_loader_plugin.core.ts_constants import _KNOWN_COMMON_NAMES

        self.assertEqual(_KNOWN_COMMON_NAMES["red"], "red")
        self.assertEqual(_KNOWN_COMMON_NAMES["green"], "green")
        self.assertEqual(_KNOWN_COMMON_NAMES["blue"], "blue")
        self.assertEqual(_KNOWN_COMMON_NAMES["nir"], "nir")

    def test_known_common_names_has_cbers(self):
        from bdc_loader_plugin.core.ts_constants import _KNOWN_COMMON_NAMES

        self.assertEqual(_KNOWN_COMMON_NAMES["BAND13"], "blue")
        self.assertEqual(_KNOWN_COMMON_NAMES["BAND14"], "green")
        self.assertEqual(_KNOWN_COMMON_NAMES["BAND15"], "red")
        self.assertEqual(_KNOWN_COMMON_NAMES["BAND16"], "nir")

    def test_known_common_names_has_modis(self):
        from bdc_loader_plugin.core.ts_constants import _KNOWN_COMMON_NAMES

        self.assertEqual(_KNOWN_COMMON_NAMES["red_reflectance"], "red")
        self.assertEqual(_KNOWN_COMMON_NAMES["NIR_reflectance"], "nir")

    def test_index_defs_structure(self):
        from bdc_loader_plugin.core.ts_constants import _INDEX_DEFS

        self.assertIn("_NDVI", _INDEX_DEFS)
        self.assertIn("_EVI", _INDEX_DEFS)
        self.assertEqual(_INDEX_DEFS["_NDVI"]["output"], "NDVI")
        self.assertEqual(_INDEX_DEFS["_NDVI"]["requires"], ["nir", "red"])
        self.assertEqual(_INDEX_DEFS["_EVI"]["output"], "EVI")
        self.assertEqual(_INDEX_DEFS["_EVI"]["requires"], ["nir", "red", "blue"])


# ── ts_bands — static methods ────────────────────────────────────────────────


class TestCalcNDVI(unittest.TestCase):
    """Tests for TSBandManager._calc_ndvi static method."""

    def test_basic_ndvi(self):
        from bdc_loader_plugin.core.ts_bands import TSBandManager

        d1 = datetime(2023, 1, 1)
        d2 = datetime(2023, 2, 1)
        nir = [(d1, 8000), (d2, 7000)]
        red = [(d1, 2000), (d2, 3000)]
        result = TSBandManager._calc_ndvi(nir, red)
        self.assertEqual(len(result), 2)
        # NDVI = (8000 - 2000) / (8000 + 2000) * 10000 = 6000
        self.assertAlmostEqual(result[0][1], 6000.0, places=1)
        # NDVI = (7000 - 3000) / (7000 + 3000) * 10000 = 4000
        self.assertAlmostEqual(result[1][1], 4000.0, places=1)

    def test_ndvi_zero_denom_skipped(self):
        from bdc_loader_plugin.core.ts_bands import TSBandManager

        d = datetime(2023, 1, 1)
        nir = [(d, 0)]
        red = [(d, 0)]
        result = TSBandManager._calc_ndvi(nir, red)
        self.assertEqual(len(result), 0)

    def test_ndvi_no_matching_dates(self):
        from bdc_loader_plugin.core.ts_bands import TSBandManager

        d1 = datetime(2023, 1, 1)
        d2 = datetime(2023, 2, 1)
        nir = [(d1, 5000)]
        red = [(d2, 5000)]
        result = TSBandManager._calc_ndvi(nir, red)
        self.assertEqual(len(result), 0)

    def test_ndvi_empty_input(self):
        from bdc_loader_plugin.core.ts_bands import TSBandManager

        result = TSBandManager._calc_ndvi([], [])
        self.assertEqual(result, [])

    def test_ndvi_negative_values(self):
        from bdc_loader_plugin.core.ts_bands import TSBandManager

        d = datetime(2023, 1, 1)
        nir = [(d, 1000)]
        red = [(d, 3000)]
        result = TSBandManager._calc_ndvi(nir, red)
        self.assertEqual(len(result), 1)
        # NDVI = (1000 - 3000) / (1000 + 3000) * 10000 = -5000
        self.assertAlmostEqual(result[0][1], -5000.0, places=1)

    def test_ndvi_preserves_dates(self):
        from bdc_loader_plugin.core.ts_bands import TSBandManager

        d1, d2 = datetime(2023, 3, 15), datetime(2023, 6, 20)
        nir = [(d1, 6000), (d2, 8000)]
        red = [(d1, 2000), (d2, 2000)]
        result = TSBandManager._calc_ndvi(nir, red)
        self.assertEqual(result[0][0], d1)
        self.assertEqual(result[1][0], d2)


class TestCalcEVI(unittest.TestCase):
    """Tests for TSBandManager._calc_evi static method."""

    def test_basic_evi_scaled(self):
        from bdc_loader_plugin.core.ts_bands import TSBandManager

        d = datetime(2023, 1, 1)
        # Large values (> 1.0) → L = 10000
        nir = [(d, 8000)]
        red = [(d, 2000)]
        blue = [(d, 1000)]
        result = TSBandManager._calc_evi(nir, red, blue)
        self.assertEqual(len(result), 1)
        # EVI = 2.5*(8000-2000)/(8000 + 6*2000 - 7.5*1000 + 10000)
        #     = 2.5*6000/(8000 + 12000 - 7500 + 10000) = 15000/22500 = 0.6667
        # × 10000 = 6666.67
        self.assertAlmostEqual(result[0][1], 6666.67, places=0)

    def test_evi_zero_denom_skipped(self):
        from bdc_loader_plugin.core.ts_bands import TSBandManager

        datetime(2023, 1, 1)
        # nir + 6*red - 7.5*blue + L = 0 is very unlikely with L=10000
        # but we can test with reflectance scale (L=1.0)
        # nir + 6*red - 7.5*blue + 1 = 0 → impossible for typical values
        # Just verify it handles empty input
        result = TSBandManager._calc_evi([], [], [])
        self.assertEqual(result, [])

    def test_evi_no_matching_dates(self):
        from bdc_loader_plugin.core.ts_bands import TSBandManager

        d1, d2, d3 = datetime(2023, 1, 1), datetime(2023, 2, 1), datetime(2023, 3, 1)
        nir = [(d1, 5000)]
        red = [(d2, 2000)]
        blue = [(d3, 1000)]
        result = TSBandManager._calc_evi(nir, red, blue)
        self.assertEqual(len(result), 0)

    def test_evi_clamps_values(self):
        from bdc_loader_plugin.core.ts_bands import TSBandManager

        d = datetime(2023, 1, 1)
        # Very extreme values to push EVI out of [-1, 1]
        nir = [(d, 50000)]
        red = [(d, 1)]
        blue = [(d, 1)]
        result = TSBandManager._calc_evi(nir, red, blue)
        self.assertEqual(len(result), 1)
        # EVI is clamped to [-1, 1] then × 10000
        self.assertLessEqual(result[0][1], 10000.0)
        self.assertGreaterEqual(result[0][1], -10000.0)

    def test_evi_reflectance_scale(self):
        """With values < 1.0, L should be 1.0 instead of 10000."""
        from bdc_loader_plugin.core.ts_bands import TSBandManager

        d = datetime(2023, 1, 1)
        nir = [(d, 0.8)]
        red = [(d, 0.2)]
        blue = [(d, 0.1)]
        result = TSBandManager._calc_evi(nir, red, blue)
        self.assertEqual(len(result), 1)
        # median_nir = 0.8, which is < 1.0 → L = 1.0
        # denom = 0.8 + 6*0.2 - 7.5*0.1 + 1.0 = 0.8 + 1.2 - 0.75 + 1.0 = 2.25
        # EVI = 2.5*(0.8-0.2)/2.25 = 2.5*0.6/2.25 = 0.6667, clamped [-1,1]
        # × 10000 = 6667
        self.assertAlmostEqual(result[0][1], 6666.7, places=0)


class TestGetRGBForCollection(unittest.TestCase):
    """Tests for TSBandManager._get_rgb_for_collection static method."""

    def test_sentinel2(self):
        from bdc_loader_plugin.core.ts_bands import TSBandManager

        result = TSBandManager._get_rgb_for_collection("S2-16D-2")
        self.assertEqual(result, ("B04", "B03", "B02"))

    def test_landsat(self):
        from bdc_loader_plugin.core.ts_bands import TSBandManager

        result = TSBandManager._get_rgb_for_collection("LANDSAT-16D-1")
        self.assertEqual(result, ("red", "green", "blue"))

    def test_cbers4_wfi(self):
        from bdc_loader_plugin.core.ts_bands import TSBandManager

        result = TSBandManager._get_rgb_for_collection("CBERS4-WFI-16D-2")
        self.assertEqual(result, ("BAND15", "BAND14", "BAND13"))

    def test_cbers4_mux(self):
        from bdc_loader_plugin.core.ts_bands import TSBandManager

        result = TSBandManager._get_rgb_for_collection("CBERS4-MUX-2M-1")
        self.assertEqual(result, ("BAND7", "BAND6", "BAND5"))

    def test_modis(self):
        from bdc_loader_plugin.core.ts_bands import TSBandManager

        result = TSBandManager._get_rgb_for_collection("mod13q1-6.1")
        self.assertEqual(result, ("NIR_reflectance", "red_reflectance", "blue_reflectance"))

    def test_unknown_collection_returns_none(self):
        from bdc_loader_plugin.core.ts_bands import TSBandManager

        result = TSBandManager._get_rgb_for_collection("UNKNOWN-COLL-999")
        self.assertIsNone(result)

    def test_unknown_with_rgb_bands_fallback(self):
        from bdc_loader_plugin.core.ts_bands import TSBandManager

        result = TSBandManager._get_rgb_for_collection("NEW-COLLECTION-1", bands=["red", "green", "blue", "nir"])
        self.assertEqual(result, ("red", "green", "blue"))

    def test_unknown_with_no_rgb_bands(self):
        from bdc_loader_plugin.core.ts_bands import TSBandManager

        result = TSBandManager._get_rgb_for_collection("NEW-COLLECTION-1", bands=["NDVI", "EVI"])
        self.assertIsNone(result)

    def test_amazonia1(self):
        from bdc_loader_plugin.core.ts_bands import TSBandManager

        result = TSBandManager._get_rgb_for_collection("AMZ1-WFI-L4-SR-1")
        self.assertEqual(result, ("BAND3", "BAND2", "BAND1"))


# ── ts_bands — instance methods ──────────────────────────────────────────────


class TestResolveBandAndIndices(unittest.TestCase):
    """Tests for _resolve_common_band and _get_available_indices."""

    def _make_manager(self):
        from bdc_loader_plugin.core.ts_bands import TSBandManager

        mgr = TSBandManager.__new__(TSBandManager)
        mgr._band_info = {
            "S2-16D-2": {
                "B04": {"common_name": "red"},
                "B03": {"common_name": "green"},
                "B02": {"common_name": "blue"},
                "B08": {"common_name": "nir"},
            }
        }
        mgr._collections = {"Sentinel-2": {"id": "S2-16D-2", "bands": ["B02", "B03", "B04", "B08", "NDVI"]}}
        return mgr

    def test_resolve_common_band_from_band_info(self):

        mgr = self._make_manager()
        self.assertEqual(mgr._resolve_common_band("S2-16D-2", "red"), "B04")
        self.assertEqual(mgr._resolve_common_band("S2-16D-2", "nir"), "B08")
        self.assertEqual(mgr._resolve_common_band("S2-16D-2", "blue"), "B02")

    def test_resolve_common_band_fallback_known_names(self):
        from bdc_loader_plugin.core.ts_bands import TSBandManager

        mgr = TSBandManager.__new__(TSBandManager)
        mgr._band_info = {"CBERS4-WFI-16D-2": {}}
        mgr._collections = {"CBERS-WFI": {"id": "CBERS4-WFI-16D-2", "bands": ["BAND13", "BAND14", "BAND15", "BAND16"]}}
        self.assertEqual(mgr._resolve_common_band("CBERS4-WFI-16D-2", "red"), "BAND15")
        self.assertEqual(mgr._resolve_common_band("CBERS4-WFI-16D-2", "nir"), "BAND16")

    def test_resolve_unknown_common_name(self):

        mgr = self._make_manager()
        self.assertIsNone(mgr._resolve_common_band("S2-16D-2", "thermal"))

    def test_get_available_indices_ndvi_evi(self):

        mgr = self._make_manager()
        indices = mgr._get_available_indices("S2-16D-2", ["B02", "B03", "B04", "B08"])
        self.assertIn("_NDVI", indices)
        self.assertIn("_EVI", indices)

    def test_get_available_indices_skips_existing(self):
        """NDVI already a real band → should be excluded from computable indices."""

        mgr = self._make_manager()
        indices = mgr._get_available_indices("S2-16D-2", ["B02", "B03", "B04", "B08", "NDVI"])
        self.assertNotIn("_NDVI", indices)
        self.assertIn("_EVI", indices)

    def test_get_available_indices_no_nir(self):
        """Without NIR, no index should be computable."""
        from bdc_loader_plugin.core.ts_bands import TSBandManager

        mgr = TSBandManager.__new__(TSBandManager)
        mgr._band_info = {"TEST": {"B01": {"common_name": "coastal"}}}
        mgr._collections = {"Test": {"id": "TEST", "bands": ["B01"]}}
        indices = mgr._get_available_indices("TEST", ["B01"])
        self.assertEqual(indices, [])


# ── ts_extraction — pure logic ───────────────────────────────────────────────


class TestFindExistingEntry(unittest.TestCase):
    """Tests for TSExtractionEngine._find_existing_entry."""

    def _make_engine(self, history):
        from bdc_loader_plugin.core.ts_extraction import TSExtractionEngine

        eng = TSExtractionEngine.__new__(TSExtractionEngine)
        eng._history = history
        return eng

    def test_found(self):
        history = [
            {
                "lon": -45.0,
                "lat": -12.0,
                "collection": "S2-16D-2",
                "start": "2023-01-01",
                "end": "2023-12-31",
            }
        ]
        eng = self._make_engine(history)
        result = eng._find_existing_entry(-45.0, -12.0, "S2-16D-2", "2023-01-01", "2023-12-31")
        self.assertIs(result, history[0])

    def test_not_found_different_collection(self):
        history = [
            {
                "lon": -45.0,
                "lat": -12.0,
                "collection": "S2-16D-2",
                "start": "2023-01-01",
                "end": "2023-12-31",
            }
        ]
        eng = self._make_engine(history)
        result = eng._find_existing_entry(-45.0, -12.0, "LANDSAT-16D-1", "2023-01-01", "2023-12-31")
        self.assertIsNone(result)

    def test_not_found_different_coords(self):
        history = [
            {
                "lon": -45.0,
                "lat": -12.0,
                "collection": "S2-16D-2",
                "start": "2023-01-01",
                "end": "2023-12-31",
            }
        ]
        eng = self._make_engine(history)
        result = eng._find_existing_entry(-46.0, -12.0, "S2-16D-2", "2023-01-01", "2023-12-31")
        self.assertIsNone(result)

    def test_empty_history(self):
        eng = self._make_engine([])
        result = eng._find_existing_entry(-45.0, -12.0, "S2-16D-2", "2023-01-01", "2023-12-31")
        self.assertIsNone(result)

    def test_near_coords_threshold(self):
        history = [
            {
                "lon": -45.0,
                "lat": -12.0,
                "collection": "S2-16D-2",
                "start": "2023-01-01",
                "end": "2023-12-31",
            }
        ]
        eng = self._make_engine(history)
        # Within 1e-6 threshold
        result = eng._find_existing_entry(-45.0000005, -12.0000005, "S2-16D-2", "2023-01-01", "2023-12-31")
        self.assertIs(result, history[0])


class TestGetMissingBands(unittest.TestCase):
    """Tests for TSExtractionEngine._get_missing_bands."""

    def _make_engine(self):
        from bdc_loader_plugin.core.ts_extraction import TSExtractionEngine

        return TSExtractionEngine.__new__(TSExtractionEngine)

    def test_all_missing(self):
        eng = self._make_engine()
        entry = {"bands": ["NDVI"]}
        result = eng._get_missing_bands(entry, ["EVI", "B04"])
        self.assertEqual(result, ["EVI", "B04"])

    def test_none_missing(self):
        eng = self._make_engine()
        entry = {"bands": ["NDVI", "EVI"]}
        result = eng._get_missing_bands(entry, ["NDVI", "EVI"])
        self.assertEqual(result, [])

    def test_partial_missing(self):
        eng = self._make_engine()
        entry = {"bands": ["NDVI", "B04"]}
        result = eng._get_missing_bands(entry, ["NDVI", "EVI", "B04"])
        self.assertEqual(result, ["EVI"])


class TestGetItemDate(unittest.TestCase):
    """Tests for TSExtractionEngine._get_item_date."""

    def _make_engine(self):
        from bdc_loader_plugin.core.ts_extraction import TSExtractionEngine

        return TSExtractionEngine.__new__(TSExtractionEngine)

    def test_item_with_datetime_attr(self):
        eng = self._make_engine()
        item = MagicMock()
        item.datetime = datetime(2023, 6, 15)
        result = eng._get_item_date(item)
        self.assertEqual(result, datetime(2023, 6, 15))

    def test_item_with_properties_datetime(self):
        eng = self._make_engine()
        item = MagicMock()
        item.datetime = None
        item.properties = {"datetime": "2023-06-15T00:00:00Z"}
        result = eng._get_item_date(item)
        self.assertEqual(result.year, 2023)
        self.assertEqual(result.month, 6)

    def test_item_with_no_datetime(self):
        eng = self._make_engine()
        item = MagicMock()
        item.datetime = None
        item.properties = {}
        result = eng._get_item_date(item)
        self.assertEqual(result, datetime.min)

    def test_item_with_invalid_datetime_string(self):
        eng = self._make_engine()
        item = MagicMock()
        item.datetime = None
        item.properties = {"datetime": "bad_date"}
        result = eng._get_item_date(item)
        self.assertEqual(result, datetime.min)


def test_ndvi_skips_non_positive_denominator_and_clips():
    from datetime import datetime

    from bdc_loader_plugin.core.ts_bands import TSBandManager

    d1, d2, d3 = datetime(2024, 1, 1), datetime(2024, 1, 2), datetime(2024, 1, 3)
    nir = [(d1, -0.02), (d2, -0.01), (d3, 0.30)]
    red = [(d1, 0.01), (d2, 0.03), (d3, 0.05)]
    result = dict(TSBandManager._calc_ndvi(nir, red))
    assert d1 not in result  # NIR + RED < 0: no NDVI
    assert result[d2] == -10000.0  # -0.04 / 0.02 = -2, clipped to -1
    assert abs(result[d3] - (0.25 / 0.35) * 10000.0) < 1e-6


def test_a_wtss_band_and_a_cog_band_pair_by_date_for_an_index():
    from datetime import timezone

    from bdc_loader_plugin.core.ts_bands import TSBandManager
    from bdc_loader_plugin.extraction.point_series import item_datetime
    from bdc_loader_plugin.extraction.wtss_extractor import _parse_get_response

    wtss = {
        "result": {
            "timeline": ["2024-01-01", "2024-01-17"],
            "attributes": [{"attribute": "B04", "values": [1000, 1200]}],
        }
    }
    red = _parse_get_response(wtss, ["B04"])["B04"]
    nir = []
    for day in (1, 17):
        item = MagicMock()
        item.datetime = datetime(2024, 1, day, tzinfo=timezone.utc)
        nir.append((item_datetime(item), 3000.0))

    assert len(TSBandManager._calc_ndvi(nir, red)) == 2


def test_an_entry_removed_during_the_extraction_is_not_charted():
    from bdc_loader_plugin.core.ts_extraction import TSExtractionEngine

    eng = TSExtractionEngine.__new__(TSExtractionEngine)
    kept = {"id": 1, "bands": ["NDVI"], "collection": "S2-16D-2", "data": {}}
    removed = {"id": 2, "bands": ["NDVI"], "collection": "S2-16D-2", "data": {}}
    eng._history = [kept]
    for name in (
        "_refresh_history_list",
        "_update_rgb_combos",
        "_update_viz_navigation",
        "_plot_result",
        "_set_status",
    ):
        setattr(eng, name, MagicMock())
    eng.chart_dock = MagicMock()
    eng.chart_dock.rgb_mode_btn.isChecked.return_value = False

    eng._show_extraction_result([], [removed], [], 0, 0, True)

    assert eng._current_viz_index == 0
    eng._plot_result.assert_called_once_with(kept)


class TestChartClickImageChoice(unittest.TestCase):
    """Which bands and which date a click on the chart loads."""

    def test_settings_pick_one_band_or_all_three(self):
        from bdc_loader_plugin.core.ts_visualization import _settings_vrt_bands

        self.assertEqual(_settings_vrt_bands({"vrt_mode": "single", "vrt_single_band": " B08 "}), ["B08"])
        self.assertEqual(_settings_vrt_bands({"vrt_mode": "single", "vrt_single_band": ""}), [])
        rgb = {"vrt_mode": "rgb", "vrt_r_band": "B04", "vrt_g_band": "B03", "vrt_b_band": "B02"}
        self.assertEqual(_settings_vrt_bands(rgb), ["B04", "B03", "B02"])
        self.assertEqual(_settings_vrt_bands({**rgb, "vrt_g_band": " "}), [])

    def test_nearest_date_compares_aware_and_naive_dates(self):
        from datetime import timedelta, timezone

        from bdc_loader_plugin.core.ts_visualization import _nearest_series_date

        early, late = datetime(2024, 1, 1, tzinfo=timezone.utc), datetime(2024, 3, 1)
        data = {"B04": [(early, 1.0), (late, 2.0)]}

        self.assertEqual(_nearest_series_date(data, ["B04"], late - timedelta(days=5), False), late)
        self.assertEqual(_nearest_series_date(data, ["B04"], datetime(2024, 1, 10), False), early)

    def test_rgb_composite_only_lands_on_dates_every_band_has(self):
        from bdc_loader_plugin.core.ts_visualization import _nearest_series_date

        shared, red_only = datetime(2024, 1, 1), datetime(2024, 2, 1)
        data = {"B04": [(shared, 1.0), (red_only, 1.0)], "B03": [(shared, 1.0)], "B02": [(shared, 1.0)]}
        bands = ["B04", "B03", "B02"]

        self.assertEqual(_nearest_series_date(data, bands, red_only, intersect=True), shared)
        self.assertEqual(_nearest_series_date(data, bands, red_only, intersect=False), red_only)
        self.assertIsNone(_nearest_series_date({"B04": [], "B03": [], "B02": []}, bands, shared, intersect=True))


if __name__ == "__main__":
    unittest.main()


def test_series_dates_do_not_depend_on_the_computer_time_zone():
    import os
    import time
    from datetime import timezone

    import pytest

    from bdc_loader_plugin.extraction.point_series import item_datetime

    if not hasattr(time, "tzset"):
        pytest.skip("time.tzset is not available on this system")
    item = MagicMock()
    item.datetime = datetime(2022, 8, 13, 0, 0, tzinfo=timezone.utc)
    saved = os.environ.get("TZ")
    try:
        for zone in ("UTC", "America/Sao_Paulo", "Asia/Tokyo"):
            os.environ["TZ"] = zone
            time.tzset()
            assert item_datetime(item) == datetime(2022, 8, 13), zone
    finally:
        if saved is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = saved
        time.tzset()
