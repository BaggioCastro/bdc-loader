#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_vrt_builder.py — Tests for core/vrt_builder.py pure functions.

Covers: resolve_band, item-level band availability, VRT preflight validation,
        vrt_has_direct_remote_source, BAND_ALIASES.

Run: python3 -m pytest bdc_loader_plugin/tests/test_vrt_builder.py -v
"""

import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from bdc_loader_plugin.core import (
    cutline,
    layer_style,
    overview_cache,
    overviews,
    raster_export,
    render_ranges,
    vrt_overview_run,
    vrt_tasks,
)
from bdc_loader_plugin.tests.catalog_patch import patch_catalog
from bdc_loader_plugin.tests.pipeline_patch import patch_pipeline


class TestResolveBand(unittest.TestCase):
    """Tests for resolve_band — band name alias resolution."""

    def test_exact_match(self):
        from bdc_loader_plugin.core.band_selection import resolve_band

        assets = {"B01": {}, "B02": {}, "B03": {}}
        self.assertEqual(resolve_band("B01", assets), "B01")

    def test_alias_rgb_to_tci(self):
        from bdc_loader_plugin.core.band_selection import resolve_band

        assets = {"tci": {}, "B02": {}}
        self.assertEqual(resolve_band("rgb", assets), "tci")

    def test_alias_tci_to_visual(self):
        from bdc_loader_plugin.core.band_selection import resolve_band

        assets = {"visual": {}, "B02": {}}
        self.assertEqual(resolve_band("tci", assets), "visual")

    def test_case_insensitive_match(self):
        from bdc_loader_plugin.core.band_selection import resolve_band

        assets = {"B08": {}, "NDVI": {}}
        self.assertEqual(resolve_band("b08", assets), "B08")
        self.assertEqual(resolve_band("ndvi", assets), "NDVI")

    def test_not_found(self):
        from bdc_loader_plugin.core.band_selection import resolve_band

        assets = {"B01": {}, "B02": {}}
        self.assertIsNone(resolve_band("B99", assets))

    def test_empty_assets(self):
        from bdc_loader_plugin.core.band_selection import resolve_band

        self.assertIsNone(resolve_band("B01", {}))

    def test_exact_match_preferred_over_alias(self):
        """When both exact match and alias exist, exact wins."""
        from bdc_loader_plugin.core.band_selection import resolve_band

        assets = {"rgb": {}, "tci": {}}
        self.assertEqual(resolve_band("rgb", assets), "rgb")

    def test_case_insensitive_uppercase_query(self):
        from bdc_loader_plugin.core.band_selection import resolve_band

        assets = {"ndvi": {}}
        self.assertEqual(resolve_band("NDVI", assets), "ndvi")


class TestItemBandAvailability(unittest.TestCase):
    """Collection-level bands must be narrowed to assets in selected items."""

    CANDIDATES = [
        "Gamma0_HH",
        "Gamma0_HV",
        "Gamma0_VH",
        "Gamma0_VV",
        "layover_shadow_mask",
        "local_incidence_angle",
    ]
    DV_ITEM_ID = "S1A_IW_RTCH_1SDV_20260620_065050_0832F0_8892"
    DV_ASSETS = {
        "Gamma0_VH": {},
        "Gamma0_VV": {},
        "layover_shadow_mask": {},
        "local_incidence_angle": {},
        "thumbnail": {},
    }

    @staticmethod
    def _item(item_id, assets):
        return SimpleNamespace(id=item_id, assets=assets)

    def test_real_sentinel1_dv_item_only_offers_vh_and_vv(self):
        from bdc_loader_plugin.core.band_selection import available_bands_for_items

        item = self._item(self.DV_ITEM_ID, self.DV_ASSETS)
        result = available_bands_for_items(self.CANDIDATES, [item])

        self.assertEqual(
            result,
            ["Gamma0_VH", "Gamma0_VV", "layover_shadow_mask", "local_incidence_angle"],
        )

    def test_issue_reports_hh_as_missing_with_actual_item_assets(self):
        from bdc_loader_plugin.core.band_selection import band_availability_issues

        item = self._item(self.DV_ITEM_ID, self.DV_ASSETS)
        issues = band_availability_issues(["Gamma0_HH"], [item])

        self.assertEqual(
            issues,
            [
                (
                    self.DV_ITEM_ID,
                    ["Gamma0_HH"],
                    ["Gamma0_VH", "Gamma0_VV", "layover_shadow_mask", "local_incidence_angle"],
                )
            ],
        )

    def test_mixed_dv_and_dh_selection_has_no_common_polarization(self):
        from bdc_loader_plugin.core.band_selection import available_bands_for_items

        dv_item = self._item(self.DV_ITEM_ID, self.DV_ASSETS)
        dh_item = self._item("S1A_IW_RTCH_1SDH_example", {"Gamma0_HH": {}, "Gamma0_HV": {}})

        self.assertEqual(available_bands_for_items(self.CANDIDATES, [dv_item, dh_item]), [])

    def test_no_selected_items_keeps_collection_candidates(self):
        from bdc_loader_plugin.core.band_selection import available_bands_for_items

        self.assertEqual(available_bands_for_items(self.CANDIDATES, []), self.CANDIDATES)

    def test_unavailable_band_reasons_are_short(self):
        from bdc_loader_plugin.core.band_selection import unavailable_band_reasons

        item = self._item(self.DV_ITEM_ID, self.DV_ASSETS)
        reasons = unavailable_band_reasons(self.CANDIDATES, [item])

        self.assertEqual(
            reasons,
            {
                "Gamma0_HH": "Not available.",
                "Gamma0_HV": "Not available.",
            },
        )

    def test_grouped_mosaic_matches_builder_any_source_semantics(self):
        from bdc_loader_plugin.core.band_selection import available_bands_for_items

        source_without_vh = self._item("source-hh", {"Gamma0_HH": {}})
        source_with_vh = self._item("source-vh", {"Gamma0_VH": {}})
        mosaic = SimpleNamespace(
            id="shape_mosaic_2026-06-20",
            assets={},
            _source_items=[source_without_vh, source_with_vh],
        )

        self.assertEqual(available_bands_for_items(["Gamma0_VH"], [mosaic]), ["Gamma0_VH"])


class TestCatalogBandSynchronization(unittest.TestCase):
    """The picker must disable stale collection bands after item selection."""

    class _BandItem:
        def __init__(self, text):
            self._text = text
            self._data = None
            self._flags = 0x0001 | 0x0020
            self._foreground = None
            self._tooltip = ""

        def data(self, _role):
            return self._data

        def setData(self, _role, value):
            self._data = value

        def text(self):
            return self._text

        def flags(self):
            return self._flags

        def setFlags(self, flags):
            self._flags = flags

        def setForeground(self, foreground):
            self._foreground = foreground

        def setToolTip(self, tooltip):
            self._tooltip = tooltip

    class _BandList:
        def __init__(self, bands):
            self.items = []
            for band in bands:
                item = TestCatalogBandSynchronization._BandItem(band)
                item.setData(None, band)
                self.items.append(item)

        def count(self):
            return len(self.items)

        def item(self, row):
            return self.items[row]

        def clear(self):
            self.items.clear()

        def addItem(self, item):
            self.items.append(item)

        def setUpdatesEnabled(self, _enabled):
            pass

    def test_cached_collection_assets_disable_missing_bands_before_search(self):
        from bdc_loader_plugin.core.catalog import CatalogManager

        collection_id = "sentinel-1-rtc-1"
        dialog = SimpleNamespace(
            _results_fresh=True,
            _searched_params=None,
            _collection_asset_cache={
                collection_id: {
                    "Gamma0_VH",
                    "Gamma0_VV",
                    "layover_shadow_mask",
                    "local_incidence_angle",
                }
            },
        )

        reasons = CatalogManager._collection_band_reasons(
            dialog,
            collection_id,
            ["Gamma0_HH", "Gamma0_HV", "Gamma0_VH", "Gamma0_VV"],
        )

        self.assertEqual(
            reasons,
            {
                "Gamma0_HH": "Not available.",
                "Gamma0_HV": "Not available.",
            },
        )

    def test_bands_stay_usable_while_the_check_runs(self):
        from bdc_loader_plugin.core.catalog import CatalogManager

        dialog = SimpleNamespace(_results_fresh=True, _searched_params=None, _collection_asset_cache={})

        self.assertEqual(CatalogManager._collection_band_reasons(dialog, "new-collection", ["B02", "B03"]), {})

    def test_incomplete_scan_disables_nothing(self):
        """A band missing from the newest items may exist in older ones (Landsat lwir)."""
        from bdc_loader_plugin.core.catalog import CatalogManager
        from bdc_loader_plugin.stac.client import AssetNames

        names = AssetNames({"blue", "lwir11"})
        names.complete = False
        dialog = SimpleNamespace(
            _results_fresh=True, _searched_params=None, _collection_asset_cache={"landsat-2": names}
        )

        self.assertEqual(CatalogManager._collection_band_reasons(dialog, "landsat-2", ["blue", "lwir"]), {})

    def test_dv_selection_disables_hh_but_preserves_valid_selection(self):
        from bdc_loader_plugin.core.catalog import CatalogManager

        collection_name = "Sentinel-1 RTC Scenes"
        collection_id = "sentinel-1-rtc-1"
        collection_bands = [
            "Gamma0_HH",
            "Gamma0_HV",
            "Gamma0_VH",
            "Gamma0_VV",
            "layover_shadow_mask",
            "local_incidence_angle",
        ]
        item = SimpleNamespace(
            id="S1A_IW_RTCH_1SDV_20260620_065050_0832F0_8892",
            assets={
                "Gamma0_VH": {},
                "Gamma0_VV": {},
                "layover_shadow_mask": {},
                "local_incidence_angle": {},
                "thumbnail": {},
            },
        )
        combo = MagicMock()
        combo.currentIndex.return_value = 0
        combo.itemData.return_value = collection_name
        dialog = SimpleNamespace(
            _results_fresh=True,
            _searched_params=None,
            collection_combo=combo,
            selected_bands=self._BandList(["Gamma0_HH", "Gamma0_VH"]),
            get_selected_items=lambda: [item],
            _update_band_list=MagicMock(),
            _update_preset_list=MagicMock(),
            update_bands_status=MagicMock(),
        )
        dialog._current_collection_name = CatalogManager._current_collection_name.__get__(dialog)
        globals_data = (
            {collection_name: {"id": collection_id, "bands": collection_bands}},
            {collection_id: {}},
            {},
        )

        with (
            patch_catalog(*globals_data),
            patch("bdc_loader_plugin.core.catalog.QListWidgetItem", self._BandItem),
        ):
            CatalogManager._sync_bands_with_selected_items(dialog)

        dialog._update_band_list.assert_called_once()
        update_args = dialog._update_band_list.call_args.args
        self.assertEqual(update_args[0], collection_name)
        self.assertEqual(update_args[1], collection_bands)
        self.assertEqual(set(update_args[2]), {"Gamma0_HH", "Gamma0_HV"})
        retained = [entry.data(None) for entry in dialog.selected_bands.items]
        self.assertEqual(retained, ["Gamma0_VH"])

    def test_unavailable_band_is_grey_disabled_and_has_tooltip(self):
        from PyQt5.QtCore import Qt

        from bdc_loader_plugin.core.catalog import CatalogManager

        collection_name = "Sentinel-1 RTC Scenes"
        collection_id = "sentinel-1-rtc-1"
        available_list = self._BandList([])
        dialog = SimpleNamespace(_results_fresh=True, _searched_params=None, available_bands=available_list)
        globals_data = (
            {
                collection_name: {
                    "id": collection_id,
                    "bands": ["Gamma0_VV", "Gamma0_HH"],
                }
            },
            {collection_id: {}},
            {},
        )
        reason = "Unavailable for all current results."

        with (
            patch_catalog(*globals_data),
            patch("bdc_loader_plugin.core.catalog.QListWidgetItem", self._BandItem),
        ):
            CatalogManager._update_band_list(
                dialog,
                collection_name,
                ["Gamma0_VV", "Gamma0_HH"],
                {"Gamma0_HH": reason},
            )

        hh_item, vv_item = available_list.items
        self.assertEqual([item.data(Qt.UserRole) for item in available_list.items], ["Gamma0_HH", "Gamma0_VV"])
        self.assertFalse(hh_item.flags() & Qt.ItemIsEnabled)
        self.assertFalse(hh_item.flags() & Qt.ItemIsSelectable)
        self.assertIsNotNone(hh_item._foreground)
        self.assertEqual(hh_item._tooltip, reason)
        self.assertTrue(vv_item.flags() & Qt.ItemIsEnabled)
        self.assertEqual(vv_item._tooltip, "")

    def test_visible_results_define_availability_when_none_are_selected(self):
        from bdc_loader_plugin.core.catalog import CatalogManager

        collection_name = "Sentinel-1 RTC Scenes"
        collection_id = "sentinel-1-rtc-1"
        item = SimpleNamespace(id="visible-dv", assets={"Gamma0_VH": {}, "Gamma0_VV": {}})
        widget = SimpleNamespace(item=item, isVisible=lambda: True)
        combo = MagicMock()
        combo.currentIndex.return_value = 0
        combo.itemData.return_value = collection_name
        dialog = SimpleNamespace(
            _results_fresh=True,
            _searched_params=None,
            collection_combo=combo,
            selected_bands=self._BandList([]),
            result_widgets=[widget],
            get_selected_items=lambda: [],
            _update_band_list=MagicMock(),
            _update_preset_list=MagicMock(),
            update_bands_status=MagicMock(),
        )
        dialog._current_collection_name = CatalogManager._current_collection_name.__get__(dialog)
        collection_bands = ["Gamma0_HH", "Gamma0_HV", "Gamma0_VH", "Gamma0_VV"]
        globals_data = (
            {collection_name: {"id": collection_id, "bands": collection_bands}},
            {collection_id: {}},
            {},
        )

        with patch_catalog(*globals_data):
            CatalogManager._sync_bands_with_selected_items(dialog)

        reasons = dialog._update_band_list.call_args.args[2]
        self.assertEqual(set(reasons), {"Gamma0_HH", "Gamma0_HV"})
        dialog._update_preset_list.assert_called_once_with(collection_name, ["Gamma0_VH", "Gamma0_VV"])


def _bind_overview_steps(dialog):
    """Give a fake dialog the real steps _build_overviews calls on itself."""
    from bdc_loader_plugin.core.vrt_generator import VrtGenerator

    for name in ("_run_overview_jobs", "_record_overview", "_report_overview_outcome"):
        setattr(dialog, name, getattr(VrtGenerator, name).__get__(dialog))
    return dialog


def _bind_layer_steps(dialog):
    """Give a fake dialog the real steps _load_vrt_layers calls on itself."""
    from bdc_loader_plugin.core.vrt_generator import VrtGenerator

    for name in (
        "_ensure_layer_groups",
        "_retire_replaced_layers",
        "_open_new_layers",
        "_add_layers_to_groups",
        "_add_shape_masks",
        "_add_shape_mask",
    ):
        setattr(dialog, name, getattr(VrtGenerator, name).__get__(dialog))
    return dialog


def _bind_load_steps(dialog):
    """Give a fake dialog the real preflight steps generate_and_load calls on itself."""
    from bdc_loader_plugin.core.catalog import CatalogManager
    from bdc_loader_plugin.core.vrt_generator import VrtGenerator

    for name in ("_load_bands", "_bands_available", "_confirm_large_crop", "_load_collection", "_confirm_non_cog_load"):
        setattr(dialog, name, getattr(VrtGenerator, name).__get__(dialog))
    dialog._current_collection_name = CatalogManager._current_collection_name.__get__(dialog)
    dialog._results_match_panel = lambda: True
    return dialog


class TestVrtBandAvailabilityPreflight(unittest.TestCase):
    """Generation must fail before filesystem or GDAL work for stale UI state."""

    def test_unavailable_sentinel1_band_stops_before_output_creation(self):
        from bdc_loader_plugin.core.vrt_generator import VrtGenerator

        item = SimpleNamespace(
            id="S1A_IW_RTCH_1SDV_20260620_065050_0832F0_8892",
            assets={
                "Gamma0_VH": {},
                "Gamma0_VV": {},
                "layover_shadow_mask": {},
                "local_incidence_angle": {},
            },
        )
        selected_band = MagicMock()
        selected_band.data.return_value = "Gamma0_HH"
        selected_bands = MagicMock()
        selected_bands.count.return_value = 1
        selected_bands.item.return_value = selected_band
        dialog = _bind_load_steps(SimpleNamespace(get_selected_items=lambda: [item], selected_bands=selected_bands))

        with patch("bdc_loader_plugin.core.vrt_generator.QMessageBox.warning") as warning:
            VrtGenerator.generate_and_load(dialog)

        warning.assert_called_once()
        message = warning.call_args.args[2]
        self.assertIn(item.id, message)
        self.assertIn("Gamma0_HH", message)
        self.assertIn("Gamma0_VH", message)


class TestCalculateRenderRange(unittest.TestCase):
    """Contrast ranges must follow the sampled data, not a sensor-specific constant."""

    def test_float_radar_values_keep_small_dynamic_range(self):
        from bdc_loader_plugin.core.render_ranges import calculate_render_range

        values = [0.05 + index / 1000 for index in range(100)]
        low, high = calculate_render_range(values)
        self.assertGreater(low, 0)
        self.assertLess(high, 1)

    def test_reflectance_values_use_percentiles(self):
        from bdc_loader_plugin.core.render_ranges import calculate_render_range

        values = list(range(100, 10100, 100)) + [60000]
        low, high = calculate_render_range(values)
        self.assertGreaterEqual(low, 100)
        self.assertLess(high, 60000)

    def test_continuous_zero_background_is_ignored(self):
        from bdc_loader_plugin.core.render_ranges import calculate_render_range

        values = [0] * 30 + list(range(100, 200))
        low, high = calculate_render_range(values)
        self.assertGreaterEqual(low, 100)
        self.assertGreater(high, low)

    def test_categorical_zero_class_is_preserved(self):
        from bdc_loader_plugin.core.render_ranges import calculate_render_range

        self.assertEqual(calculate_render_range([0, 0, 1, 1, 2, 2]), (0.0, 2.0))

    def test_nodata_nan_and_infinity_are_excluded(self):
        from bdc_loader_plugin.core.render_ranges import calculate_render_range

        values = [-32768, float("nan"), float("inf"), 0.1, 0.2, 0.3]
        self.assertEqual(calculate_render_range(values, nodata=-32768), (0.1, 0.3))

    def test_constant_or_empty_sample_has_no_range(self):
        from bdc_loader_plugin.core.render_ranges import calculate_render_range

        self.assertIsNone(calculate_render_range([]))
        self.assertIsNone(calculate_render_range([4, 4, 4]))


class TestEstimateVrtRenderRanges(unittest.TestCase):
    def test_uses_local_overview_and_bounded_read(self):
        import bdc_loader_plugin.core.vrt_builder as module

        estimate_vrt_render_ranges = render_ranges.estimate_vrt_render_ranges
        gdal = module.gdal
        dataset = MagicMock()
        dataset.RasterXSize = 50000
        dataset.RasterYSize = 30000
        dataset.RasterCount = 1
        dataset.GetMetadataItem.return_value = overview_cache._OVERVIEW_VERSION
        band = MagicMock()
        band.GetNoDataValue.return_value = -32768
        band.ReadAsArray.return_value = [0.05 + index / 1000 for index in range(100)]
        dataset.GetRasterBand.return_value = band

        with tempfile.NamedTemporaryFile(suffix=".vrt", delete=False) as vrt:
            vrt_path = vrt.name
        with open(vrt_path + ".ovr", "w", encoding="utf-8"):
            pass

        original_open = gdal.Open
        open_mock = MagicMock(return_value=dataset)
        gdal.Open = open_mock
        try:
            ranges = estimate_vrt_render_ranges(vrt_path, sample_size=64)
        finally:
            gdal.Open = original_open
            os.unlink(vrt_path)
            os.unlink(vrt_path + ".ovr")

        # Two reads of the overview; the third opens the local VRT for its color
        # table, which the overview does not carry.
        self.assertEqual(open_mock.call_count, 3)
        open_mock.assert_has_calls(
            [unittest.mock.call(vrt_path + ".ovr", gdal.GA_ReadOnly)] * 2
            + [unittest.mock.call(vrt_path, gdal.GA_ReadOnly)]
        )
        band.ReadAsArray.assert_called_once_with(
            0,
            0,
            50000,
            30000,
            buf_xsize=64,
            buf_ysize=64,
        )
        self.assertIn(1, ranges)
        self.assertLess(ranges[1][1], 1)


class TestOverviewValidation(unittest.TestCase):
    @staticmethod
    def _dataset(dtype=6, nodata=-32768):
        dataset = MagicMock()
        dataset.RasterCount = 1
        dataset.RasterXSize = 4096
        dataset.RasterYSize = 2048
        band = MagicMock()
        band.DataType = dtype
        band.GetNoDataValue.return_value = nodata
        dataset.GetRasterBand.return_value = band
        return dataset

    @staticmethod
    def _signature(minimum, maximum, render_range, valid_count=100, nonzero_count=100):
        return {
            "valid_count": valid_count,
            "nonzero_count": nonzero_count,
            "minimum": minimum,
            "maximum": maximum,
            "render_range": render_range,
        }

    def _validate(self, source_signature, overview_signature):
        import bdc_loader_plugin.core.overviews as module

        source = self._dataset()
        overview = self._dataset()
        overview.RasterXSize = 512
        overview.RasterYSize = 256
        with (
            patch.object(module.gdal, "Open", side_effect=[source, overview]),
            patch.object(
                module,
                "_sample_band_signature",
                side_effect=[source_signature, overview_signature],
            ),
        ):
            return overviews._validate_overview("source.vrt", "source.vrt.ovr.tmp.tif")

    def test_accepts_comparable_dynamic_values(self):
        source = self._signature(-0.01, 0.5, (0.001, 0.08))
        overview = self._signature(-0.1, 2.7, (0.002, 0.09))

        self.assertEqual(self._validate(source, overview), (True, None))

    def test_rejects_zero_output_from_dynamic_source(self):
        source = self._signature(-0.01, 0.5, (0.001, 0.08))
        overview = self._signature(0.0, 0.0, None, nonzero_count=0)

        valid, reason = self._validate(source, overview)

        self.assertFalse(valid)
        self.assertIn("all zero", reason)

    def test_rejects_values_far_outside_source_scale(self):
        source = self._signature(-0.01, 0.5, (0.001, 0.08))
        overview = self._signature(-1e20, 1e30, (-1e20, 1e30))

        valid, reason = self._validate(source, overview)

        self.assertFalse(valid)
        self.assertIn("outside the source scale", reason)

    def test_accepts_matching_constant_zero_band(self):
        source = self._signature(0.0, 0.0, None, nonzero_count=0)
        overview = self._signature(0.0, 0.0, None, nonzero_count=0)

        self.assertEqual(self._validate(source, overview), (True, None))


class TestBuildOverview(unittest.TestCase):
    def test_uses_nearest_resampling_and_caps_largest_dimension(self):
        import bdc_loader_plugin.core.overviews as module

        gdal = module.gdal
        source_dataset = MagicMock()
        source_dataset.RasterXSize = 1535
        source_dataset.RasterYSize = 1000
        source_dataset.GetGeoTransform.return_value = (0, 10, 0, 0, 0, -10)
        output_dataset = MagicMock()
        metadata_dataset = MagicMock()

        with tempfile.NamedTemporaryFile(suffix=".vrt", delete=False) as vrt:
            vrt_path = vrt.name
        with (
            patch.object(gdal, "Open", side_effect=[source_dataset, metadata_dataset]),
            patch.object(gdal, "GA_Update", 1, create=True),
            patch.object(gdal, "Warp", return_value=output_dataset, create=True) as warp_mock,
            patch.object(gdal, "WarpOptions", return_value=MagicMock(), create=True) as options_mock,
            patch.object(module, "_validate_overview", return_value=(True, None)),
            patch.object(module.os, "replace") as replace_mock,
        ):
            try:
                result = overviews.build_overview(vrt_path)
            finally:
                os.unlink(vrt_path)

        self.assertEqual(result, vrt_path + ".ovr")
        options = options_mock.call_args.kwargs
        self.assertEqual(options["resampleAlg"], "nearest")
        self.assertEqual(options["xRes"], 30)
        self.assertEqual(options["yRes"], 30)
        self.assertFalse(any(value.startswith("PREDICTOR=") for value in options["creationOptions"]))
        warp_mock.assert_called_once_with(
            vrt_path + ".ovr.tmp.tif",
            vrt_path,
            options=options_mock.return_value,
        )
        metadata_dataset.SetMetadataItem.assert_any_call(
            overview_cache._OVERVIEW_METADATA_KEY,
            overview_cache._OVERVIEW_VERSION,
        )
        # The overview also records which VRT it was made from.
        self.assertEqual(
            [c.args[0] for c in metadata_dataset.SetMetadataItem.call_args_list],
            [overview_cache._OVERVIEW_METADATA_KEY, overview_cache._OVERVIEW_SOURCE_KEY],
        )
        output_dataset.FlushCache.assert_called_once_with()
        metadata_dataset.FlushCache.assert_called_once_with()
        replace_mock.assert_called_once_with(
            vrt_path + ".ovr.tmp.tif",
            vrt_path + ".ovr",
        )

    def test_replaces_unversioned_overview_before_opening_source(self):
        import bdc_loader_plugin.core.overviews as module

        gdal = module.gdal
        stale_dataset = MagicMock()
        stale_dataset.GetMetadataItem.return_value = None
        source_dataset = MagicMock()
        source_dataset.RasterXSize = 1535
        source_dataset.RasterYSize = 1000
        source_dataset.GetGeoTransform.return_value = (0, 10, 0, 0, 0, -10)
        output_dataset = MagicMock()
        metadata_dataset = MagicMock()

        with tempfile.NamedTemporaryFile(suffix=".vrt", delete=False) as vrt:
            vrt_path = vrt.name
        with open(vrt_path + ".ovr", "w", encoding="utf-8"):
            pass

        with (
            patch.object(gdal, "Open", side_effect=[stale_dataset, source_dataset, metadata_dataset]),
            patch.object(gdal, "GA_Update", 1, create=True),
            patch.object(gdal, "Warp", return_value=output_dataset, create=True) as warp_mock,
            patch.object(gdal, "WarpOptions", return_value=MagicMock(), create=True),
            patch.object(module, "_validate_overview", return_value=(True, None)),
            patch.object(module.os, "replace"),
        ):
            try:
                result = overviews.build_overview(vrt_path)
                self.assertFalse(os.path.exists(vrt_path + ".ovr"))
            finally:
                os.unlink(vrt_path)
                if os.path.exists(vrt_path + ".ovr"):
                    os.unlink(vrt_path + ".ovr")

        self.assertEqual(result, vrt_path + ".ovr")
        warp_mock.assert_called_once()

    def test_rejects_invalid_output_before_publishing(self):
        import bdc_loader_plugin.core.overviews as module

        gdal = module.gdal
        source_dataset = MagicMock()
        source_dataset.RasterXSize = 1535
        source_dataset.RasterYSize = 1000
        source_dataset.GetGeoTransform.return_value = (0, 10, 0, 0, 0, -10)
        output_dataset = MagicMock()

        with tempfile.NamedTemporaryFile(suffix=".vrt", delete=False) as vrt:
            vrt_path = vrt.name
        with (
            patch.object(gdal, "Open", return_value=source_dataset),
            patch.object(gdal, "Warp", return_value=output_dataset, create=True),
            patch.object(gdal, "WarpOptions", return_value=MagicMock(), create=True),
            patch.object(module, "_validate_overview", return_value=(False, "band 1 became all zero")),
            patch.object(module, "_log_warning") as warning_mock,
            patch.object(module.os, "replace") as replace_mock,
        ):
            try:
                result = overviews.build_overview(vrt_path)
            finally:
                os.unlink(vrt_path)

        self.assertIsNone(result)
        output_dataset.FlushCache.assert_called_once_with()
        replace_mock.assert_not_called()
        warning_mock.assert_called_once()


class TestBuildOverviewCutline(unittest.TestCase):
    """build_overview(vrt_path, cutline_path) — masked overview + safe fallback."""

    def _source_dataset(self):
        ds = MagicMock()
        ds.RasterXSize = 1535
        ds.RasterYSize = 1000
        ds.GetGeoTransform.return_value = (0, 10, 0, 0, 0, -10)
        return ds

    def test_masked_overview_passes_cutline_to_warp_options(self):
        import bdc_loader_plugin.core.overviews as module

        gdal = module.gdal
        source_dataset = self._source_dataset()
        check_dataset = MagicMock(RasterXSize=100, RasterYSize=100)
        metadata_dataset = MagicMock()
        warp_output = MagicMock()

        with tempfile.NamedTemporaryFile(suffix=".vrt", delete=False) as vrt:
            vrt_path = vrt.name
        with (
            patch.object(gdal, "Open", side_effect=[source_dataset, check_dataset, metadata_dataset]),
            patch.object(gdal, "GA_Update", 1, create=True),
            patch.object(gdal, "Warp", return_value=warp_output, create=True) as warp_mock,
            patch.object(gdal, "WarpOptions", return_value=MagicMock(), create=True) as options_mock,
            patch.object(module, "_cutline_in_raster_srs", return_value="/tmp/cut.geojson") as matcher_mock,
            patch.object(module, "_validate_overview") as validate_mock,
            patch.object(module.os, "replace"),
        ):
            try:
                result = overviews.build_overview(vrt_path, cutline_path="/tmp/cut.geojson")
            finally:
                os.unlink(vrt_path)

        self.assertEqual(result, vrt_path + ".ovr")
        warp_mock.assert_called_once()
        matcher_mock.assert_called_once_with("/tmp/cut.geojson", vrt_path)
        options = options_mock.call_args.kwargs
        self.assertEqual(options["cutlineDSName"], "/tmp/cut.geojson")
        self.assertNotIn("cutlineSRS", options)
        self.assertEqual(options["dstNodata"], 0)
        # Masking changes band stats on purpose — the strict statistical
        # validator would false-positive reject a correctly masked overview.
        validate_mock.assert_not_called()

    def test_cutline_failure_falls_back_to_unmasked_overview(self):
        import bdc_loader_plugin.core.overviews as module

        gdal = module.gdal
        source_dataset = self._source_dataset()
        metadata_dataset = MagicMock()
        warp_output = MagicMock()

        with tempfile.NamedTemporaryFile(suffix=".vrt", delete=False) as vrt:
            vrt_path = vrt.name
        with (
            patch.object(gdal, "Open", side_effect=[source_dataset, metadata_dataset]),
            patch.object(gdal, "GA_Update", 1, create=True),
            patch.object(
                gdal,
                "Warp",
                side_effect=[RuntimeError("PROJ: aea: Invalid latitude"), warp_output],
                create=True,
            ) as warp_mock,
            patch.object(gdal, "WarpOptions", return_value=MagicMock(), create=True),
            patch.object(module, "_cutline_in_raster_srs", return_value="/tmp/cut.geojson"),
            patch.object(module, "_validate_overview", return_value=(True, None)) as validate_mock,
            patch.object(module, "_log_warning") as warning_mock,
            patch.object(module.os, "replace"),
        ):
            try:
                result = overviews.build_overview(vrt_path, cutline_path="/tmp/cut.geojson")
            finally:
                os.unlink(vrt_path)

        self.assertEqual(result, vrt_path + ".ovr")
        self.assertEqual(warp_mock.call_count, 2)
        validate_mock.assert_called_once()
        self.assertTrue(
            any("falling back to bbox-only" in str(call) for call in warning_mock.call_args_list),
            warning_mock.call_args_list,
        )

    def test_reprojected_cutline_temp_file_is_cleaned_up(self):
        import bdc_loader_plugin.core.overviews as module

        gdal = module.gdal
        source_dataset = self._source_dataset()
        check_dataset = MagicMock(RasterXSize=100, RasterYSize=100)
        metadata_dataset = MagicMock()
        warp_output = MagicMock()

        with tempfile.NamedTemporaryFile(suffix=".vrt", delete=False) as vrt:
            vrt_path = vrt.name
        # A real file at the "reprojected cutline" path -- os.path.isfile must
        # stay real here (unmocked) so it doesn't also affect the unrelated
        # _overview_is_current() check at the top of build_overview.
        fd, reprojected_path = tempfile.mkstemp(suffix=".gpkg")
        os.close(fd)
        with (
            patch.object(gdal, "Open", side_effect=[source_dataset, check_dataset, metadata_dataset]),
            patch.object(gdal, "GA_Update", 1, create=True),
            patch.object(gdal, "Warp", return_value=warp_output, create=True),
            patch.object(gdal, "WarpOptions", return_value=MagicMock(), create=True),
            patch.object(module, "_cutline_in_raster_srs", return_value=reprojected_path),
            patch.object(module, "_validate_overview"),
            patch.object(module.os, "replace"),
        ):
            try:
                overviews.build_overview(vrt_path, cutline_path="/tmp/cut.geojson")
            finally:
                os.unlink(vrt_path)
                if os.path.exists(reprojected_path):
                    os.remove(reprojected_path)
                    self.fail("reprojected cutline temp file was not cleaned up")


class TestEstimateTileFetchFraction(unittest.TestCase):
    """estimate_tile_fetch_fraction — bbox-vs-bbox overlap estimate used to
    decide between a windowed remote read and a full parallel prefetch."""

    def test_full_overlap_returns_one(self):
        from bdc_loader_plugin.core.cutline import estimate_tile_fetch_fraction

        item_bbox = (-50.0, -20.0, -49.0, -19.0)
        cutline_bbox = (-51.0, -21.0, -48.0, -18.0)  # fully contains the tile
        self.assertEqual(estimate_tile_fetch_fraction(item_bbox, cutline_bbox), 1.0)

    def test_no_overlap_returns_zero(self):
        from bdc_loader_plugin.core.cutline import estimate_tile_fetch_fraction

        item_bbox = (-50.0, -20.0, -49.0, -19.0)
        cutline_bbox = (-40.0, -10.0, -39.0, -9.0)
        self.assertEqual(estimate_tile_fetch_fraction(item_bbox, cutline_bbox), 0.0)

    def test_partial_overlap_returns_fraction_of_item_area(self):
        from bdc_loader_plugin.core.cutline import estimate_tile_fetch_fraction

        item_bbox = (0.0, 0.0, 10.0, 10.0)  # 100 sq deg
        cutline_bbox = (5.0, 0.0, 15.0, 10.0)  # overlaps the right half -> 50 sq deg
        self.assertAlmostEqual(estimate_tile_fetch_fraction(item_bbox, cutline_bbox), 0.5)

    def test_missing_bbox_defaults_to_full_fetch(self):
        from bdc_loader_plugin.core.cutline import estimate_tile_fetch_fraction

        self.assertEqual(estimate_tile_fetch_fraction(None, (0, 0, 1, 1)), 1.0)
        self.assertEqual(estimate_tile_fetch_fraction((0, 0, 1, 1), None), 1.0)


class TestCutlineWgs84Bbox(unittest.TestCase):
    def test_returns_none_for_unreadable_cutline(self):
        import bdc_loader_plugin.core.cutline as module
        from bdc_loader_plugin.core.cutline import cutline_wgs84_bbox

        with patch.object(module.ogr, "Open", return_value=None, create=True):
            result = cutline_wgs84_bbox("/tmp/missing.geojson")

        self.assertIsNone(result)

    def test_reorders_layer_extent_into_xmin_ymin_xmax_ymax(self):
        import bdc_loader_plugin.core.cutline as module
        from bdc_loader_plugin.core.cutline import cutline_wgs84_bbox

        layer = MagicMock()
        layer.GetExtent.return_value = (-50.0, -49.0, -20.0, -19.0)  # xmin, xmax, ymin, ymax
        cut_ds = MagicMock()
        cut_ds.GetLayer.return_value = layer

        with patch.object(module.ogr, "Open", return_value=cut_ds, create=True):
            result = cutline_wgs84_bbox("/tmp/cut.geojson")

        self.assertEqual(result, (-50.0, -20.0, -49.0, -19.0))


class TestCutlineInRasterSRS(unittest.TestCase):
    """_cutline_in_raster_srs — replaces the cutlineSRS kwarg (not available in
    every GDAL Python binding version) by reprojecting the cutline itself."""

    def test_unreadable_cutline_returns_original_path(self):
        with patch.object(cutline.ogr, "Open", return_value=None, create=True):
            result = cutline._cutline_in_raster_srs("/tmp/cut.geojson", "/tmp/raster.vrt")

        self.assertEqual(result, "/tmp/cut.geojson")

    def test_unreadable_raster_returns_original_cutline_path(self):
        cut_ds = MagicMock()
        with (
            patch.object(cutline.ogr, "Open", return_value=cut_ds, create=True),
            patch.object(cutline.gdal, "Open", return_value=None),
        ):
            result = cutline._cutline_in_raster_srs("/tmp/cut.geojson", "/tmp/raster.vrt")

        self.assertEqual(result, "/tmp/cut.geojson")


class TestCutlineForGroup(unittest.TestCase):
    """VrtGenerator._cutline_for_group — exact group match with fallback."""

    def test_returns_the_cutline_recorded_for_the_group(self):
        from bdc_loader_plugin.core.vrt_generator import VrtGenerator

        dialog = SimpleNamespace(
            _cached_cutline_path="/tmp/merged.geojson",
            _group_cutlines={"S2-16D-2 / Sao-Paulo-abc123": "/tmp/feat_sao_paulo.geojson"},
        )
        result = VrtGenerator._cutline_for_group(dialog, "S2-16D-2 / Sao-Paulo-abc123")
        self.assertEqual(result, "/tmp/feat_sao_paulo.geojson")

    def test_a_group_whose_name_merely_contains_another_is_not_matched(self):
        """ "A" must not pick the cutline of "A-2"; only exact group names match."""
        from bdc_loader_plugin.core.vrt_generator import VrtGenerator

        dialog = SimpleNamespace(
            _cached_cutline_path="/tmp/merged.geojson",
            _group_cutlines={"S2-16D-2 / A-2-abc123": "/tmp/a2.geojson"},
        )
        self.assertEqual(VrtGenerator._cutline_for_group(dialog, "S2-16D-2 / A-abc123"), "/tmp/merged.geojson")

    def test_falls_back_to_cached_cutline_when_no_group_matches(self):
        from bdc_loader_plugin.core.vrt_generator import VrtGenerator

        dialog = SimpleNamespace(_cached_cutline_path="/tmp/merged.geojson", _group_cutlines={})
        result = VrtGenerator._cutline_for_group(dialog, "S2-16D-2 / Crop 2024-01-01")
        self.assertEqual(result, "/tmp/merged.geojson")

    def test_returns_none_for_regular_non_shape_search(self):
        from bdc_loader_plugin.core.vrt_generator import VrtGenerator

        dialog = SimpleNamespace(_cached_cutline_path=None, _group_cutlines={})
        result = VrtGenerator._cutline_for_group(dialog, "S2-16D-2 / 031021")
        self.assertIsNone(result)


class TestPrepareVrtTasksLocalDownload(unittest.TestCase):
    """_prepare_vrt_tasks must reference an already-downloaded crop/feature
    file (multiband GeoTIFF, VRT over per-band files, or the single band file)
    instead of rebuilding a VRT from the source tiles."""

    AREA = "Sao-Paulo-abc123"

    def setUp(self):
        self.download_dir = tempfile.mkdtemp(prefix="bdc_test_vrtgen_")
        self.addCleanup(shutil.rmtree, self.download_dir, ignore_errors=True)
        patcher = patch(
            "bdc_loader_plugin.core.output_crs.build_options",
            return_value=[SimpleNamespace(tag=""), SimpleNamespace(tag="epsg4326")],
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _mosaic_item(self, date="2024-01-01", area=AREA, is_extent_crop=False):
        return SimpleNamespace(
            id=f"{area}_{date}",
            datetime=SimpleNamespace(strftime=lambda fmt: date),
            properties={
                "bdc:is_shape_mosaic": True,
                "bdc:is_extent_crop": is_extent_crop,
                "bdc:feature_name": "Sao Paulo",
                "bdc:area_tag": area,
                "bdc:mosaic_date": date,
            },
            _source_items=[],
        )

    def _dialog(self):
        dialog = SimpleNamespace(
            output_dir=SimpleNamespace(text=lambda: self.download_dir),
            _download_dir=self.download_dir,
            _get_shape_cutline_geometry=MagicMock(return_value=None),
            _get_extent_cutline=MagicMock(return_value=None),
            _cutline_for_item=MagicMock(return_value="/tmp/feat_cutline.geojson"),
            shape_merge_check=SimpleNamespace(isChecked=lambda: False),
            _current_result_mode="shape_mosaic",
            _tile_filter_dict={},
            _build_single_band_task=MagicMock(
                return_value={"vrt_path": "irrelevant", "group_name": f"S2-16D-2 / {self.AREA}"}
            ),
            _build_rgb_task=MagicMock(return_value={"vrt_path": "irrelevant", "group_name": f"S2-16D-2 / {self.AREA}"}),
        )
        from bdc_loader_plugin.core.vrt_generator import VrtGenerator

        for name in ("_crop_checked_tiles", "_register_area", "_composition_task"):
            setattr(dialog, name, getattr(VrtGenerator, name).__get__(dialog))
        return dialog

    def _write(self, date, bands, fmt, tag=""):
        from bdc_loader_plugin.core.download_outputs import area_outputs

        plan = area_outputs(self.download_dir, "S2-16D-2", self.AREA, date, bands, fmt, tag)
        for path in plan.paths():
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(b"fake")
        return plan

    def test_uses_the_downloaded_band_file_directly(self):
        from bdc_loader_plugin.core.vrt_generator import VrtGenerator

        plan = self._write("2024-01-01", ["B04"], "per_band")
        dialog = self._dialog()
        vrt_tasks, prebuilt_layers = VrtGenerator._prepare_vrt_tasks(
            dialog, [self._mosaic_item()], ["B04"], 1, "B04", "S2-16D-2", False, "stac", []
        )

        self.assertEqual(vrt_tasks, [])
        path, _layer_name, group_name = prebuilt_layers[0]
        self.assertEqual(path, plan.band_files[0][1])
        self.assertEqual(group_name, f"S2-16D-2 / {self.AREA}")
        dialog._build_single_band_task.assert_not_called()

    def test_uses_a_reprojected_vrt_over_per_band_files(self):
        from bdc_loader_plugin.core.vrt_generator import VrtGenerator

        plan = self._write("2024-01-01", ["B04", "B03", "B02"], "per_band_vrt", "epsg4326")
        _tasks, prebuilt_layers = VrtGenerator._prepare_vrt_tasks(
            self._dialog(),
            [self._mosaic_item()],
            ["B04", "B03", "B02"],
            3,
            "B04-B03-B02",
            "S2-16D-2",
            False,
            "stac",
            [],
        )

        self.assertEqual(prebuilt_layers[0][0], plan.vrt)

    def test_builds_normal_task_when_nothing_was_downloaded(self):
        from bdc_loader_plugin.core.vrt_generator import VrtGenerator

        dialog = self._dialog()
        vrt_tasks, prebuilt_layers = VrtGenerator._prepare_vrt_tasks(
            dialog, [self._mosaic_item()], ["B04"], 1, "B04", "S2-16D-2", False, "stac", []
        )

        self.assertEqual(prebuilt_layers, [])
        self.assertEqual(len(vrt_tasks), 1)
        self.assertEqual(dialog._build_single_band_task.call_args.args[10], "/tmp/feat_cutline.geojson")

    def test_feature_crop_is_cut_by_a_mask_band(self):
        from bdc_loader_plugin.core.vrt_generator import VrtGenerator

        vrt_tasks, _prebuilt = VrtGenerator._prepare_vrt_tasks(
            self._dialog(), [self._mosaic_item()], ["B04"], 1, "B04", "S2-16D-2", False, "stac", []
        )

        self.assertEqual(vrt_tasks[0].get("area_mask"), "/tmp/feat_cutline.geojson")

    def test_extent_crop_gets_no_mask_band(self):
        # The box is cut as a straight rectangle of the grid; a mask along the
        # lon/lat box would put stair-stepped corners back.
        from bdc_loader_plugin.core.vrt_generator import VrtGenerator

        dialog = self._dialog()
        dialog._current_result_mode = "extent_crop"
        vrt_tasks, _prebuilt = VrtGenerator._prepare_vrt_tasks(
            dialog,
            [self._mosaic_item(area="crop-x", is_extent_crop=True)],
            ["B04"],
            1,
            "B04",
            "S2-16D-2",
            False,
            "stac",
            [],
        )

        self.assertNotIn("area_mask", vrt_tasks[0])

    def test_extent_crop_dates_share_one_spatial_group(self):
        from bdc_loader_plugin.core.vrt_generator import VrtGenerator

        area = "crop-23.35S-45.55W-0f1e2d"
        dialog = self._dialog()
        dialog._current_result_mode = "extent_crop"
        VrtGenerator._prepare_vrt_tasks(
            dialog,
            [
                self._mosaic_item("2026-06-20", area, is_extent_crop=True),
                self._mosaic_item("2026-06-21", area, is_extent_crop=True),
            ],
            ["Gamma0_VH"],
            1,
            "Gamma0_VH",
            "sentinel-1-rtc-1",
            False,
            "stac",
            [],
        )

        group_names = [call.args[11] for call in dialog._build_single_band_task.call_args_list]
        self.assertEqual(group_names, [f"sentinel-1-rtc-1 / {area}"] * 2)
        # The tasks still clip to the box, but the overview of an extent crop
        # is not masked: it shows the same straight rectangle as full resolution.
        self.assertEqual(dialog._build_single_band_task.call_args.args[10], "/tmp/feat_cutline.geojson")
        self.assertEqual(dialog._group_cutlines, {f"sentinel-1-rtc-1 / {area}": None})

    def test_mixed_group_serves_a_cached_date_and_a_fresh_one(self):
        from bdc_loader_plugin.core.vrt_generator import VrtGenerator

        self._write("2024-01-01", ["B04"], "per_band")
        dialog = self._dialog()
        vrt_tasks, prebuilt_layers = VrtGenerator._prepare_vrt_tasks(
            dialog,
            [self._mosaic_item("2024-01-01"), self._mosaic_item("2024-02-01")],
            ["B04"],
            1,
            "B04",
            "S2-16D-2",
            False,
            "stac",
            [],
        )

        self.assertEqual(len(prebuilt_layers), 1)
        self.assertEqual(len(vrt_tasks), 1)
        self.assertEqual(prebuilt_layers[0][2], f"S2-16D-2 / {self.AREA}")
        self.assertEqual(vrt_tasks[0]["group_name"], f"S2-16D-2 / {self.AREA}")


class TestLoadVrtLayersMask(unittest.TestCase):
    """_load_vrt_layers's vector mask overlay: a shape mosaic's cutline is an
    irregular polygon inside the raster's bbox, so the mask visibly hides the
    area outside the shape. An extent-crop's cutline IS the raster's exact
    bbox, so the same mask would have nothing to hide -- it must be skipped."""

    def _dialog(self, result_mode):
        root = MagicMock()
        root.findGroup.return_value = None
        group = MagicMock()
        root.insertGroup.return_value = group

        project = MagicMock()
        project.mapLayers.return_value = {}
        project.layerTreeRoot.return_value = root

        canvas = MagicMock()
        iface = MagicMock()
        iface.mapCanvas.return_value = canvas

        layer = MagicMock()
        layer.isValid.return_value = True
        layer.name.return_value = "layer1"

        return SimpleNamespace(
            _set_status=MagicMock(),
            iface=iface,
            auto_select_check=SimpleNamespace(isChecked=lambda: True),
            _current_result_mode=result_mode,
            _create_raster_layer=MagicMock(return_value=layer),
            _open_raster_layers=lambda jobs: {vrt_path: layer for vrt_path, _name in jobs},
            _cutline_for_group=MagicMock(return_value="/tmp/cutline.geojson"),
            _timeline_toolbar=None,
        ), project

    def test_shape_mosaic_gets_a_mask_layer(self):
        import bdc_loader_plugin.core.vrt_generator as module

        dialog, project = self._dialog("shape_mosaic")
        vrt_paths = [("/tmp/out.vrt", "layer1", "S2-16D-2 / Sao_Paulo")]

        with (
            patch_pipeline("QgsProject", project),
            patch_pipeline("QgsVectorLayer") as vector_layer_cls,
            patch_pipeline("QgsFillSymbol"),
            patch_pipeline("QgsSingleSymbolRenderer"),
            patch_pipeline("QgsInvertedPolygonRenderer"),
        ):
            vector_layer_cls.return_value.isValid.return_value = True
            module.VrtGenerator._load_vrt_layers(_bind_layer_steps(dialog), vrt_paths)

        vector_layer_cls.assert_called_once()

    def test_extent_crop_gets_no_mask_layer(self):
        import bdc_loader_plugin.core.vrt_generator as module

        dialog, project = self._dialog("extent_crop")
        vrt_paths = [("/tmp/out.vrt", "layer1", "S2-16D-2 / Crop 2026-06-10")]

        with (
            patch_pipeline("QgsProject", project),
            patch_pipeline("QgsVectorLayer") as vector_layer_cls,
            patch_pipeline("QgsFillSymbol"),
            patch_pipeline("QgsSingleSymbolRenderer"),
            patch_pipeline("QgsInvertedPolygonRenderer"),
        ):
            vector_layer_cls.return_value.isValid.return_value = True
            module.VrtGenerator._load_vrt_layers(_bind_layer_steps(dialog), vrt_paths)

        vector_layer_cls.assert_not_called()


class TestResolveMaskTargetGroup(unittest.TestCase):
    """_resolve_mask_target_group decides where a shape mask goes when its
    expected group is or isn't in the cache. The expected-group-missing case
    must fall back to the project root with a warning flag, never silently to an
    unrelated group."""

    def test_returns_expected_group_when_present(self):
        from bdc_loader_plugin.core.vrt_layers import _resolve_mask_target_group

        expected = object()
        root = object()
        cache = {"grp": expected}

        node, missing = _resolve_mask_target_group(cache, "grp", root)

        self.assertIs(node, expected)
        self.assertFalse(missing)

    def test_missing_group_falls_back_to_root_not_another_group(self):
        from bdc_loader_plugin.core.vrt_layers import _resolve_mask_target_group

        other = object()  # a real but semantically wrong group
        root = object()
        cache = {"some_other_group": other}

        node, missing = _resolve_mask_target_group(cache, "expected_group", root)

        # Not the first cached group: the mask goes to root, and the miss is flagged.
        self.assertIs(node, root)
        self.assertIsNot(node, other)
        self.assertTrue(missing)

    def test_missing_group_with_empty_cache_falls_back_to_root(self):
        from bdc_loader_plugin.core.vrt_layers import _resolve_mask_target_group

        root = object()

        node, missing = _resolve_mask_target_group({}, "expected_group", root)

        self.assertIs(node, root)
        self.assertTrue(missing)


class TestExportMaskedGeotiff(unittest.TestCase):
    """export_masked_geotiff — real cutline Warp for the opt-in export path.

    These exercise a real temp directory with a fake gdal.Warp that actually
    writes bytes to the path it is handed, so the atomic ``.part`` -> os.replace
    contract is observed on the filesystem, not just via mock call assertions.
    """

    def setUp(self):
        self.work_dir = tempfile.mkdtemp(prefix="bdc_test_export_")
        self.addCleanup(shutil.rmtree, self.work_dir, ignore_errors=True)
        self.src = os.path.join(self.work_dir, "src.vrt")
        self.cut = os.path.join(self.work_dir, "cut.geojson")
        self.dst = os.path.join(self.work_dir, "out.tif")
        self.part = self.dst + ".part"

    def _fake_warp(self, raster_size=(100, 100), payload=b"GTIFF-DATA", fail=False, returns_none=False):
        """A gdal.Warp stand-in that writes real bytes to the destination path
        it receives (the ``.part`` temp), mirroring how GDAL materializes
        output before this function commits it with os.replace."""

        def _warp(dst, src, options=None):
            with open(dst, "wb") as f:
                f.write(payload)
            if fail:
                raise RuntimeError("boom")
            if returns_none:
                return None
            ds = MagicMock()
            ds.RasterXSize, ds.RasterYSize = raster_size
            return ds

        return _warp

    def test_success_creates_final_file_and_removes_temp(self):
        import bdc_loader_plugin.core.raster_export as module

        gdal = module.gdal
        with (
            patch.object(gdal, "Warp", side_effect=self._fake_warp(), create=True) as warp_mock,
            patch.object(gdal, "WarpOptions", return_value=MagicMock(), create=True) as options_mock,
            patch.object(module, "_cutline_in_raster_srs", return_value=self.cut) as matcher_mock,
        ):
            ok, result = raster_export.export_masked_geotiff(self.src, self.cut, self.dst)

        self.assertTrue(ok)
        self.assertEqual(result, self.dst)
        # The final file exists; the temp was consumed by os.replace.
        self.assertTrue(os.path.isfile(self.dst))
        self.assertFalse(os.path.exists(self.part))
        matcher_mock.assert_called_once_with(self.cut, self.src)
        # Warp writes to the .part temp, never straight to the final path.
        warp_dst = warp_mock.call_args.args[0]
        self.assertEqual(warp_dst, self.part)
        options = options_mock.call_args.kwargs
        self.assertEqual(options["cutlineDSName"], self.cut)
        self.assertNotIn("cutlineSRS", options)
        self.assertTrue(options["cropToCutline"])
        self.assertEqual(options["dstNodata"], 0)

    def test_large_output_gets_internal_overviews(self):
        import bdc_loader_plugin.core.raster_export as module

        gdal = module.gdal
        warp = self._fake_warp(raster_size=(4096, 4096))
        captured = {}

        def _warp(dst, src, options=None):
            ds = warp(dst, src, options)
            captured["ds"] = ds
            return ds

        with (
            patch.object(gdal, "Warp", side_effect=_warp, create=True),
            patch.object(gdal, "WarpOptions", return_value=MagicMock(), create=True),
            patch.object(module, "_cutline_in_raster_srs", return_value=self.cut),
        ):
            ok, result = raster_export.export_masked_geotiff(self.src, self.cut, self.dst)

        self.assertTrue(ok)
        self.assertTrue(os.path.isfile(self.dst))
        captured["ds"].BuildOverviews.assert_called_once()
        alg, levels = captured["ds"].BuildOverviews.call_args.args
        self.assertEqual(alg, "NEAREST")
        self.assertEqual(levels, [2, 4, 8])

    def test_reprojected_cutline_temp_file_is_cleaned_up(self):
        import bdc_loader_plugin.core.raster_export as module

        gdal = module.gdal
        reprojected = os.path.join(self.work_dir, "cut_reprojected.gpkg")
        with open(reprojected, "wb") as f:
            f.write(b"reprojected cutline")

        with (
            patch.object(gdal, "Warp", side_effect=self._fake_warp(), create=True),
            patch.object(gdal, "WarpOptions", return_value=MagicMock(), create=True),
            patch.object(module, "_cutline_in_raster_srs", return_value=reprojected),
        ):
            raster_export.export_masked_geotiff(self.src, self.cut, self.dst)

        # The reprojected cutline temp (distinct from the caller's cutline) is removed.
        self.assertFalse(os.path.exists(reprojected))
        self.assertTrue(os.path.isfile(self.dst))

    def test_warp_returning_none_reports_failure_and_leaves_no_final(self):
        import bdc_loader_plugin.core.raster_export as module

        gdal = module.gdal
        with (
            patch.object(gdal, "Warp", side_effect=self._fake_warp(returns_none=True), create=True),
            patch.object(gdal, "WarpOptions", return_value=MagicMock(), create=True),
            patch.object(module, "_cutline_in_raster_srs", return_value=self.cut),
        ):
            ok, result = raster_export.export_masked_geotiff(self.src, self.cut, self.dst)

        self.assertFalse(ok)
        self.assertIn("no dataset", result)
        # Warp wrote a partial temp; it must be cleaned up and never promoted.
        self.assertFalse(os.path.exists(self.dst))
        self.assertFalse(os.path.exists(self.part))

    def test_exception_is_caught_and_reported_and_temp_removed(self):
        import bdc_loader_plugin.core.raster_export as module

        gdal = module.gdal
        with (
            patch.object(gdal, "Warp", side_effect=self._fake_warp(fail=True), create=True),
            patch.object(gdal, "WarpOptions", return_value=MagicMock(), create=True),
            patch.object(module, "_cutline_in_raster_srs", return_value=self.cut),
            patch.object(module, "_log_error"),
        ):
            ok, result = raster_export.export_masked_geotiff(self.src, self.cut, self.dst)

        self.assertFalse(ok)
        self.assertEqual(result, "boom")
        # A failure after writing part of the temp leaves no final file behind.
        self.assertFalse(os.path.exists(self.dst))
        self.assertFalse(os.path.exists(self.part))

    def test_cancelled_export_leaves_no_final_and_removes_temp(self):
        import bdc_loader_plugin.core.raster_export as module

        gdal = module.gdal
        with (
            patch.object(gdal, "Warp", side_effect=self._fake_warp(), create=True),
            patch.object(gdal, "WarpOptions", return_value=MagicMock(), create=True),
            patch.object(module, "_cutline_in_raster_srs", return_value=self.cut),
        ):
            ok, result = raster_export.export_masked_geotiff(self.src, self.cut, self.dst, cancel_check=lambda: True)

        self.assertFalse(ok)
        self.assertFalse(os.path.exists(self.dst))
        self.assertFalse(os.path.exists(self.part))

    def test_partial_temp_alone_does_not_count_as_downloaded(self):
        """A leftover ``.part`` from an interrupted run must not make the
        caller's os.path.isfile(dst) "already downloaded" check pass."""
        with open(self.part, "wb") as f:
            f.write(b"leftover partial")

        self.assertFalse(os.path.isfile(self.dst))

    def test_retry_after_failure_succeeds(self):
        import bdc_loader_plugin.core.raster_export as module

        gdal = module.gdal
        # First attempt fails mid-write.
        with (
            patch.object(gdal, "Warp", side_effect=self._fake_warp(fail=True), create=True),
            patch.object(gdal, "WarpOptions", return_value=MagicMock(), create=True),
            patch.object(module, "_cutline_in_raster_srs", return_value=self.cut),
            patch.object(module, "_log_error"),
        ):
            ok1, _ = raster_export.export_masked_geotiff(self.src, self.cut, self.dst)
        self.assertFalse(ok1)
        self.assertFalse(os.path.exists(self.dst))

        # A second attempt with a working Warp must be allowed and succeed.
        with (
            patch.object(gdal, "Warp", side_effect=self._fake_warp(), create=True),
            patch.object(gdal, "WarpOptions", return_value=MagicMock(), create=True),
            patch.object(module, "_cutline_in_raster_srs", return_value=self.cut),
        ):
            ok2, result = raster_export.export_masked_geotiff(self.src, self.cut, self.dst)

        self.assertTrue(ok2)
        self.assertEqual(result, self.dst)
        self.assertTrue(os.path.isfile(self.dst))
        self.assertFalse(os.path.exists(self.part))

    def test_existing_valid_final_is_replaced_only_after_new_file_ready(self):
        """A pre-existing valid dst is left intact if the new export fails, and
        is atomically replaced (not truncated in place) when it succeeds."""
        import bdc_loader_plugin.core.raster_export as module

        with open(self.dst, "wb") as f:
            f.write(b"OLD-VALID-CONTENT")

        gdal = module.gdal
        # Failing re-export must not damage the existing final file.
        with (
            patch.object(gdal, "Warp", side_effect=self._fake_warp(fail=True), create=True),
            patch.object(gdal, "WarpOptions", return_value=MagicMock(), create=True),
            patch.object(module, "_cutline_in_raster_srs", return_value=self.cut),
            patch.object(module, "_log_error"),
        ):
            ok, _ = raster_export.export_masked_geotiff(self.src, self.cut, self.dst)
        self.assertFalse(ok)
        with open(self.dst, "rb") as f:
            self.assertEqual(f.read(), b"OLD-VALID-CONTENT")

        # Succeeding re-export replaces it with the new content.
        with (
            patch.object(gdal, "Warp", side_effect=self._fake_warp(payload=b"NEW-CONTENT"), create=True),
            patch.object(gdal, "WarpOptions", return_value=MagicMock(), create=True),
            patch.object(module, "_cutline_in_raster_srs", return_value=self.cut),
        ):
            ok, _ = raster_export.export_masked_geotiff(self.src, self.cut, self.dst)
        self.assertTrue(ok)
        with open(self.dst, "rb") as f:
            self.assertEqual(f.read(), b"NEW-CONTENT")


class TestExportMaskedGeotiffOutputOptions(unittest.TestCase):
    """The output projection rides on the same single gdal.Warp the crop
    already runs, and the cutline keeps the pixels the boundary crosses."""

    def setUp(self):
        self.work_dir = tempfile.mkdtemp(prefix="bdc_test_export_opts_")
        self.addCleanup(shutil.rmtree, self.work_dir, ignore_errors=True)
        self.src = os.path.join(self.work_dir, "src.vrt")
        self.cut = os.path.join(self.work_dir, "cut.geojson")
        self.dst = os.path.join(self.work_dir, "out.tif")

    def _warp_kwargs(self, **export_kwargs):
        """Run the export with a Warp that writes bytes, and return the
        keyword arguments gdal.WarpOptions was built from."""
        import bdc_loader_plugin.core.raster_export as module

        def _warp(dst, src, options=None):
            with open(dst, "wb") as f:
                f.write(b"GTIFF-DATA")
            ds = MagicMock()
            ds.RasterXSize = ds.RasterYSize = 100
            return ds

        gdal = module.gdal
        with (
            patch.object(gdal, "Warp", side_effect=_warp, create=True),
            patch.object(gdal, "WarpOptions", return_value=MagicMock(), create=True) as options_mock,
            patch.object(module, "_cutline_in_raster_srs", return_value=self.cut),
            patch.object(module, "_effective_dst_srs", side_effect=lambda srs, _src: srs),
        ):
            ok, result = raster_export.export_masked_geotiff(self.src, self.cut, self.dst, **export_kwargs)
        self.assertTrue(ok, msg=result)
        return options_mock.call_args.kwargs

    def test_native_output_adds_no_reprojection(self):
        """Without a projection request the export is the plain hard cutline
        mask — no dstSRS, no resampling, no extra band."""
        kwargs = self._warp_kwargs()

        self.assertNotIn("dstSRS", kwargs)
        self.assertNotIn("resampleAlg", kwargs)
        self.assertNotIn("dstAlpha", kwargs)
        self.assertEqual(kwargs["dstNodata"], 0)
        self.assertTrue(kwargs["cropToCutline"])

    def test_cutline_keeps_the_pixels_the_boundary_crosses(self):
        """A centre-based mask drops pixels the boundary only clips, which
        renders as transparent notches inside the shape overlay."""
        kwargs = self._warp_kwargs()

        self.assertEqual(kwargs["warpOptions"], ["CUTLINE_ALL_TOUCHED=TRUE"])

    def test_dst_srs_is_passed_through(self):
        kwargs = self._warp_kwargs(dst_srs="EPSG:4326")

        self.assertEqual(kwargs["dstSRS"], "EPSG:4326")
        # No resampling algorithm is forced: GDAL's default keeps the source
        # values exactly rather than interpolating new ones.
        self.assertNotIn("resampleAlg", kwargs)

    def test_reprojection_keeps_the_all_touched_cutline(self):
        kwargs = self._warp_kwargs(dst_srs="EPSG:31983")

        self.assertEqual(kwargs["dstSRS"], "EPSG:31983")
        self.assertEqual(kwargs["warpOptions"], ["CUTLINE_ALL_TOUCHED=TRUE"])
        self.assertNotIn("dstAlpha", kwargs)


class TestEffectiveDstSrs(unittest.TestCase):
    """Reprojecting a raster into the CRS it is already in costs a full
    resample and changes nothing, so that request is dropped."""

    def test_no_request_means_no_reprojection(self):

        self.assertIsNone(raster_export._effective_dst_srs(None, "/tmp/src.vrt"))
        self.assertIsNone(raster_export._effective_dst_srs("", "/tmp/src.vrt"))

    def test_matching_source_crs_is_dropped(self):
        import bdc_loader_plugin.core.raster_export as module

        src_ds = MagicMock()
        src_ds.GetProjection.return_value = "EPSG:4326"
        with patch.object(module.gdal, "Open", return_value=src_ds):
            self.assertIsNone(raster_export._effective_dst_srs("EPSG:4326", "/tmp/src.vrt"))

    def test_different_crs_is_kept(self):
        import bdc_loader_plugin.core.raster_export as module

        src_ds = MagicMock()
        src_ds.GetProjection.return_value = "EPSG:4326"
        with patch.object(module.gdal, "Open", return_value=src_ds):
            self.assertEqual(raster_export._effective_dst_srs("EPSG:31983", "/tmp/src.vrt"), "EPSG:31983")

    def test_unreadable_source_leaves_the_decision_to_gdal(self):
        import bdc_loader_plugin.core.raster_export as module

        with patch.object(module.gdal, "Open", return_value=None):
            self.assertEqual(raster_export._effective_dst_srs("EPSG:4326", "/tmp/src.vrt"), "EPSG:4326")

    def test_source_without_a_projection_leaves_the_decision_to_gdal(self):
        import bdc_loader_plugin.core.raster_export as module

        src_ds = MagicMock()
        src_ds.GetProjection.return_value = ""
        with patch.object(module.gdal, "Open", return_value=src_ds):
            self.assertEqual(raster_export._effective_dst_srs("EPSG:4326", "/tmp/src.vrt"), "EPSG:4326")

    def test_unparseable_srs_is_passed_through(self):
        import bdc_loader_plugin.core.raster_export as module

        with patch.object(module.gdal, "Open", side_effect=RuntimeError("boom")):
            self.assertEqual(raster_export._effective_dst_srs("EPSG:4326", "/tmp/src.vrt"), "EPSG:4326")


class TestCutlineChordLength(unittest.TestCase):
    """How finely the cutline is densified before it is reprojected — the
    difference between an edge that follows the boundary and one that cuts
    across it in long chords."""

    def test_pixel_scale_beats_the_coarse_fallback(self):

        # 1 degree of cutline spans 100000 raster units, i.e. 1e-5 deg/unit;
        # a 50-unit pixel is 5e-4 deg, so 4 pixels is 2e-3 deg.
        chord = cutline._cutline_chord_length(1.0, 50.0, 1e-5)

        self.assertAlmostEqual(chord, 2e-3)
        self.assertLess(chord, 1.0 / cutline.CUTLINE_MIN_CHORDS)
        self.assertGreater(chord, 1.0 / cutline.CUTLINE_MAX_CHORDS)

    def test_never_coarser_than_the_fixed_subdivision(self):

        # A huge pixel would ask for a chord longer than the whole shape.
        chord = cutline._cutline_chord_length(1.0, 1e6, 1e-5)

        self.assertEqual(chord, 1.0 / cutline.CUTLINE_MIN_CHORDS)

    def test_vertex_count_stays_bounded_for_tiny_pixels(self):

        chord = cutline._cutline_chord_length(1.0, 1e-9, 1e-5)

        self.assertEqual(chord, 1.0 / cutline.CUTLINE_MAX_CHORDS)

    def test_unknown_scale_falls_back_to_the_fixed_subdivision(self):

        self.assertEqual(cutline._cutline_chord_length(1.0, 10.0, None), 1.0 / cutline.CUTLINE_MIN_CHORDS)
        self.assertEqual(cutline._cutline_chord_length(1.0, 0.0, 1e-5), 1.0 / cutline.CUTLINE_MIN_CHORDS)

    def test_degenerate_span_produces_no_segmentation(self):

        self.assertIsNone(cutline._cutline_chord_length(0.0, 10.0, 1e-5))

    def test_scale_is_measured_across_the_envelope_diagonal(self):

        transform = MagicMock()
        transform.TransformPoint.side_effect = lambda x, y: (x * 1000.0, y * 1000.0, 0.0)

        scale = cutline._units_per_raster_unit((0.0, 2.0, 0.0, 2.0), transform)

        self.assertAlmostEqual(scale, 1e-3)

    def test_unmeasurable_scale_returns_none(self):

        transform = MagicMock()
        transform.TransformPoint.side_effect = RuntimeError("no transform")

        self.assertIsNone(cutline._units_per_raster_unit((0.0, 2.0, 0.0, 2.0), transform))
        self.assertIsNone(cutline._units_per_raster_unit((1.0, 1.0, 1.0, 1.0), MagicMock()))


class TestExtentBoundaryPoints(unittest.TestCase):
    """Corners alone under-measure a reprojected extent — the edges between
    them bow outwards, and a corner-only bbox slices that bulge off."""

    def test_corners_are_included(self):

        points = set(cutline._extent_boundary_points((0.0, 10.0, 0.0, 4.0), samples_per_edge=1))

        for corner in [(0.0, 0.0), (10.0, 0.0), (0.0, 4.0), (10.0, 4.0)]:
            self.assertIn(corner, points)

    def test_edges_are_sampled_between_the_corners(self):

        points = list(cutline._extent_boundary_points((0.0, 10.0, 0.0, 4.0), samples_per_edge=4))

        self.assertIn((5.0, 0.0), points)  # midpoint of the bottom edge
        self.assertIn((0.0, 2.0), points)  # midpoint of the left edge

    def test_every_point_lies_on_the_rectangle(self):

        for x, y in cutline._extent_boundary_points((-5.0, 5.0, -2.0, 2.0)):
            self.assertTrue(x in (-5.0, 5.0) or y in (-2.0, 2.0))
            self.assertTrue(-5.0 <= x <= 5.0 and -2.0 <= y <= 2.0)

    def test_bounds_use_the_sampled_boundary_not_only_the_corners(self):
        """A transform that bows the edges outwards must widen the returned
        bounds; sampling only the corners would miss it entirely."""
        import bdc_loader_plugin.core.cutline as module

        cut_srs = MagicMock()
        cut_srs.IsSame.return_value = False
        layer = MagicMock()
        layer.GetSpatialRef.return_value = cut_srs
        layer.GetExtent.return_value = (0.0, 10.0, 0.0, 10.0)
        cut_ds = MagicMock()
        cut_ds.GetLayer.return_value = layer

        def _bowed(x, y):
            # Points away from the corners are pushed outwards in y.
            bulge = 4.0 * (1.0 - abs(x - 5.0) / 5.0)
            return (x, y - bulge if y < 5.0 else y + bulge, 0.0)

        transform = MagicMock()
        transform.TransformPoint.side_effect = _bowed

        with (
            patch.object(module.ogr, "Open", return_value=cut_ds, create=True),
            patch.object(module.gdal, "Open", return_value=MagicMock()),
            patch.object(module.osr, "CoordinateTransformation", return_value=transform),
        ):
            bounds = cutline._get_cutline_bounds_in_vrt_crs("/tmp/cut.geojson", "/tmp/src.vrt")

        self.assertEqual(bounds, (0.0, -4.0, 10.0, 14.0))


class TestOverviewFallback(unittest.TestCase):
    def test_warns_and_keeps_remote_fallback_for_invalid_overview(self):
        import bdc_loader_plugin.core.vrt_generator as module

        dialog = MagicMock()
        dialog._vrt_cancelled = False
        dialog.progress_bar = MagicMock()
        dialog._cutline_for_group = MagicMock(return_value=None)
        settings_class = MagicMock()
        settings_class.return_value.value.return_value = True
        with (
            patch("qgis.core.QgsSettings", settings_class),
            patch_pipeline("vrt_has_direct_remote_source", return_value=True),
            patch_pipeline("build_overview", return_value=None) as build_mock,
            patch_pipeline("_log_warning") as warning_mock,
        ):
            module.VrtGenerator._build_overviews(_bind_overview_steps(dialog), [("/tmp/a.vrt", "layer", "group")])

        build_mock.assert_called_once_with("/tmp/a.vrt", None)
        warning_mock.assert_called_with(
            "1 of 1 overview could not be created; those layers draw directly from the BDC."
        )
        dialog._set_status.assert_called_with(
            "1 of 1 overview could not be created; those layers draw directly from the BDC.",
            "warning",
        )


class TestStyleRasterLayerStretch(unittest.TestCase):
    def test_applies_sampled_float_range_to_renderer(self):
        import bdc_loader_plugin.core.layer_style as module

        layer = MagicMock()
        layer.isValid.return_value = True
        renderer = MagicMock()
        renderer.usesBands.return_value = [1]
        enhancement = MagicMock()
        layer.renderer.return_value = renderer
        layer.dataProvider.return_value.dataType.return_value = 6

        contrast_class = MagicMock(return_value=enhancement)
        contrast_class.ContrastEnhancementAlgorithm.StretchToMinimumMaximum = "stretch"

        with patch.object(module, "QgsContrastEnhancement", contrast_class):
            result = layer_style._style_raster_layer(
                layer, "/tmp/sentinel1.vrt", "Sentinel-1 Gamma0 VV", {1: (0.003, 0.56)}
            )

        self.assertIs(result, layer)
        contrast_class.assert_called_once_with(6)
        enhancement.setMinimumValue.assert_called_once_with(0.003)
        enhancement.setMaximumValue.assert_called_once_with(0.56)
        enhancement.setContrastEnhancementAlgorithm.assert_called_once_with("stretch")
        renderer.setContrastEnhancement.assert_called_once_with(enhancement)
        layer.setRenderer.assert_not_called()
        layer.triggerRepaint.assert_called_once_with()

    def test_applies_sampled_ranges_to_multiband_renderer_channels(self):
        import bdc_loader_plugin.core.layer_style as module

        layer = MagicMock()
        layer.isValid.return_value = True
        renderer = MagicMock()
        renderer.usesBands.return_value = [1, 2, 3]
        renderer.redBand.return_value = 1
        renderer.greenBand.return_value = 2
        renderer.blueBand.return_value = 3
        layer.renderer.return_value = renderer
        layer.dataProvider.return_value.dataType.side_effect = [6, 6, 6]
        enhancements = [MagicMock(), MagicMock(), MagicMock()]

        contrast_class = MagicMock(side_effect=enhancements)
        contrast_class.ContrastEnhancementAlgorithm.StretchToMinimumMaximum = "stretch"
        ranges = {
            1: (100.0, 1100.0),
            2: (200.0, 1200.0),
            3: (300.0, 1300.0),
        }

        with patch.object(module, "QgsContrastEnhancement", contrast_class):
            result = layer_style._style_raster_layer(layer, "/tmp/optical_rgb.vrt", "Optical RGB", ranges)

        self.assertIs(result, layer)
        renderer.setRedContrastEnhancement.assert_called_once_with(enhancements[0])
        renderer.setGreenContrastEnhancement.assert_called_once_with(enhancements[1])
        renderer.setBlueContrastEnhancement.assert_called_once_with(enhancements[2])
        for enhancement, render_range in zip(enhancements, ranges.values()):
            enhancement.setMinimumValue.assert_called_once_with(render_range[0])
            enhancement.setMaximumValue.assert_called_once_with(render_range[1])
            enhancement.setContrastEnhancementAlgorithm.assert_called_once_with("stretch")
        layer.setRenderer.assert_not_called()
        layer.triggerRepaint.assert_called_once_with()


class TestResolveBandLandsatSensorVariants(unittest.TestCase):
    """The landsat-2 collection mixes TM (Landsat 4/5), ETM+ (Landsat 7) and OLI/OLI-2
    (Landsat 8/9) scenes under one collection ID. These fixtures are the real asset-key
    sets (values are irrelevant to resolve_band, which only checks membership) from live
    STAC items, one per sensor generation. They guarantee that:
      - bands common to every generation always resolve, so True Color / False Color /
        SWIR composites work no matter which sensor produced the selected item;
      - bands that genuinely don't exist for a given sensor (coastal, lwir11 on TM/ETM+)
        resolve to None cleanly instead of raising, so the caller can report a clear
        "band not available" error instead of the item silently failing to load.
    """

    TM_KEYS = {"ang", "blue", "green", "lwir", "nir08", "qa_pixel", "qa_radsat", "red", "swir16", "swir22"}
    ETM_KEYS = {"ang", "blue", "green", "lwir", "nir08", "qa_pixel", "qa_radsat", "red", "swir16", "swir22"}
    OLI_KEYS = {
        "ang",
        "blue",
        "coastal",
        "green",
        "lwir11",
        "nir08",
        "qa_aerosol",
        "qa_pixel",
        "qa_radsat",
        "red",
        "swir16",
        "swir22",
    }

    def _assets(self, keys):
        return {k: {} for k in keys}

    def test_common_bands_resolve_on_every_sensor_generation(self):
        from bdc_loader_plugin.core.band_selection import resolve_band

        common = ["red", "green", "blue", "nir08", "swir16", "swir22"]
        for keys in (self.TM_KEYS, self.ETM_KEYS, self.OLI_KEYS):
            assets = self._assets(keys)
            for band in common:
                self.assertEqual(resolve_band(band, assets), band, f"{band} failed to resolve for {sorted(keys)}")

    def test_oli_only_bands_missing_on_tm_and_etm(self):
        from bdc_loader_plugin.core.band_selection import resolve_band

        tm_assets = self._assets(self.TM_KEYS)
        etm_assets = self._assets(self.ETM_KEYS)
        self.assertIsNone(resolve_band("coastal", tm_assets))
        self.assertIsNone(resolve_band("coastal", etm_assets))
        self.assertIsNone(resolve_band("lwir11", tm_assets))
        self.assertIsNone(resolve_band("lwir11", etm_assets))

    def test_oli_only_bands_present_on_oli(self):
        from bdc_loader_plugin.core.band_selection import resolve_band

        oli_assets = self._assets(self.OLI_KEYS)
        self.assertEqual(resolve_band("coastal", oli_assets), "coastal")
        self.assertEqual(resolve_band("lwir11", oli_assets), "lwir11")


class TestBuildItemNamingPrefix(unittest.TestCase):
    """Tests for build_item_naming_prefix, using real item ids across collections with
    different grids/sensors (landsat-2/WRS2, S2_L2A-1/MGRS, S2-16D-2 cube, CBERS4-MUX)."""

    def test_stac_format_uses_item_id_verbatim(self):
        from bdc_loader_plugin.core.layer_names import build_item_naming_prefix

        result = build_item_naming_prefix(
            "LT05_L2SP_228061_20081121_20200828_02_T1", "landsat-2", "228061", "2008-11-21", False, "stac"
        )
        self.assertEqual(result, "LT05_L2SP_228061_20081121_20200828_02_T1")

    def test_stac_format_sentinel2_scene(self):
        from bdc_loader_plugin.core.layer_names import build_item_naming_prefix

        item_id = "S2C_MSIL2A_20260707T132231_N0512_R038_T22KEU_20260707T175011"
        result = build_item_naming_prefix(item_id, "S2_L2A-1", "22KEU", "2026-07-07", False, "stac")
        self.assertEqual(result, item_id)

    def test_stac_format_cube_item(self):
        from bdc_loader_plugin.core.layer_names import build_item_naming_prefix

        result = build_item_naming_prefix(
            "S2-16D_V2_001014_20260610", "S2-16D-2", "001014", "2026-06-10", False, "stac"
        )
        self.assertEqual(result, "S2-16D_V2_001014_20260610")

    def test_compact_format_ignores_item_id(self):
        from bdc_loader_plugin.core.layer_names import build_item_naming_prefix

        result = build_item_naming_prefix(
            "LT05_L2SP_228061_20081121_20200828_02_T1", "landsat-2", "228061", "2008-11-21", False, "compact"
        )
        self.assertEqual(result, "landsat-2_228061_2008-11-21")

    def test_mosaic_ignores_naming_format(self):
        """Mosaics/crops merge many items — no single STAC id applies, so both formats
        must fall back to collection_id + tile_safe (which already encodes the crop
        location/feature name and date, e.g. 'Crop_15.3S_47.5W_to_15.0S_47.1W_2008-11-21')."""
        from bdc_loader_plugin.core.layer_names import build_item_naming_prefix

        tile_safe = "Crop_15.3S_47.5W_to_15.0S_47.1W_2008-11-21"
        for fmt in ("stac", "compact"):
            result = build_item_naming_prefix("synthetic-mosaic-id", "landsat-2", tile_safe, "2008-11-21", True, fmt)
            self.assertEqual(result, f"landsat-2_{tile_safe}")

    def test_missing_item_id_falls_back_to_compact_even_in_stac_format(self):
        from bdc_loader_plugin.core.layer_names import build_item_naming_prefix

        result = build_item_naming_prefix(None, "landsat-2", "228061", "2008-11-21", False, "stac")
        self.assertEqual(result, "landsat-2_228061_2008-11-21")

    def test_unsafe_characters_in_item_id_are_sanitized(self):
        from bdc_loader_plugin.core.layer_names import build_item_naming_prefix

        result = build_item_naming_prefix("weird/id:with*chars", "col", "t", "2026-01-01", False, "stac")
        self.assertNotIn("/", result)
        self.assertNotIn(":", result)
        self.assertNotIn("*", result)


class TestNamingSamplesEndToEnd(unittest.TestCase):
    """Full VRT-filename samples (prefix + '-'.join(bands) suffix) across collections,
    matching the reference table shared with the user, for both naming formats."""

    def _name(self, item_id, collection_id, tile_safe, date_str, bands, naming_format="stac"):
        from bdc_loader_plugin.core.layer_names import build_item_naming_prefix

        prefix = build_item_naming_prefix(item_id, collection_id, tile_safe, date_str, False, naming_format)
        return f"{prefix}_{'-'.join(bands)}"

    def test_landsat_single_band_stac(self):
        name = self._name("LT05_L2SP_228061_20081121_20200828_02_T1", "landsat-2", "228061", "2008-11-21", ["red"])
        self.assertEqual(name, "LT05_L2SP_228061_20081121_20200828_02_T1_red")

    def test_landsat_rgb_stac(self):
        name = self._name(
            "LT05_L2SP_228061_20081121_20200828_02_T1",
            "landsat-2",
            "228061",
            "2008-11-21",
            ["red", "green", "blue"],
        )
        self.assertEqual(name, "LT05_L2SP_228061_20081121_20200828_02_T1_red-green-blue")

    def test_sentinel2_rgb_stac(self):
        name = self._name(
            "S2C_MSIL2A_20260707T132231_N0512_R038_T22KEU_20260707T175011",
            "S2_L2A-1",
            "22KEU",
            "2026-07-07",
            ["nir08", "red", "green"],
        )
        self.assertEqual(name, "S2C_MSIL2A_20260707T132231_N0512_R038_T22KEU_20260707T175011_nir08-red-green")

    def test_cbers_mux_single_band_stac(self):
        name = self._name("CB4MUX-2M_V1_008005_20260301", "CBERS4-MUX-2M-1", "008005", "2026-03-01", ["BAND6"])
        self.assertEqual(name, "CB4MUX-2M_V1_008005_20260301_BAND6")

    def test_landsat_single_band_compact(self):
        name = self._name(
            "LT05_L2SP_228061_20081121_20200828_02_T1",
            "landsat-2",
            "228061",
            "2008-11-21",
            ["red"],
            naming_format="compact",
        )
        self.assertEqual(name, "landsat-2_228061_2008-11-21_red")

    def test_landsat_rgb_compact(self):
        name = self._name(
            "LT05_L2SP_228061_20081121_20200828_02_T1",
            "landsat-2",
            "228061",
            "2008-11-21",
            ["red", "green", "blue"],
            naming_format="compact",
        )
        self.assertEqual(name, "landsat-2_228061_2008-11-21_red-green-blue")

    def test_candidates_cover_both_current_formats_and_legacy_rgb(self):
        from bdc_loader_plugin.core.layer_names import build_vrt_layer_name_candidates

        candidates = build_vrt_layer_name_candidates(
            "LT05_L2SP_228061_20081121_20200828_02_T1",
            "landsat-2",
            "228061",
            "2008-11-21",
            ["red", "green", "blue"],
        )

        self.assertEqual(
            candidates,
            (
                "LT05_L2SP_228061_20081121_20200828_02_T1_red-green-blue",
                "landsat-2_228061_2008-11-21_red-green-blue",
                "landsat-2_228061_2008-11-21_red_green_blue",
            ),
        )

    def test_single_band_candidates_do_not_duplicate_legacy_name(self):
        from bdc_loader_plugin.core.layer_names import build_vrt_layer_name_candidates

        candidates = build_vrt_layer_name_candidates(
            "S1A_IW_RTCH_1SDV_20260620_065050_0832F0_8892",
            "sentinel-1-rtc-1",
            "S1A_IW_RTCH_1SDV_20260620_065050_0832F0_8892",
            "2026-06-20",
            ["Gamma0_VH"],
        )
        self.assertEqual(len(candidates), 2)


class TestVrtHasDirectRemoteSource(unittest.TestCase):
    """Tests for vrt_has_direct_remote_source — VRT XML content check."""

    def test_remote_source(self):
        from bdc_loader_plugin.core.vrt_builder import vrt_has_direct_remote_source

        with tempfile.NamedTemporaryFile(mode="w", suffix=".vrt", delete=False) as f:
            f.write("<VRTDataset><SourceFilename>/vsicurl/https://example.com/tile.tif</SourceFilename></VRTDataset>")
            f.flush()
            result = vrt_has_direct_remote_source(f.name)
        os.unlink(f.name)
        self.assertTrue(result)

    def test_local_source(self):
        from bdc_loader_plugin.core.vrt_builder import vrt_has_direct_remote_source

        with tempfile.NamedTemporaryFile(mode="w", suffix=".vrt", delete=False) as f:
            f.write("<VRTDataset><SourceFilename>/tmp/local_tile.tif</SourceFilename></VRTDataset>")
            f.flush()
            result = vrt_has_direct_remote_source(f.name)
        os.unlink(f.name)
        self.assertFalse(result)

    def test_remote_source_after_many_local_ones(self):
        from bdc_loader_plugin.core.vrt_builder import vrt_has_direct_remote_source

        local = "".join(f"<SourceFilename>/data/local_tile_{i:04d}.tif</SourceFilename>" for i in range(2000))
        with tempfile.NamedTemporaryFile(mode="w", suffix=".vrt", delete=False) as f:
            f.write(f"<VRTDataset>{local}<SourceFilename>/vsicurl/https://x/t.tif</SourceFilename></VRTDataset>")
        try:
            self.assertGreater(os.path.getsize(f.name), 16384)
            self.assertTrue(vrt_has_direct_remote_source(f.name))
        finally:
            os.unlink(f.name)

    def test_nonexistent_file(self):
        from bdc_loader_plugin.core.vrt_builder import vrt_has_direct_remote_source

        self.assertFalse(vrt_has_direct_remote_source("/tmp/nonexistent_file.vrt"))

    def test_empty_file(self):
        from bdc_loader_plugin.core.vrt_builder import vrt_has_direct_remote_source

        with tempfile.NamedTemporaryFile(mode="w", suffix=".vrt", delete=False) as f:
            f.write("")
            f.flush()
            result = vrt_has_direct_remote_source(f.name)
        os.unlink(f.name)
        self.assertFalse(result)


class TestIsValidLocalRaster(unittest.TestCase):
    """is_valid_local_raster — the reuse gate that keeps an unfinished or broken
    local file from being mistaken for a completed download.

    The filesystem checks (existence, size, ``.part`` sibling) run on a real
    temp dir; GDAL's open/dimensions/band checks use an injected opener because
    the suite runs under a fake GDAL whose Open always returns None.
    """

    def setUp(self):
        self.work_dir = tempfile.mkdtemp(prefix="bdc_test_valid_raster_")
        self.addCleanup(shutil.rmtree, self.work_dir, ignore_errors=True)
        self.path = os.path.join(self.work_dir, "tile_B04.tif")

    def _write(self, path, data=b"GTIFF-BYTES"):
        with open(path, "wb") as f:
            f.write(data)

    def _dataset(self, xsize=64, ysize=64, bands=1, band=object()):
        ds = MagicMock()
        ds.RasterXSize = xsize
        ds.RasterYSize = ysize
        ds.RasterCount = bands
        ds.GetRasterBand.return_value = band
        return ds

    def _opener(self, dataset):
        calls = []

        def _open(path, mode=0):
            calls.append((path, mode))
            return dataset

        _open.calls = calls
        return _open

    def _call(self, opener):
        from bdc_loader_plugin.core.vrt_builder import is_valid_local_raster

        return is_valid_local_raster(self.path, opener=opener)

    def test_nonexistent_file_is_invalid(self):
        opener = self._opener(self._dataset())
        self.assertFalse(self._call(opener))
        # Missing files short-circuit before any GDAL open is attempted.
        self.assertEqual(opener.calls, [])

    def test_empty_file_is_invalid(self):
        self._write(self.path, b"")
        opener = self._opener(self._dataset())
        self.assertFalse(self._call(opener))
        self.assertEqual(opener.calls, [])

    def test_corrupt_file_is_invalid(self):
        # Non-empty bytes that GDAL cannot open as a raster (opener -> None).
        self._write(self.path, b"not a real geotiff")
        self.assertFalse(self._call(self._opener(None)))

    def test_part_sibling_makes_file_invalid(self):
        self._write(self.path)
        self._write(self.path + ".part", b"in-progress")
        opener = self._opener(self._dataset())
        self.assertFalse(self._call(opener))
        # The .part check precedes the GDAL open, so no open happens.
        self.assertEqual(opener.calls, [])

    def test_valid_final_with_residual_part_is_invalid(self):
        """A finished, openable raster with a leftover ``.part`` sibling must
        still be treated as unfinished and re-fetched."""
        self._write(self.path)
        self._write(self.path + ".part", b"leftover")
        self.assertFalse(self._call(self._opener(self._dataset())))

    def test_zero_dimensions_is_invalid(self):
        self._write(self.path)
        self.assertFalse(self._call(self._opener(self._dataset(xsize=0, ysize=10))))

    def test_no_bands_is_invalid(self):
        self._write(self.path)
        self.assertFalse(self._call(self._opener(self._dataset(bands=0))))

    def test_unreadable_band_is_invalid(self):
        self._write(self.path)
        self.assertFalse(self._call(self._opener(self._dataset(band=None))))

    def test_open_raising_is_invalid(self):
        self._write(self.path)

        def _boom(path, mode=0):
            raise RuntimeError("open failed")

        self.assertFalse(self._call(_boom))

    def test_valid_geotiff_is_reusable(self):
        self._write(self.path)
        opener = self._opener(self._dataset(xsize=64, ysize=64, bands=3))
        self.assertTrue(self._call(opener))
        self.assertEqual(opener.calls[0][0], self.path)


class TestOverviewStreamsFullRaster(unittest.TestCase):
    """overview_streams_full_raster — a pyramid-less source only counts when it
    is also big enough for the full read to hurt.

    BDC serves scene-level products (AMZ1-WFI-L4-DN-1, CB4-WFI-L4-DN-1) as
    large striped GeoTIFFs with no internal overviews, unlike its data cubes
    (S2-16D-2) which are tiled COGs with a pyramid. Between them sit small
    pyramid-less collections (landsat-tsirf-*) whose overview is cheap.
    """

    @staticmethod
    def _dataset(overview_count, xsize=16126, ysize=14163):
        band = MagicMock()
        band.GetOverviewCount.return_value = overview_count
        dataset = MagicMock()
        dataset.GetRasterBand.return_value = band
        dataset.RasterXSize = xsize
        dataset.RasterYSize = ysize
        return dataset

    def test_large_source_without_pyramid_is_detected(self):

        # AMZ1-WFI-L4-DN-1 scene geometry: 228 Mpx, far above the pixel limit.
        self.assertTrue(overviews.overview_streams_full_raster(self._dataset(0)))

    def test_small_source_without_pyramid_is_not_flagged(self):

        # landsat-tsirf-yearly-1 geometry: 16 Mpx, under the pixel limit, so
        # the overview is worth building despite the missing pyramid.
        self.assertFalse(overviews.overview_streams_full_raster(self._dataset(0, 4004, 4004)))

    def test_cog_with_pyramid_is_not_flagged(self):

        self.assertFalse(overviews.overview_streams_full_raster(self._dataset(5)))

    def test_pyramid_wins_over_size(self):

        # A huge COG mosaic still reads cheaply through its pyramid.
        self.assertFalse(overviews.overview_streams_full_raster(self._dataset(8, 60000, 60000)))

    def test_missing_dataset_is_not_flagged(self):

        self.assertFalse(overviews.overview_streams_full_raster(None))

    def test_unreadable_band_is_not_flagged(self):

        dataset = MagicMock()
        dataset.GetRasterBand.side_effect = RuntimeError("no band")
        self.assertFalse(overviews.overview_streams_full_raster(dataset))


class TestOverviewSkipsFullRasterStreams(unittest.TestCase):
    """build_overview must not warp a remote source that has no pyramid.

    gdal.Warp reads the source at reduced resolution; without a pyramid that
    read expands to every full-resolution block, so a remote scene is pulled in
    full over /vsicurl before anything renders.
    """

    def setUp(self):
        with tempfile.NamedTemporaryFile(suffix=".vrt", delete=False) as vrt:
            self.vrt_path = vrt.name
        self.addCleanup(lambda: os.path.exists(self.vrt_path) and os.unlink(self.vrt_path))

    def _write_vrt(self, source):
        with open(self.vrt_path, "w", encoding="utf-8") as handle:
            handle.write(f"<VRTDataset><SourceFilename>{source}</SourceFilename></VRTDataset>")

    @staticmethod
    def _source_dataset(overview_count, xsize=16126, ysize=14163):
        band = MagicMock()
        band.GetOverviewCount.return_value = overview_count
        dataset = MagicMock()
        dataset.GetRasterBand.return_value = band
        dataset.RasterXSize = xsize
        dataset.RasterYSize = ysize
        dataset.GetGeoTransform.return_value = (0, 64, 0, 0, 0, -64)
        return dataset

    def _run(self, source, overview_count, xsize=16126, ysize=14163):
        import bdc_loader_plugin.core.overviews as module

        self._write_vrt(source)
        gdal = module.gdal
        with (
            patch.object(gdal, "Open", return_value=self._source_dataset(overview_count, xsize, ysize)),
            patch.object(gdal, "GA_Update", 1, create=True),
            patch.object(gdal, "Warp", return_value=MagicMock(), create=True) as warp_mock,
            patch.object(gdal, "WarpOptions", return_value=MagicMock(), create=True),
            patch.object(module, "_validate_overview", return_value=(True, None)),
            patch.object(module, "_log_warning") as warning_mock,
            patch.object(module.os, "replace"),
        ):
            result = overviews.build_overview(self.vrt_path)
        return result, warp_mock, warning_mock

    def test_remote_source_without_pyramid_is_skipped(self):
        result, warp_mock, warning_mock = self._run("/vsicurl/https://data.inpe.br/scene_BAND4.tif", 0)

        self.assertIsNone(result)
        warp_mock.assert_not_called()
        self.assertIn("no internal overviews", warning_mock.call_args.args[0])

    def test_remote_cog_with_pyramid_still_builds(self):
        result, warp_mock, _ = self._run("/vsicurl/https://data.inpe.br/cube_B04.tif", 5)

        self.assertEqual(result, self.vrt_path + ".ovr")
        warp_mock.assert_called_once()

    def test_local_source_without_pyramid_still_builds(self):
        # A downloaded file is read from disk, so a full read is cheap and the
        # overview is still worth building.
        result, warp_mock, _ = self._run("/home/user/downloads/scene_BAND4.tif", 0)

        self.assertEqual(result, self.vrt_path + ".ovr")
        warp_mock.assert_called_once()

    def test_small_remote_source_without_pyramid_still_builds(self):
        # landsat-tsirf-* geometry: pyramid-less but under the pixel limit,
        # so the overview must not be skipped.
        result, warp_mock, _ = self._run("/vsicurl/https://data.inpe.br/tsirf.tif", 0, xsize=4004, ysize=4004)

        self.assertEqual(result, self.vrt_path + ".ovr")
        warp_mock.assert_called_once()


class TestVrtBuildPhaseKeepsUiResponsive(unittest.TestCase):
    """Phase 2 waits on its workers from the UI thread too. build_single_vrt
    only reads source metadata, but a rate-limited server can still stall it,
    and the wait must not become a freeze."""

    @staticmethod
    def _dialog():
        dialog = MagicMock()
        dialog._vrt_cancelled = False
        dialog.progress_bar = MagicMock()
        return dialog

    def test_stalled_build_is_abandoned_and_reported(self):
        import time

        import bdc_loader_plugin.core.vrt_generator as module

        dialog = self._dialog()
        events = []
        core = MagicMock()
        core.processEvents.side_effect = lambda: events.append(time.monotonic())
        errors = []

        started = time.monotonic()
        with (
            patch_pipeline("build_single_vrt", side_effect=lambda t: time.sleep(30)),
            patch_pipeline("QCoreApplication", core),
            patch_pipeline("_VRT_BUILD_BUDGET_S", 1.0),
            patch_pipeline("_log_warning"),
            patch_pipeline("_log_info"),
        ):
            vrt_paths, errors, cancelled, _ = module.VrtGenerator._execute_vrt_build(
                dialog, [{"tile": "a"}], errors, time.time(), False
            )
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 10, "phase 2 held the UI thread past its budget")
        self.assertEqual(vrt_paths, [])
        self.assertTrue(any("abandoned" in e for e in errors), errors)
        # The UI keeps getting event-loop time while the worker is stuck.
        self.assertGreater(len(events), 2)
        self.assertLess(max(b - a for a, b in zip(events, events[1:])), 1.0)

    def test_normal_build_still_collects_results_and_errors(self):
        import time

        import bdc_loader_plugin.core.vrt_generator as module

        dialog = self._dialog()
        results = {
            "ok_tile": ("ok", "/tmp/ok.vrt", "layer", "group"),
            "bad_tile": ("error", "bad_tile", "band missing"),
        }
        errors = []

        with (
            patch_pipeline("build_single_vrt", side_effect=lambda t: results[t["tile"]]),
            patch_pipeline("QCoreApplication", MagicMock()),
            patch_pipeline("_log_info"),
        ):
            vrt_paths, errors, cancelled, _ = module.VrtGenerator._execute_vrt_build(
                dialog, [{"tile": "ok_tile"}, {"tile": "bad_tile"}], errors, time.time(), False
            )

        self.assertEqual(vrt_paths, [("/tmp/ok.vrt", "layer", "group")])
        self.assertEqual(errors, ["bad_tile: band missing"])
        self.assertFalse(cancelled)

    def test_cancel_still_returns_partial_results(self):
        import time

        import bdc_loader_plugin.core.vrt_generator as module

        dialog = self._dialog()
        errors = []

        def _cancel_after_first(task):
            dialog._vrt_cancelled = True
            return ("ok", "/tmp/a.vrt", "layer", "group")

        with (
            patch_pipeline("build_single_vrt", side_effect=_cancel_after_first),
            patch_pipeline("QCoreApplication", MagicMock()),
            patch_pipeline("_log_info"),
        ):
            vrt_paths, errors, cancelled, _ = module.VrtGenerator._execute_vrt_build(
                dialog, [{"tile": "a"}], errors, time.time(), False
            )

        self.assertTrue(cancelled)


class TestOverviewPhaseKeepsUiResponsive(unittest.TestCase):
    """_build_overviews runs on the UI thread; a stalled remote read must not
    hold it. Waiting on the futures directly froze QGIS for as long as the
    slowest read took."""

    @staticmethod
    def _dialog():
        dialog = MagicMock()
        dialog._vrt_cancelled = False
        dialog.progress_bar = MagicMock()
        dialog._cutline_for_group = MagicMock(return_value=None)
        dialog._render_ranges_cache = {}
        return dialog

    def test_slow_preparation_is_abandoned_within_the_budget(self):
        import time

        import bdc_loader_plugin.core.vrt_generator as module

        dialog = self._dialog()
        settings_class = MagicMock()
        settings_class.return_value.value.return_value = True
        process_events_at = []

        def _never_returns(vrt_path, cutline=None):
            time.sleep(30)
            return vrt_path + ".ovr"

        core = MagicMock()
        core.processEvents.side_effect = lambda: process_events_at.append(time.monotonic())

        started = time.monotonic()
        with (
            patch("qgis.core.QgsSettings", settings_class),
            patch_pipeline("vrt_has_direct_remote_source", return_value=True),
            patch_pipeline("build_overview", side_effect=_never_returns),
            patch_pipeline("estimate_vrt_render_ranges", return_value={}),
            patch_pipeline("QCoreApplication", core),
            patch_pipeline("_OVERVIEW_PHASE_BUDGET_S", 1.0),
            patch_pipeline("_log_warning"),
        ):
            module.VrtGenerator._build_overviews(_bind_overview_steps(dialog), [("/tmp/slow.vrt", "layer", "group")])
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 10, "phase 2.5 held the UI thread past its budget")
        # The UI keeps getting event-loop time while the worker is stuck.
        self.assertGreater(len(process_events_at), 2)
        self.assertLess(max(b - a for a, b in zip(process_events_at, process_events_at[1:])), 1.0)

    def test_abandoned_vrt_is_not_resampled_on_the_ui_thread(self):
        import time

        import bdc_loader_plugin.core.vrt_generator as module

        dialog = self._dialog()
        settings_class = MagicMock()
        settings_class.return_value.value.return_value = True

        with (
            patch("qgis.core.QgsSettings", settings_class),
            patch_pipeline("vrt_has_direct_remote_source", return_value=True),
            patch_pipeline("build_overview", side_effect=lambda p, c=None: time.sleep(30)),
            patch_pipeline("estimate_vrt_render_ranges", return_value={}) as estimate,
            patch_pipeline("QCoreApplication", MagicMock()),
            patch_pipeline("_OVERVIEW_PHASE_BUDGET_S", 1.0),
            patch_pipeline("_log_warning"),
        ):
            vrt_paths = [("/tmp/slow.vrt", "layer", "group")]
            module.VrtGenerator._build_overviews(_bind_overview_steps(dialog), vrt_paths)
            # Phase 2.5 seeded the cache, so phase 2.6 has nothing left to do.
            self.assertIn("/tmp/slow.vrt", dialog._render_ranges_cache)
            estimate.reset_mock()
            module.VrtGenerator._precompute_render_ranges(dialog, vrt_paths)

        estimate.assert_not_called()

    def test_pyramidless_collection_is_reported_as_such(self):
        # A skipped overview and a failed one need different advice: this one
        # is a property of the collection's format, not a transient error.
        import bdc_loader_plugin.core.vrt_generator as module

        dialog = self._dialog()
        settings_class = MagicMock()
        settings_class.return_value.value.return_value = True

        with (
            patch("qgis.core.QgsSettings", settings_class),
            patch_pipeline("vrt_has_direct_remote_source", return_value=True),
            patch_pipeline("build_overview", return_value=None),
            patch_pipeline("remote_vrt_streams_full_raster", return_value=True),
            patch_pipeline("estimate_vrt_render_ranges", return_value={}),
            patch_pipeline("QCoreApplication", MagicMock()),
            patch_pipeline("_log_warning") as warning_mock,
        ):
            module.VrtGenerator._build_overviews(_bind_overview_steps(dialog), [("/tmp/scene.vrt", "layer", "group")])

        status = dialog._set_status.call_args.args[0]
        self.assertIn("not cloud-optimized", status)
        self.assertIn("Download these images", status)
        # The message must say nothing was generated, since the render range is
        # skipped along with the overview.
        self.assertIn("no overview or contrast was prepared", status)
        self.assertIn("not cloud-optimized", warning_mock.call_args.args[0])
        # It is not counted as a failure, so no misleading "not created" alarm.
        self.assertFalse(any("could not be created" in str(call) for call in warning_mock.call_args_list))

    def test_pyramidless_layer_is_sampled_with_fewer_rows(self):
        # Without a range QGIS samples the scene itself on the UI thread when
        # the layer is built; a 64-row sample in the worker avoids that freeze.
        import bdc_loader_plugin.core.vrt_generator as module

        dialog = self._dialog()
        settings_class = MagicMock()
        settings_class.return_value.value.return_value = True
        sampled = {1: (45.0, 1023.0)}

        with (
            patch("qgis.core.QgsSettings", settings_class),
            patch_pipeline("vrt_has_direct_remote_source", return_value=True),
            patch_pipeline("build_overview", return_value=None),
            patch_pipeline("remote_vrt_streams_full_raster", return_value=True),
            patch_pipeline("estimate_vrt_render_ranges", return_value=sampled) as estimate,
            patch_pipeline("QCoreApplication", MagicMock()),
            patch_pipeline("_log_warning"),
        ):
            module.VrtGenerator._build_overviews(_bind_overview_steps(dialog), [("/tmp/scene.vrt", "layer", "group")])

        estimate.assert_called_once_with("/tmp/scene.vrt", sample_size=vrt_overview_run._FULL_STREAM_SAMPLE)
        self.assertEqual(dialog._render_ranges_cache["/tmp/scene.vrt"], sampled)

    def test_fast_preparation_still_completes_normally(self):
        import bdc_loader_plugin.core.vrt_generator as module

        dialog = self._dialog()
        settings_class = MagicMock()
        settings_class.return_value.value.return_value = True

        with (
            patch("qgis.core.QgsSettings", settings_class),
            patch_pipeline("vrt_has_direct_remote_source", return_value=True),
            patch_pipeline("build_overview", return_value="/tmp/a.vrt.ovr") as build_mock,
            patch_pipeline("estimate_vrt_render_ranges", return_value={1: (0.1, 0.9)}),
            patch_pipeline("QCoreApplication", MagicMock()),
            patch_pipeline("_log_info") as info_mock,
        ):
            module.VrtGenerator._build_overviews(_bind_overview_steps(dialog), [("/tmp/a.vrt", "layer", "group")])

        build_mock.assert_called_once_with("/tmp/a.vrt", None)
        self.assertEqual(dialog._render_ranges_cache["/tmp/a.vrt"], {1: (0.1, 0.9)})
        info_mock.assert_called_with("Overviews: 1/1 generated")


class TestLoadRunAlwaysEnds(unittest.TestCase):
    """An error in a load phase still gives Load, Search and the Cancel button back."""

    def test_an_error_in_a_phase_ends_the_run(self):
        import tempfile

        from bdc_loader_plugin.core.vrt_generator import VrtGenerator

        owner = MagicMock()
        owner._load_bands.return_value = ["B04"]
        owner._load_collection.return_value = ("S2-16D-2", {}, {})
        owner._prepare_vrt_tasks.side_effect = RuntimeError("phase 1 broke")
        with tempfile.TemporaryDirectory() as tmp:
            owner.output_dir.text.return_value = tmp
            with self.assertRaises(RuntimeError):
                VrtGenerator.generate_and_load(owner)

        owner._begin_vrt_run.assert_called_once()
        owner._end_vrt_run.assert_called_once_with()


class TestCollectionCloudOptimizedFlag(unittest.TestCase):
    """collection_is_cloud_optimized — derived from item_assets, which the
    /collections response already carries, so the flag costs no extra request.

    It is an advertisement: BDC gets it wrong for a few collections in both
    directions, which is why it drives a hint and not a filter.
    """

    @staticmethod
    def _collection(*types):
        return {"item_assets": {f"B{i}": {"type": t} for i, t in enumerate(types)}}

    def test_all_cog_assets(self):
        from bdc_loader_plugin.stac.client import collection_is_cloud_optimized

        cog = "image/tiff; application=geotiff; profile=cloud-optimized"
        self.assertTrue(collection_is_cloud_optimized(self._collection(cog, cog)))

    def test_plain_geotiff_assets(self):
        from bdc_loader_plugin.stac.client import collection_is_cloud_optimized

        self.assertFalse(collection_is_cloud_optimized(self._collection("image/tiff; application=geotiff")))

    def test_mixed_assets_count_as_cloud_optimized(self):
        # S2_L2A-1 labels 15 of 16 raster assets cloud-optimized and leaves AOT
        # plain, yet AOT measures as a COG like the rest. Demanding every label
        # agree condemned a whole cloud-optimized collection.
        from bdc_loader_plugin.stac.client import collection_is_cloud_optimized

        cog = "image/tiff; application=geotiff; profile=cloud-optimized"
        self.assertTrue(collection_is_cloud_optimized(self._collection(cog, "image/tiff")))

    def test_non_raster_assets_fall_back_to_bdc_type(self):
        from bdc_loader_plugin.stac.client import collection_is_cloud_optimized

        collection = {"item_assets": {"thumbnail": {"type": "image/png"}}, "bdc:type": "cube"}
        self.assertTrue(collection_is_cloud_optimized(collection))
        self.assertFalse(collection_is_cloud_optimized({"item_assets": {"thumbnail": {"type": "image/png"}}}))

    def test_missing_item_assets_without_cube_type_is_false(self):
        from bdc_loader_plugin.stac.client import collection_is_cloud_optimized

        self.assertFalse(collection_is_cloud_optimized({}))
        self.assertTrue(collection_is_cloud_optimized({"bdc:type": "cube"}))


class TestCollectionBadge(unittest.TestCase):
    """badge_for_collection — drives the COG / GEOTIFF pill in the combo."""

    def test_cloud_optimized_gets_cog_badge(self):
        from bdc_loader_plugin.widgets.collection_badge import COG_BADGE, badge_for_collection

        self.assertEqual(badge_for_collection({"cloud_optimized": True}), COG_BADGE)

    def test_plain_geotiff_gets_geotiff_badge(self):
        from bdc_loader_plugin.widgets.collection_badge import GEOTIFF_BADGE, badge_for_collection

        self.assertEqual(badge_for_collection({"cloud_optimized": False}), GEOTIFF_BADGE)

    def test_unknown_format_gets_no_badge(self):
        # The offline fallback carries no asset media types; drawing no badge
        # beats guessing one.
        from bdc_loader_plugin.widgets.collection_badge import badge_for_collection

        self.assertIsNone(badge_for_collection({}))

    def test_type_badge_classification(self):
        from bdc_loader_plugin.widgets.collection_badge import type_badge_for_collection

        self.assertEqual(type_badge_for_collection({"type": "cube"}), "CUBE")
        self.assertEqual(type_badge_for_collection({"type": "mosaic"}), "MOSAIC")
        self.assertEqual(type_badge_for_collection({"type": "collection"}), "SCENE")
        self.assertEqual(type_badge_for_collection({}), "SCENE")

    def test_grid_badge_classification(self):
        from bdc_loader_plugin.widgets.collection_badge import (
            NO_GRID_BADGE,
            grid_badge_for_collection,
        )

        self.assertIsNone(grid_badge_for_collection({"grid": "CBERS_MUX"}))
        self.assertEqual(grid_badge_for_collection({"has_tiles": False}), NO_GRID_BADGE)
        self.assertEqual(grid_badge_for_collection({"grid": "-"}), NO_GRID_BADGE)
        self.assertEqual(grid_badge_for_collection({}), NO_GRID_BADGE)


class TestNonCogGenerationGuardDialog(unittest.TestCase):
    """generate_and_load must let the user back out before paying for a build
    that cannot produce an overview or a stretch, and must stop nagging once
    they say so."""

    @staticmethod
    def _dialog():
        dialog = MagicMock()
        dialog.get_selected_items.return_value = [MagicMock()]
        dialog.selected_bands.count.return_value = 1
        dialog.selected_bands.item.return_value.data.return_value = "BAND4"
        dialog.is_extent_crop_mode.return_value = False
        dialog.output_dir.text.return_value = "/tmp/out"
        dialog.collection_combo.currentIndex.return_value = 0
        dialog.collection_combo.itemData.return_value = "AMZ1-WFI-L4-DN-1"
        # Let the pipeline past the guard run to a harmless finish.
        dialog._prepare_vrt_tasks.return_value = ([], [])
        dialog._execute_vrt_build.return_value = ([], [], False, 0.0)
        dialog._load_vrt_layers.return_value = (0, 0, 0)
        return _bind_load_steps(dialog)

    def _run(self, cloud_optimized, button="cancel", muted=False, tick_never_again=False):
        import bdc_loader_plugin.core.vrt_generator as module

        dialog = self._dialog()
        collections = {"AMZ1-WFI-L4-DN-1": {"id": "AMZ1-WFI-L4-DN-1", "cloud_optimized": cloud_optimized}}

        message_box = MagicMock()
        message_box.StandardButton.Yes = 0x4000
        message_box.StandardButton.Cancel = 0x400000
        box = MagicMock()
        box.exec.return_value = message_box.StandardButton.Yes if button == "yes" else message_box.StandardButton.Cancel
        message_box.return_value = box

        checkbox = MagicMock()
        checkbox.isChecked.return_value = tick_never_again

        with (
            patch_catalog(*(collections, {})),
            patch.object(module, "band_availability_issues", return_value=[]),
            patch.object(module, "QMessageBox", message_box),
            patch.object(module, "QCheckBox", return_value=checkbox),
            patch.object(module, "_non_cog_warning_muted", return_value=muted),
            patch.object(module, "_mute_non_cog_warning") as mute,
            patch.object(module.os, "makedirs"),
        ):
            module.VrtGenerator.generate_and_load(dialog)
        return dialog, box, mute

    def test_non_cog_collection_asks_before_building(self):
        dialog, box, _ = self._run(cloud_optimized=False)

        box.exec.assert_called_once()
        self.assertIn("Download", box.setText.call_args.args[0])
        box.setCheckBox.assert_called_once()
        # Cancelling must stop before any VRT work starts.
        dialog._prepare_vrt_tasks.assert_not_called()

    def test_cog_collection_is_not_interrupted(self):
        _, box, _ = self._run(cloud_optimized=True, button="yes")

        box.exec.assert_not_called()

    def test_unknown_format_is_not_interrupted(self):
        # Offline fallback: no flag, so no nag.
        _, box, _ = self._run(cloud_optimized=None, button="yes")

        box.exec.assert_not_called()

    def test_dont_show_again_is_persisted(self):
        _, _, mute = self._run(cloud_optimized=False, button="yes", tick_never_again=True)

        mute.assert_called_once_with()

    def test_dont_show_again_is_honored_when_cancelling(self):
        # Someone who cancels and ticks the box has still decided.
        _, _, mute = self._run(cloud_optimized=False, button="cancel", tick_never_again=True)

        mute.assert_called_once_with()

    def test_unticked_box_keeps_the_warning(self):
        _, _, mute = self._run(cloud_optimized=False, button="yes", tick_never_again=False)

        mute.assert_not_called()

    def test_muted_warning_does_not_interrupt(self):
        dialog, box, _ = self._run(cloud_optimized=False, muted=True)

        box.exec.assert_not_called()
        # Muting only silences the prompt; the build proceeds.
        dialog._prepare_vrt_tasks.assert_called_once()


class TestVrtSourcesMatch(unittest.TestCase):
    """vrt_sources_match — decides whether a rebuild would change anything."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.vrt_path = os.path.join(self.dir, "scene.vrt")

    def _write(self, *sources):
        bands = "".join(
            f"<VRTRasterBand band='{i + 1}'><SimpleSource>"
            f"<SourceFilename relativeToVRT='0'>{s}</SourceFilename>"
            f"</SimpleSource></VRTRasterBand>"
            for i, s in enumerate(sources)
        )
        with open(self.vrt_path, "w", encoding="utf-8") as handle:
            handle.write(f"<VRTDataset rasterXSize='10' rasterYSize='10'>{bands}</VRTDataset>")

    def test_identical_sources_match(self):
        import bdc_loader_plugin.core.vrt_builder as module

        hrefs = ["/vsicurl/https://x/a.tif", "/vsicurl/https://x/b.tif"]
        self._write(*hrefs)
        self.assertTrue(module.vrt_sources_match(self.vrt_path, hrefs))

    def test_cloud_to_local_upgrade_does_not_match(self):
        # The one change worth rebuilding for: the scene was downloaded, so the
        # VRT must be re-pointed at the local file.
        import bdc_loader_plugin.core.vrt_builder as module

        self._write("/vsicurl/https://x/a.tif")
        self.assertFalse(module.vrt_sources_match(self.vrt_path, ["/home/u/downloads/a.tif"]))

    def test_band_order_change_does_not_match(self):
        import bdc_loader_plugin.core.vrt_builder as module

        self._write("/vsicurl/https://x/a.tif", "/vsicurl/https://x/b.tif")
        self.assertFalse(
            module.vrt_sources_match(self.vrt_path, ["/vsicurl/https://x/b.tif", "/vsicurl/https://x/a.tif"])
        )

    def test_band_count_change_does_not_match(self):
        import bdc_loader_plugin.core.vrt_builder as module

        self._write("/vsicurl/https://x/a.tif")
        self.assertFalse(
            module.vrt_sources_match(self.vrt_path, ["/vsicurl/https://x/a.tif", "/vsicurl/https://x/b.tif"])
        )

    def test_missing_vrt_does_not_match(self):
        import bdc_loader_plugin.core.vrt_builder as module

        self.assertFalse(module.vrt_sources_match(self.vrt_path, ["/vsicurl/https://x/a.tif"]))

    def test_corrupt_vrt_does_not_match(self):
        import bdc_loader_plugin.core.vrt_builder as module

        with open(self.vrt_path, "w", encoding="utf-8") as handle:
            handle.write("<VRTDataset><unclosed>")
        self.assertFalse(module.vrt_sources_match(self.vrt_path, ["/vsicurl/https://x/a.tif"]))


class TestSplitUnchangedTasks(unittest.TestCase):
    """Already-loaded layers whose sources did not change must not be rebuilt."""

    def _split(self, tasks, loaded_names, matches):

        project = MagicMock()
        project.instance.return_value.mapLayers.return_value = {
            str(i): MagicMock(**{"name.return_value": n}) for i, n in enumerate(loaded_names)
        }
        with (
            patch_pipeline("QgsProject", project),
            patch_pipeline("vrt_sources_match", side_effect=lambda p, h: matches),
        ):
            return vrt_tasks._split_unchanged_tasks(tasks)

    def test_loaded_layer_with_same_sources_is_skipped(self):
        task = {"layer_name": "scene_rgb", "vrt_path": "/tmp/scene_rgb.vrt", "hrefs": ["/vsicurl/a.tif"]}

        to_build, unchanged = self._split([task], {"scene_rgb"}, matches=True)

        self.assertEqual(to_build, [])
        self.assertEqual(unchanged, [task])

    def test_downloaded_scene_is_rebuilt_against_the_local_file(self):
        task = {"layer_name": "scene_rgb", "vrt_path": "/tmp/scene_rgb.vrt", "hrefs": ["/home/u/a.tif"]}

        to_build, unchanged = self._split([task], {"scene_rgb"}, matches=False)

        self.assertEqual(to_build, [task])
        self.assertEqual(unchanged, [])

    def test_layer_not_loaded_is_built(self):
        task = {"layer_name": "scene_rgb", "vrt_path": "/tmp/scene_rgb.vrt", "hrefs": ["/vsicurl/a.tif"]}

        to_build, unchanged = self._split([task], set(), matches=True)

        self.assertEqual(to_build, [task])
        self.assertEqual(unchanged, [])


class TestFindBandDownload(unittest.TestCase):
    """find_band_download — the single place writer and reader agree on.

    The download names files after the band the user picked; the VRT builder
    knows the asset key it resolved to. When those differ, looking up only one
    spelling made a downloaded scene invisible and it was re-read over HTTP.
    """

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def _place(self, collection_id, item_id, filename):
        import bdc_loader_plugin.core.download as module

        item_dir = module.band_download_dir(self.root, collection_id, item_id)
        os.makedirs(item_dir, exist_ok=True)
        path = os.path.join(item_dir, filename)
        with open(path, "wb") as handle:
            handle.write(b"tif")
        return path

    def _find(self, *args, **kwargs):
        import bdc_loader_plugin.core.download as module

        with patch.object(module, "is_valid_local_raster", side_effect=os.path.isfile):
            return module.find_band_download(self.root, *args, **kwargs)

    def test_finds_file_named_after_the_selected_band(self):
        expected = self._place("AMZ1-WFI-L4-DN-1", "SCENE_1", "SCENE_1_BAND4.tif")

        self.assertEqual(self._find("AMZ1-WFI-L4-DN-1", "SCENE_1", "BAND4", "BAND4"), expected)

    def test_finds_file_when_the_asset_key_differs_from_the_band(self):
        # Aliased band: downloaded as "rgb", resolved to asset "tci".
        expected = self._place("S2-16D-2", "SCENE_2", "SCENE_2_rgb.tif")

        self.assertEqual(self._find("S2-16D-2", "SCENE_2", "rgb", "tci"), expected)

    def test_finds_file_named_after_the_resolved_asset(self):
        expected = self._place("S2-16D-2", "SCENE_3", "SCENE_3_tci.tif")

        self.assertEqual(self._find("S2-16D-2", "SCENE_3", "rgb", "tci"), expected)

    def test_sanitizes_ids_the_same_way_the_download_does(self):
        # The writer sanitizes; a reader that did not looked in a path that
        # never existed.
        import bdc_loader_plugin.core.download as module

        collection_id = "coll/with:unsafe"
        item_id = "item/with:unsafe"
        item_dir = module.band_download_dir(self.root, collection_id, item_id)
        self.assertNotIn("/with", item_dir[len(self.root) :].replace(os.sep, "/", 1))
        os.makedirs(item_dir, exist_ok=True)
        safe_item = module._safe_path_component(item_id)
        expected = os.path.join(item_dir, f"{safe_item}_BAND4.tif")
        with open(expected, "wb") as handle:
            handle.write(b"tif")

        self.assertEqual(self._find(collection_id, item_id, "BAND4", "BAND4"), expected)

    def test_missing_download_returns_none(self):
        self.assertIsNone(self._find("AMZ1-WFI-L4-DN-1", "SCENE_9", "BAND4", "BAND4"))


class TestCompositionTaskSources(unittest.TestCase):
    """Single-band and RGB tasks read a downloaded band from disk and the rest over /vsicurl/.

    Both look the download up with find_band_download, so a scene saved under
    the band spelling the user picked, or under a sanitized id, is found.
    """

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.out = os.path.join(self.root, "vrt")
        self.addCleanup(shutil.rmtree, self.root, True)

    @staticmethod
    def _item(item_id, *bands):
        assets = {band: SimpleNamespace(href=f"https://data/{item_id}/{band}.tif") for band in bands}
        assets["thumbnail"] = SimpleNamespace(href="https://data/thumb.png")
        return SimpleNamespace(id=item_id, assets=assets)

    def _download(self, collection_id, item_id, band):
        import bdc_loader_plugin.core.download as module

        item_dir = module.band_download_dir(self.root, collection_id, item_id)
        os.makedirs(item_dir, exist_ok=True)
        path = os.path.join(item_dir, f"{module._safe_path_component(item_id)}_{band}.tif")
        with open(path, "wb") as handle:
            handle.write(b"tif")
        return path

    def _single(self, band, items, errors, is_mosaic=True):
        import bdc_loader_plugin.core.download as download
        from bdc_loader_plugin.core.vrt_generator import VrtGenerator

        with patch.object(download, "is_valid_local_raster", side_effect=os.path.isfile):
            return VrtGenerator._build_single_band_task(
                None, band, items, items[0], is_mosaic, "S2-16D-2", "T1", "T1", "2024-01-01",
                self.root, self.out, None, "group", "stac", errors,
            )  # fmt: skip

    def _rgb(self, bands, items, errors, is_mosaic):
        import bdc_loader_plugin.core.download as download
        from bdc_loader_plugin.core.vrt_generator import VrtGenerator

        with patch.object(download, "is_valid_local_raster", side_effect=os.path.isfile):
            return VrtGenerator._build_rgb_task(
                None, bands, "4,3,2", items, items[0], is_mosaic, "S2-16D-2", "T1", "T1", "2024-01-01",
                self.root, self.out, False, None, "group", "stac", errors,
            )  # fmt: skip

    def test_single_band_reads_a_download_saved_under_the_picked_spelling_and_a_sanitized_id(self):
        # The band resolves to asset "B04" by case; the download used the picked "b04"
        # and a sanitized item id.
        local = self._download("S2-16D-2", "SCENE:1", "b04")
        items = [self._item("SCENE:1", "B04"), self._item("SCENE_2", "B04")]

        task = self._single("b04", items, [])

        self.assertEqual(task["hrefs"], [local, "/vsicurl/https://data/SCENE_2/B04.tif"])
        self.assertEqual(task["vrt_path"], os.path.join(self.out, task["layer_name"] + ".vrt"))
        self.assertFalse(task["separate"])

    def test_single_band_missing_from_every_item_reports_the_available_assets(self):
        errors = []

        self.assertIsNone(self._single("B08", [self._item("S1", "B04", "B03")], errors))
        self.assertEqual(errors, ["T1: band 'B08' not available (available: ['B04', 'B03'])"])

    def test_scene_rgb_takes_one_source_per_band_in_band_order(self):
        local = self._download("S2-16D-2", "S1", "B03")
        task = self._rgb(["B04", "B03", "B02"], [self._item("S1", "B02", "B03", "B04")], [], is_mosaic=False)

        self.assertEqual(task["hrefs"], ["/vsicurl/https://data/S1/B04.tif", local, "/vsicurl/https://data/S1/B02.tif"])
        self.assertNotIn("href_groups", task)
        self.assertEqual(task["band_desc"], "RGB 4,3,2")

    def test_mosaic_rgb_groups_every_item_that_has_the_band(self):
        items = [self._item("S1", "B04", "B03", "B02"), self._item("S2", "B04", "B02")]

        task = self._rgb(["B04", "B03", "B02"], items, [], is_mosaic=True)

        self.assertEqual(task["hrefs"], [])
        self.assertEqual(
            task["href_groups"],
            [
                ["/vsicurl/https://data/S1/B04.tif", "/vsicurl/https://data/S2/B04.tif"],
                ["/vsicurl/https://data/S1/B03.tif"],
                ["/vsicurl/https://data/S1/B02.tif", "/vsicurl/https://data/S2/B02.tif"],
            ],
        )
        self.assertEqual(task["band_desc"], "Mosaic RGB 4,3,2")

    def test_rgb_with_a_missing_band_reports_it_and_builds_nothing(self):
        errors = []

        for is_mosaic in (False, True):
            self.assertIsNone(self._rgb(["B04", "B08", "B02"], [self._item("S1", "B04", "B02")], errors, is_mosaic))
        self.assertEqual(errors, ["T1: bands ['B08'] not available (available: ['B04', 'B02'])"] * 2)


class TestReplacedLayerRetiredBeforeRebuild(unittest.TestCase):
    """A rebuilt VRT must be opened only after the outgoing layer let go of it.

    GDAL serves shared dataset handles: opening the path while the old layer
    still holds it returns the cached dataset with the old sources, so a scene
    rebuilt against a fresh download kept streaming over the network even
    though the .vrt on disk already pointed at the local file.
    """

    class _FakeRasterLayer:
        def __init__(self, name, source):
            self._name = name
            self._source = source

        def name(self):
            return self._name

        def source(self):
            return self._source

        def id(self):
            return "old_id"

    def _run(self, old_source, new_source):
        import bdc_loader_plugin.core.vrt_generator as module

        order = []
        old_layer = self._FakeRasterLayer("scene_rgb", old_source)

        project = MagicMock()
        project.instance.return_value.mapLayers.return_value = {"old_id": old_layer}
        project.instance.return_value.removeMapLayers.side_effect = lambda ids: order.append(("remove", tuple(ids)))

        dialog = MagicMock()
        dialog._current_result_mode = "stac_items"

        def _create(vrt_path, layer_name, is_heavy=False):
            order.append(("create", layer_name))
            layer = MagicMock()
            layer.isValid.return_value = True
            layer.name.return_value = layer_name
            return layer

        dialog._open_raster_layers.side_effect = lambda jobs: {
            vrt_path: _create(vrt_path, layer_name) for vrt_path, layer_name in jobs
        }

        with (
            patch_pipeline("QgsProject", project),
            patch_pipeline("QgsRasterLayer", self._FakeRasterLayer),
            patch_pipeline("vrt_has_direct_remote_source", side_effect=lambda p: "vsicurl" in str(p)),
            patch_pipeline("_log_warning"),
            patch_pipeline("_log_info"),
        ):
            result = module.VrtGenerator._load_vrt_layers(_bind_layer_steps(dialog), [(new_source, "scene_rgb", "grp")])
        return order, result

    def test_old_layer_is_removed_before_the_new_one_is_created(self):
        order, _ = self._run("/tmp/scene_rgb.vrt", "/tmp/scene_rgb.vrt")

        kinds = [step for step, _ in order]
        self.assertIn("remove", kinds)
        self.assertIn("create", kinds)
        self.assertLess(
            kinds.index("remove"),
            kinds.index("create"),
            "the replacement was built while the old layer still held the VRT open",
        )

    def test_cloud_to_local_upgrade_is_counted(self):
        # Old layer read /vsicurl/, the rebuilt VRT does not: a real upgrade.
        _, (_loaded, replaced, _skipped) = self._run("/tmp/remote_vsicurl.vrt", "/tmp/local.vrt")

        self.assertEqual(replaced, 1)

    def test_still_remote_rebuild_is_not_counted_as_an_upgrade(self):
        _, (_loaded, replaced, _skipped) = self._run("/tmp/remote_vsicurl.vrt", "/tmp/remote_vsicurl.vrt")

        self.assertEqual(replaced, 0)


class TestReportWhenNothingWasBuilt(unittest.TestCase):
    """A second Load of layers already in the project reports them as up to date, not as a failure."""

    def _report(self, unchanged):
        import bdc_loader_plugin.core.vrt_generator as module

        dialog = MagicMock()
        dialog._unchanged_layers = unchanged
        with patch.object(module, "QMessageBox") as box:
            module.VrtGenerator._report_vrt_results(dialog, [], [], 0, 0, 0, 0.0, False)
        return dialog, box

    def test_layers_already_loaded_get_an_info_status_and_no_error_dialog(self):
        dialog, box = self._report(1)
        box.warning.assert_not_called()
        dialog._set_status.assert_called_once_with("1 layer already loaded and up to date.", "info")

    def test_nothing_loaded_and_nothing_kept_is_still_an_error(self):
        dialog, box = self._report(0)
        box.warning.assert_called_once()
        dialog._set_status.assert_called_once_with("Loading layers failed: no layer was added to the map.", "error")


if __name__ == "__main__":
    unittest.main()
