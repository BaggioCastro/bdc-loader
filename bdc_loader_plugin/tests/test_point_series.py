# -*- coding: utf-8 -*-
"""
Point time series read grouped by file, band scaling and the indices
computed from it.

The readers run on real GeoTIFFs written with GDAL.
"""

import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from bdc_loader_plugin.extraction import band_scaling, point_series
from bdc_loader_plugin.extraction.point_series import (
    _FAILED,
    assign_items_to_points,
    extract_points_timeseries,
    read_file_points,
)
from bdc_loader_plugin.tests.test_gdal_integration import _REAL

# Readers on real files: real GDAL binding, like test_gdal_integration.py.
_real_gdal = [
    pytest.mark.gdal,
    pytest.mark.skipif(_REAL is None, reason="real GDAL Python binding not available"),
]


def _with_real_gdal(cls):
    for mark in _real_gdal:
        cls = mark(cls)
    return cls


class _RealGdalCase(unittest.TestCase):
    def setUp(self):
        gdal, ogr, osr, real_mods = _REAL
        saved = {k: sys.modules[k] for k in list(sys.modules) if k == "osgeo" or k.startswith("osgeo.")}

        def _restore():
            for k in list(sys.modules):
                if k == "osgeo" or k.startswith("osgeo."):
                    del sys.modules[k]
            sys.modules.update(saved)

        for k in saved:
            del sys.modules[k]
        sys.modules.update(real_mods)
        self.addCleanup(_restore)
        for name, module in (("gdal", gdal), ("ogr", ogr), ("osr", osr)):
            patcher = patch.object(point_series, name, module)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)


def _write_tif(path, values, nodata=None, origin=(-48.0, -20.0), pixel=0.01):
    """WGS84 GeoTIFF whose pixel (row, col) holds values[row][col]."""
    gdal, _ogr, osr, _mods = _REAL
    array = np.array(values, dtype=np.int16)
    ds = gdal.GetDriverByName("GTiff").Create(path, array.shape[1], array.shape[0], 1, gdal.GDT_Int16)
    ds.SetGeoTransform((origin[0], pixel, 0, origin[1], 0, -pixel))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    if nodata is not None:
        band.SetNoDataValue(nodata)
    band.WriteArray(array)
    ds = None
    return path


def _center(col, row, origin=(-48.0, -20.0), pixel=0.01):
    return origin[0] + (col + 0.5) * pixel, origin[1] - (row + 0.5) * pixel


@_with_real_gdal
class TestReadFilePoints(_RealGdalCase):
    def test_reads_every_point_of_one_file(self):
        path = _write_tif(os.path.join(self.tmp, "a.tif"), [[10, 20], [30, 40]])
        values = read_file_points(path, [_center(0, 0), _center(1, 1), _center(1, 0)])
        self.assertEqual(values, [10.0, 40.0, 20.0])

    def test_nodata_and_outside_are_none_not_failures(self):
        path = _write_tif(os.path.join(self.tmp, "b.tif"), [[0, 7]], nodata=0)
        values = read_file_points(path, [_center(0, 0), _center(1, 0), (-10.0, 10.0)])
        self.assertEqual(values, [None, 7.0, None])

    def test_undeclared_nodata_uses_bdc_sentinels(self):
        path = _write_tif(os.path.join(self.tmp, "c.tif"), [[-9999, 5]])
        self.assertEqual(read_file_points(path, [_center(0, 0), _center(1, 0)]), [None, 5.0])

    def test_nan_is_no_data(self):
        gdal, _ogr, osr, _mods = _REAL
        path = os.path.join(self.tmp, "f.tif")
        ds = gdal.GetDriverByName("GTiff").Create(path, 2, 1, 1, gdal.GDT_Float32)
        ds.SetGeoTransform((-48.0, 0.01, 0, -20.0, 0, -0.01))
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)
        ds.SetProjection(srs.ExportToWkt())
        ds.GetRasterBand(1).WriteArray(np.array([[np.nan, 1.5]], dtype=np.float32))
        ds = None
        self.assertEqual(read_file_points(path, [_center(0, 0), _center(1, 0)]), [None, 1.5])

    def test_unreadable_file_is_a_failure(self):
        values = read_file_points(os.path.join(self.tmp, "missing.tif"), [_center(0, 0), _center(1, 0)])
        self.assertEqual(values, [_FAILED, _FAILED])

    def test_pixel_index_floors_west_of_origin(self):
        # Truncation would put -0.5 px in column 0; floor puts it outside.
        path = _write_tif(os.path.join(self.tmp, "d.tif"), [[3, 4]])
        self.assertEqual(read_file_points(path, [(-48.005, -20.005)]), [None])


def _item(item_id, when, hrefs, bbox=None, geometry=None):
    return SimpleNamespace(
        id=item_id,
        datetime=when,
        properties={},
        assets={band: SimpleNamespace(href=href) for band, href in hrefs.items()},
        bbox=bbox,
        geometry=geometry,
    )


class TestExtractPointsTimeseries(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.responses = {}

        def _fake_read(href, points, nodata_fallback=-9999):
            self.calls.append((href, list(points)))
            queue = self.responses.get(href)
            if queue:
                return queue.pop(0)
            return [float(len(href) + i) for i in range(len(points))]

        patcher = patch.object(point_series, "read_file_points", side_effect=_fake_read)
        patcher.start()
        self.addCleanup(patcher.stop)
        pause = patch.object(point_series, "_RETRY_PAUSE_S", 0)
        pause.start()
        self.addCleanup(pause.stop)

    def test_each_file_is_read_once_for_all_its_points(self):
        d1, d2 = datetime(2024, 1, 1), datetime(2024, 1, 17)
        i1 = _item("i1", d1, {"red": "r1", "nir08": "n1"})
        i2 = _item("i2", d2, {"red": "r2", "nir08": "n2"})
        points = [(-47.0, -21.0), (-47.1, -21.1)]
        self.responses = {"/vsicurl/r1": [[1.0, 2.0]], "/vsicurl/r2": [[3.0, 4.0]]}

        series, failed = extract_points_timeseries([[i1, i2], [i1, i2]], points, ["red", "nir08"], max_workers=2)

        self.assertEqual(failed, 0)
        self.assertEqual(
            sorted(href for href, _ in self.calls), ["/vsicurl/n1", "/vsicurl/n2", "/vsicurl/r1", "/vsicurl/r2"]
        )
        for _href, pts in self.calls:
            self.assertEqual(pts, points)
        self.assertEqual(series[0]["red"], [(d1, 1.0), (d2, 3.0)])
        self.assertEqual(series[1]["red"], [(d1, 2.0), (d2, 4.0)])

    def test_points_only_read_files_that_cover_them(self):
        d1 = datetime(2024, 1, 1)
        east = _item("east", d1, {"red": "e"})
        west = _item("west", d1, {"red": "w"})
        extract_points_timeseries([[east], [west]], [(1.0, 0.0), (-1.0, 0.0)], ["red"])
        self.assertEqual(sorted(self.calls), [("/vsicurl/e", [(1.0, 0.0)]), ("/vsicurl/w", [(-1.0, 0.0)])])

    def test_bands_per_point_limits_the_reads(self):
        d1 = datetime(2024, 1, 1)
        item = _item("i", d1, {"red": "r", "nir08": "n"})
        series, _ = extract_points_timeseries(
            [[item], [item]], [(0.0, 0.0), (1.0, 1.0)], ["red", "nir08"], bands_per_point=[{"red"}, {"nir08"}]
        )
        self.assertEqual(sorted(self.calls), [("/vsicurl/n", [(1.0, 1.0)]), ("/vsicurl/r", [(0.0, 0.0)])])
        self.assertEqual(set(series[0]), {"red"})
        self.assertEqual(set(series[1]), {"nir08"})

    def test_failed_read_is_retried_and_does_not_duplicate(self):
        d1 = datetime(2024, 1, 1)
        item = _item("i", d1, {"red": "r"})
        self.responses = {"/vsicurl/r": [[_FAILED, 5.0], [6.0, 5.0]]}
        series, failed = extract_points_timeseries([[item], [item]], [(0.0, 0.0), (1.0, 1.0)], ["red"])
        self.assertEqual(failed, 0)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(series[0]["red"], [(d1, 6.0)])
        self.assertEqual(series[1]["red"], [(d1, 5.0)])

    def test_retry_clears_the_gdal_cache_of_the_file(self):
        item = _item("i", datetime(2024, 1, 1), {"red": "r", "nir08": "n"})
        self.responses = {"/vsicurl/r": [[_FAILED], [6.0]]}
        with patch.object(point_series.gdal, "VSICurlPartialClearCache", create=True) as clear:
            extract_points_timeseries([[item]], [(0.0, 0.0)], ["red", "nir08"])
        clear.assert_called_once_with("/vsicurl/r")

    def test_failure_after_retry_is_counted_not_hidden(self):
        d1 = datetime(2024, 1, 1)
        item = _item("i", d1, {"red": "r"})
        self.responses = {"/vsicurl/r": [[_FAILED, 5.0], [_FAILED, 5.0]]}
        series, failed = extract_points_timeseries([[item], [item]], [(0.0, 0.0), (1.0, 1.0)], ["red"])
        self.assertEqual(failed, 1)
        self.assertNotIn("red", series[0])
        self.assertEqual(series[1]["red"], [(d1, 5.0)])

    def test_nodata_is_not_retried(self):
        item = _item("i", datetime(2024, 1, 1), {"red": "r"})
        self.responses = {"/vsicurl/r": [[None]]}
        series, failed = extract_points_timeseries([[item]], [(0.0, 0.0)], ["red"])
        self.assertEqual((len(self.calls), failed, series[0]), (1, 0, {}))

    def test_progress_counts_files(self):
        item = _item("i", datetime(2024, 1, 1), {"red": "r", "nir08": "n"})
        seen = []
        extract_points_timeseries(
            [[item]], [(0.0, 0.0)], ["red", "nir08"], progress_callback=lambda d, t: seen.append((d, t))
        )
        self.assertEqual(sorted(seen), [(1, 2), (2, 2)])


@_with_real_gdal
class TestAssignItemsToPoints(_RealGdalCase):
    def test_footprint_decides_coverage(self):
        square = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
        triangle = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [0, 1], [0, 0]]]}
        a = _item("a", datetime(2024, 1, 1), {}, bbox=[0, 0, 1, 1], geometry=square)
        b = _item("b", datetime(2024, 1, 1), {}, bbox=[0, 0, 1, 1], geometry=triangle)
        # (0.9, 0.9) is inside both bboxes but outside the triangle.
        self.assertEqual(assign_items_to_points([a, b], [(0.1, 0.1), (0.9, 0.9)]), [[a, b], [a]])

    def test_bbox_when_there_is_no_footprint(self):
        a = _item("a", datetime(2024, 1, 1), {}, bbox=[0, 0, 1, 1])
        self.assertEqual(assign_items_to_points([a], [(0.5, 0.5), (2.0, 2.0)]), [[a], []])


_LANDSAT_COLLECTION = {
    "properties": {
        "eo:bands": [
            {"name": "TM_B3", "common_name": "red", "scale": 2.75e-05, "scale_add": -0.2, "min": 7273, "max": 43636},
            {"name": "OLI_B5", "common_name": "nir08", "scale": 2.75e-05, "scale_add": -0.2, "min": 7273, "max": 43636},
            {"name": "OLI_B4", "common_name": "red", "scale": 2.75e-05, "scale_add": -0.2, "min": 7273, "max": 43636},
            {"name": "QA_PIXEL", "common_name": "quality", "scale": 1.0, "min": 21824, "max": 65534},
        ]
    }
}


class TestBandScaling(unittest.TestCase):
    def test_parse_by_name_and_common_name_names_first(self):
        info = band_scaling._parse(_LANDSAT_COLLECTION)
        self.assertEqual(info["nir08"]["scale"], 2.75e-05)
        self.assertEqual(info["nir08"]["offset"], -0.2)
        self.assertEqual(info["qa_pixel"]["min"], 21824)
        bands = _LANDSAT_COLLECTION["properties"]["eo:bands"] + [{"name": "red", "common_name": "x", "scale": 0.5}]
        # A band named "red" wins over the common name "red" of another band.
        self.assertEqual(band_scaling._parse({"properties": {"eo:bands": bands}})["red"]["scale"], 0.5)

    def test_summaries_are_read_too(self):
        info = band_scaling._parse({"summaries": {"eo:bands": [{"name": "B04", "scale": 0.0001}]}})
        self.assertEqual(info["b04"]["scale"], 0.0001)

    def test_to_reflectance(self):
        entry = {"scale": 2.75e-05, "offset": -0.2}
        out = band_scaling.to_reflectance([("d", 10000.0), ("e", 43636.0)], entry)
        self.assertAlmostEqual(out[0][1], 0.075)
        self.assertAlmostEqual(out[1][1], 0.99999, places=4)

    def test_no_scale_is_unchanged(self):
        series = [("d", 1234.0)]
        self.assertEqual(band_scaling.to_reflectance(series, None), series)
        self.assertEqual(band_scaling.to_reflectance(series, {"scale": None}), series)

    def test_declared_valid_range(self):
        info = band_scaling._parse(_LANDSAT_COLLECTION)
        self.assertEqual(band_scaling.declared_valid_range(info, "nir08"), (7273.0, 43636.0))
        self.assertIsNone(band_scaling.declared_valid_range(info, "swir16"))

    def test_collection_info_is_fetched_once(self):
        response = MagicMock(ok=True)
        response.json.return_value = _LANDSAT_COLLECTION
        band_scaling._cache.pop("TEST-COLL", None)
        self.addCleanup(band_scaling._cache.pop, "TEST-COLL", None)
        with patch.object(band_scaling.requests, "get", return_value=response) as get:
            first = band_scaling.collection_band_info("TEST-COLL")
            second = band_scaling.collection_band_info("TEST-COLL")
        get.assert_called_once()
        self.assertTrue(get.call_args.args[0].endswith("/collections/TEST-COLL"))
        self.assertIs(first, second)

    def test_unreachable_collection_is_empty(self):
        band_scaling._cache.pop("TEST-DOWN", None)
        self.addCleanup(band_scaling._cache.pop, "TEST-DOWN", None)
        with patch.object(band_scaling.requests, "get", side_effect=OSError("down")):
            self.assertEqual(band_scaling.collection_band_info("TEST-DOWN"), {})


class TestIndicesOnReflectance(unittest.TestCase):
    def _manager(self):
        from bdc_loader_plugin.core.ts_bands import TSBandManager

        mgr = TSBandManager.__new__(TSBandManager)
        mgr._band_info = {"landsat-2": {"red": {"common_name": "red"}, "nir08": {"common_name": "nir"}}}
        mgr._collections = {}
        return mgr

    def test_landsat_ndvi_uses_scale_and_offset(self):
        d = datetime(2024, 1, 1)
        # Reflectance red 0.05, nir 0.35 stored as (r + 0.2) / 2.75e-05.
        red = (0.05 + 0.2) / 2.75e-05
        nir = (0.35 + 0.2) / 2.75e-05
        point_data = {"red": [(d, red)], "nir08": [(d, nir)]}
        info = band_scaling._parse(_LANDSAT_COLLECTION)

        self._manager()._compute_vegetation_indices("landsat-2", point_data, ["_NDVI"], info)

        self.assertAlmostEqual(point_data["NDVI"][0][1], (0.35 - 0.05) / (0.35 + 0.05) * 10000, places=3)
        # The stored bands themselves are left as read.
        self.assertEqual(point_data["red"], [(d, red)])

    def test_without_band_info_index_uses_values_as_read(self):
        d = datetime(2024, 1, 1)
        point_data = {"red": [(d, 2000.0)], "nir08": [(d, 8000.0)]}
        self._manager()._compute_vegetation_indices("landsat-2", point_data, ["_NDVI"])
        self.assertAlmostEqual(point_data["NDVI"][0][1], 6000.0)


class TestOneItemPerDate(unittest.TestCase):
    """Overlapping tiles of one acquisition must not mix bands from different items."""

    def test_all_bands_of_a_date_come_from_one_item(self):
        from datetime import datetime

        from bdc_loader_plugin.extraction.point_series import _one_item_per_date

        day = datetime(2024, 5, 1)
        rows = {
            "B04": [(day, 900.0, "T22KGA"), (day, 300.0, "T22KHA")],
            "B08": [(day, 3000.0, "T22KHA"), (day, 3100.0, "T22KGA")],
        }
        result = _one_item_per_date(rows)
        self.assertEqual(result, {"B04": [(day, 900.0)], "B08": [(day, 3100.0)]})  # both from T22KGA
        reversed_rows = {band: list(reversed(values)) for band, values in rows.items()}
        self.assertEqual(_one_item_per_date(reversed_rows), result)  # independent of read order

    def test_the_item_with_more_bands_wins(self):
        from datetime import datetime

        from bdc_loader_plugin.extraction.point_series import _one_item_per_date

        day = datetime(2024, 5, 1)
        rows = {"B04": [(day, 900.0, "A"), (day, 300.0, "B")], "B08": [(day, 3000.0, "B")]}  # A is nodata in B08
        self.assertEqual(_one_item_per_date(rows), {"B04": [(day, 300.0)], "B08": [(day, 3000.0)]})


if __name__ == "__main__":
    unittest.main()
