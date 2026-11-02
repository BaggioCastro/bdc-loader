#!/usr/bin/env python3
"""Tests for GDAL network settings, /vsimem/, and QGIS layer loading."""

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from bdc_loader_plugin.core import layer_style


def _grouped_task(vrt_path):
    return {
        "vrt_path": vrt_path,
        "hrefs": [],
        "href_groups": [["a.tif"], ["b.tif"], ["c.tif"]],
        "separate": True,
        "mixed_res": False,
        "tile": "tile",
        "tile_safe": "tile",
        "layer_name": "layer",
        "band_desc": "RGB",
        "cutline_path": None,
        "group_name": "group",
    }


class TestQgisLayerOptions(unittest.TestCase):
    def test_raster_layer_skips_default_style_lookup(self):
        import bdc_loader_plugin.core.layer_style as module

        layer = MagicMock()
        layer.isValid.return_value = True
        options = SimpleNamespace(loadDefaultStyle=True)
        raster_layer_class = MagicMock(return_value=layer)
        raster_layer_class.LayerOptions.return_value = options

        with patch.object(module, "QgsRasterLayer", raster_layer_class):
            result = layer_style._new_raster_layer("/tmp/example.vrt", "example")

        self.assertIs(result, layer)
        self.assertFalse(options.loadDefaultStyle)
        raster_layer_class.assert_called_once_with(
            "/tmp/example.vrt",
            "example",
            "gdal",
            options,
        )

    def test_cached_range_is_reused_without_sampling(self):
        import bdc_loader_plugin.core.layer_style as module

        # A remote VRT whose range was precomputed off the UI thread in _build_overviews.
        cache = {"/tmp/remote.vrt": {1: (10.0, 200.0)}, "/tmp/no_range.vrt": {}}
        with patch.object(module, "estimate_vrt_render_ranges") as sampler:
            self.assertEqual(layer_style._render_ranges("/tmp/remote.vrt", cache), {1: (10.0, 200.0)})
            # An empty cached range counts as known: the remote source is not sampled again.
            self.assertEqual(layer_style._render_ranges("/tmp/no_range.vrt", cache), {})
        sampler.assert_not_called()

    def test_source_absent_from_cache_is_sampled(self):
        import bdc_loader_plugin.core.layer_style as module

        cache = {"/tmp/remote.vrt": {1: (10.0, 200.0)}}
        with patch.object(module, "estimate_vrt_render_ranges", return_value={1: (1.0, 2.0)}) as sampler:
            self.assertEqual(layer_style._render_ranges("/tmp/local.vrt", cache), {1: (1.0, 2.0)})
        sampler.assert_called_once_with("/tmp/local.vrt")


class TestVsimemFallback(unittest.TestCase):
    def test_grouped_build_uses_memory_path_without_disk_intermediates(self):
        import bdc_loader_plugin.core.vrt_builder as module

        task = _grouped_task("/tmp/result.vrt")
        with (
            patch.object(module, "_build_grouped_vrt_vsimem", return_value=True) as memory_build,
            patch.object(module.gdal, "BuildVRT") as disk_build,
        ):
            result = module.build_single_vrt(task)

        self.assertEqual(result, ("ok", "/tmp/result.vrt", "layer", "group"))
        memory_build.assert_called_once_with(task, None)
        disk_build.assert_not_called()

    def test_grouped_build_falls_back_transparently_to_disk(self):
        import bdc_loader_plugin.core.vrt_builder as module

        task = _grouped_task("/tmp/fallback.vrt")
        dataset = MagicMock()
        with (
            patch.object(module, "_build_grouped_vrt_vsimem", return_value=False),
            patch.object(module.gdal, "BuildVRT", return_value=dataset) as build_vrt,
            patch.object(module.gdal, "BuildVRTOptions", return_value=MagicMock()),
        ):
            result = module.build_single_vrt(task)

        self.assertEqual(result, ("ok", "/tmp/fallback.vrt", "layer", "group"))
        output_paths = [call.args[0] for call in build_vrt.call_args_list]
        self.assertTrue(output_paths)
        self.assertTrue(all(not path.startswith("/vsimem/") for path in output_paths))

    def test_flat_vrt_publisher_rejects_transient_sources(self):
        import bdc_loader_plugin.core.vrt_builder as module

        xml = b'<VRTDataset rasterXSize="1" rasterYSize="1"><SourceFilename>/vsimem/a.vrt</SourceFilename></VRTDataset>'
        with tempfile.TemporaryDirectory() as work:
            path = os.path.join(work, "bad.vrt")
            with self.assertRaisesRegex(RuntimeError, "transient"):
                module._publish_vrt_bytes(xml, path)
            self.assertFalse(os.path.exists(path))


def _real_gdal_fixture():
    from bdc_loader_plugin.tests.test_gdal_integration import _REAL, _real_osgeo_active

    if _REAL is None:
        pytest.skip("real GDAL Python binding not available")
    return _REAL, _real_osgeo_active


def test_vsimem_result_is_persistent_and_data_equivalent():
    """Compare current disk semantics with the RAM-composed persistent VRT."""
    (gdal, _ogr, osr, _modules), real_osgeo_active = _real_gdal_fixture()

    with tempfile.TemporaryDirectory(prefix="bdc_vsimem_equivalence_") as work:
        spatial_ref = osr.SpatialReference()
        spatial_ref.ImportFromEPSG(4326)
        groups = []
        for band_index, (pixel_size, base_value) in enumerate(
            ((1.0, 100), (0.5, 200), (1.0, 300)),
            1,
        ):
            sources = []
            raster_size = int(8 / pixel_size)
            for tile_index in range(2):
                source_path = os.path.join(work, f"band_{band_index}_tile_{tile_index}.tif")
                dataset = gdal.GetDriverByName("GTiff").Create(
                    source_path,
                    raster_size,
                    raster_size,
                    1,
                    gdal.GDT_Int16,
                )
                dataset.SetGeoTransform((tile_index * 8, pixel_size, 0, 8, 0, -pixel_size))
                dataset.SetProjection(spatial_ref.ExportToWkt())
                raster_band = dataset.GetRasterBand(1)
                raster_band.Fill(base_value + tile_index)
                raster_band.SetNoDataValue(-9999)
                dataset = None
                sources.append(source_path)
            groups.append(sources)

        baseline_band_vrts = []
        for index, sources in enumerate(groups, 1):
            band_path = os.path.join(work, f"baseline_band_{index}.vrt")
            dataset = gdal.BuildVRT(
                band_path,
                sources,
                options=gdal.BuildVRTOptions(
                    resampleAlg="cubic",
                    allowProjectionDifference=True,
                ),
            )
            assert dataset is not None
            dataset = None
            baseline_band_vrts.append(band_path)

        baseline_path = os.path.join(work, "baseline.vrt")
        dataset = gdal.BuildVRT(
            baseline_path,
            baseline_band_vrts,
            options=gdal.BuildVRTOptions(
                resampleAlg="cubic",
                separate=True,
                resolution="highest",
            ),
        )
        assert dataset is not None
        dataset = None

        optimized_path = os.path.join(work, "optimized.vrt")
        task = _grouped_task(optimized_path)
        task["href_groups"] = groups
        task["mixed_res"] = True

        with real_osgeo_active() as module:
            result = module.build_single_vrt(task)

        assert result[0] == "ok", result
        assert "/vsimem/" not in open(optimized_path, encoding="utf-8").read()

        baseline = gdal.Open(baseline_path, gdal.GA_ReadOnly)
        optimized = gdal.Open(optimized_path, gdal.GA_ReadOnly)
        assert baseline is not None
        assert optimized is not None

        def profile(dataset):
            srs_value = osr.SpatialReference(wkt=dataset.GetProjection())
            return {
                "size": (dataset.RasterXSize, dataset.RasterYSize),
                "bands": dataset.RasterCount,
                "geotransform": dataset.GetGeoTransform(),
                "epsg": srs_value.GetAuthorityCode(None),
                "types": tuple(dataset.GetRasterBand(index).DataType for index in range(1, dataset.RasterCount + 1)),
                "nodata": tuple(
                    dataset.GetRasterBand(index).GetNoDataValue() for index in range(1, dataset.RasterCount + 1)
                ),
                "checksums": tuple(
                    dataset.GetRasterBand(index).Checksum() for index in range(1, dataset.RasterCount + 1)
                ),
            }

        assert profile(optimized) == profile(baseline)
        assert profile(optimized)["epsg"] == "4326"
        baseline = None
        optimized = None
