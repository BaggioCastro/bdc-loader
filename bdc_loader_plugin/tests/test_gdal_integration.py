#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GDAL integration tests for the masked-GeoTIFF export and the local-raster
reuse gate, exercised against a real GDAL install (no network).

The rest of the suite runs under a fake GDAL installed by conftest.py, so these
tests load the real ``osgeo`` modules on the side and patch them into
``core.vrt_builder`` for the duration of each test, restoring the fakes
afterwards. They are deselected from the default unit suite (marked both
``integration`` and ``gdal``) and never touch the network — everything is a
small, deterministic, locally generated GeoTIFF.

Requirements: a working GDAL Python binding (``osgeo.gdal`` with ``gdal.Warp``).
Run only these tests with:

    pytest -m gdal bdc_loader_plugin/tests/test_gdal_integration.py

When a real GDAL binding is unavailable the whole module is skipped, so it can
never mask a failure in the mock-based unit suite.
"""

import contextlib
import importlib
import os
import shutil
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

import pytest

from bdc_loader_plugin.core import cutline, raster_export

from .real_osgeo import patch_plugin_osgeo

pytestmark = [pytest.mark.gdal]


def _load_real_osgeo():
    """Import the real osgeo modules even though conftest's fake shadows them.

    Returns (gdal, ogr, osr, real_modules) or None if no real GDAL binding is
    installed. The fakes are always restored into sys.modules before returning,
    so the rest of the suite keeps running against the mock.
    """
    fake = {k: sys.modules.pop(k) for k in list(sys.modules) if k == "osgeo" or k.startswith("osgeo.")}
    try:
        gdal = importlib.import_module("osgeo.gdal")
        ogr = importlib.import_module("osgeo.ogr")
        osr = importlib.import_module("osgeo.osr")
        if not hasattr(gdal, "Warp"):
            return None
        real = {k: sys.modules[k] for k in list(sys.modules) if k == "osgeo" or k.startswith("osgeo.")}
        return gdal, ogr, osr, real
    except Exception:
        return None
    finally:
        for k in list(sys.modules):
            if k == "osgeo" or k.startswith("osgeo."):
                del sys.modules[k]
        sys.modules.update(fake)


_REAL = _load_real_osgeo()

pytestmark.append(pytest.mark.skipif(_REAL is None, reason="real GDAL Python binding not available"))


@contextlib.contextmanager
def _real_osgeo_active():
    """Swap the real osgeo modules into sys.modules and into the plugin modules
    for the duration of the block, then restore the fakes. Yields core.vrt_builder."""
    real_gdal, real_ogr, real_osr, real_mods = _REAL
    import bdc_loader_plugin.core.vrt_builder as vb

    saved = {k: sys.modules[k] for k in list(sys.modules) if k == "osgeo" or k.startswith("osgeo.")}
    for k in list(sys.modules):
        if k == "osgeo" or k.startswith("osgeo."):
            del sys.modules[k]
    sys.modules.update(real_mods)
    try:
        with contextlib.ExitStack() as stack:
            patch_plugin_osgeo(stack, real_gdal, real_ogr, real_osr)
            yield vb
    finally:
        for k in list(sys.modules):
            if k == "osgeo" or k.startswith("osgeo."):
                del sys.modules[k]
        sys.modules.update(saved)


class TestExportMaskedGeotiffRealGdal(unittest.TestCase):
    """export_masked_geotiff against a real gdal.Warp with a real cutline."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="bdc_gdal_it_")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.src = os.path.join(self.work, "src.tif")
        self.cut = os.path.join(self.work, "cut.geojson")
        self.dst = os.path.join(self.work, "out.tif")
        self.part = self.dst + ".part"
        self._make_source_raster(self.src)

    def _make_source_raster(self, path, bands=3):
        """A 40x40 EPSG:4326 GeoTIFF covering lon[0,4], lat[0,4], each band a
        distinct constant so masking is observable per band."""
        gdal, _ogr, osr, _mods = _REAL
        drv = gdal.GetDriverByName("GTiff")
        ds = drv.Create(path, 40, 40, bands, gdal.GDT_Byte)
        ds.SetGeoTransform([0.0, 0.1, 0.0, 4.0, 0.0, -0.1])
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)
        ds.SetProjection(srs.ExportToWkt())
        for b in range(1, bands + 1):
            ds.GetRasterBand(b).Fill(100 + b)
        ds.FlushCache()
        ds = None

    def _write_triangle_cutline(self):
        # Right triangle over the raster's lower-left half: (1,1),(3,1),(1,3).
        # After cropToCutline the bbox is lon[1,3] x lat[1,3] (20x20 px); the
        # upper-right corner of that box falls outside the triangle -> nodata.
        geojson = (
            '{"type":"FeatureCollection","features":[{"type":"Feature","properties":{},'
            '"geometry":{"type":"Polygon","coordinates":[[[1,1],[3,1],[1,3],[1,1]]]}}]}'
        )
        with open(self.cut, "w") as f:
            f.write(geojson)

    def test_creates_masked_geotiff_with_expected_shape_and_cutline(self):
        gdal = _REAL[0]
        self._write_triangle_cutline()

        with _real_osgeo_active():
            ok, result = raster_export.export_masked_geotiff(self.src, self.cut, self.dst)

        self.assertTrue(ok, msg=result)
        self.assertEqual(result, self.dst)
        # Atomic commit: the final file is there, the .part temp is gone.
        self.assertTrue(os.path.isfile(self.dst))
        self.assertFalse(os.path.exists(self.part))

        out = gdal.Open(self.dst)
        self.assertIsNotNone(out)
        # cropToCutline reduces the raster to the cutline's 2x2-deg bbox.
        self.assertEqual((out.RasterXSize, out.RasterYSize), (20, 20))
        self.assertEqual(out.RasterCount, 3)
        self.assertEqual(out.GetRasterBand(1).GetNoDataValue(), 0)

        # A pixel inside the triangle keeps its source value; the outside
        # corner is set to nodata (0) by the cutline mask.
        inside = struct.unpack("B", out.GetRasterBand(1).ReadRaster(1, out.RasterYSize - 2, 1, 1))[0]
        outside = struct.unpack("B", out.GetRasterBand(1).ReadRaster(out.RasterXSize - 2, 1, 1, 1))[0]
        out = None
        self.assertEqual(inside, 101)
        self.assertEqual(outside, 0)

    def test_failure_cleans_up_temp_and_leaves_no_final(self):
        self._write_triangle_cutline()

        def _boom(dst_arg, *a, **k):
            # Write a partial temp, then crash mid-warp.
            with open(dst_arg, "wb") as fh:
                fh.write(b"partial")
            raise RuntimeError("simulated warp failure")

        with _real_osgeo_active():
            with patch.object(raster_export.gdal, "Warp", side_effect=_boom), patch.object(raster_export, "_log_error"):
                ok, msg = raster_export.export_masked_geotiff(self.src, self.cut, self.dst)

        self.assertFalse(ok)
        self.assertIn("simulated warp failure", msg)
        self.assertFalse(os.path.exists(self.dst))
        self.assertFalse(os.path.exists(self.part))

    def test_existing_valid_final_replaced_after_new_write(self):
        self._write_triangle_cutline()

        with _real_osgeo_active():
            ok1, _ = raster_export.export_masked_geotiff(self.src, self.cut, self.dst)
        self.assertTrue(ok1)
        first_size = os.path.getsize(self.dst)

        # A second export over the same dst commits through .part and replaces
        # the existing final in place; the old file is never left half-written.
        with _real_osgeo_active():
            ok2, _ = raster_export.export_masked_geotiff(self.src, self.cut, self.dst)
        self.assertTrue(ok2)
        self.assertFalse(os.path.exists(self.part))
        self.assertTrue(os.path.isfile(self.dst))
        self.assertGreater(os.path.getsize(self.dst), 0)
        self.assertEqual(os.path.getsize(self.dst), first_size)


class TestExportMaskedGeotiffOutputOptionsRealGdal(unittest.TestCase):
    """The download-time output projection against a real gdal.Warp — these
    are the claims the mock suite cannot check: that the output really lands
    in the requested CRS, that asking for the CRS the source is already in is
    dropped instead of resampled, and that the cutline keeps the pixels its
    boundary only crosses."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="bdc_gdal_crs_")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.src = os.path.join(self.work, "src.tif")
        self.cut = os.path.join(self.work, "cut.geojson")
        self._make_source_raster(self.src)
        self._write_triangle_cutline()

    def _make_source_raster(self, path, bands=3):
        gdal, _ogr, osr, _mods = _REAL
        drv = gdal.GetDriverByName("GTiff")
        ds = drv.Create(path, 60, 60, bands, gdal.GDT_Byte)
        ds.SetGeoTransform([0.0, 0.1, 0.0, 6.0, 0.0, -0.1])
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)
        ds.SetProjection(srs.ExportToWkt())
        for b in range(1, bands + 1):
            ds.GetRasterBand(b).Fill(100 + b)
        ds.FlushCache()
        ds = None

    def _write_triangle_cutline(self):
        with open(self.cut, "w") as f:
            f.write(
                '{"type":"FeatureCollection","features":[{"type":"Feature","properties":{},'
                '"geometry":{"type":"Polygon","coordinates":[[[1,1],[5,1],[1,5],[1,1]]]}}]}'
            )

    def _band_values(self, path, band_no):
        gdal = _REAL[0]
        ds = gdal.Open(path)
        band = ds.GetRasterBand(band_no)
        raw = band.ReadRaster(0, 0, ds.RasterXSize, ds.RasterYSize)
        values = struct.unpack("B" * (ds.RasterXSize * ds.RasterYSize), raw)
        ds = None
        return values

    def test_dst_srs_writes_the_output_in_the_requested_projection(self):
        gdal, _ogr, osr, _mods = _REAL
        dst = os.path.join(self.work, "reprojected.tif")

        with _real_osgeo_active():
            ok, result = raster_export.export_masked_geotiff(self.src, self.cut, dst, dst_srs="EPSG:3857")

        self.assertTrue(ok, msg=result)
        out = gdal.Open(dst)
        out_srs = osr.SpatialReference()
        out_srs.ImportFromWkt(out.GetProjection())
        out = None
        self.assertEqual(out_srs.GetAuthorityCode(None), "3857")

    def test_requesting_the_source_projection_is_not_a_reprojection(self):
        """A project already on the cube's grid must cost exactly what the
        native option costs — no resample, no dstSRS handed to Warp."""
        with _real_osgeo_active():
            self.assertIsNone(raster_export._effective_dst_srs("EPSG:4326", self.src))
            self.assertEqual(raster_export._effective_dst_srs("EPSG:3857", self.src), "EPSG:3857")

    def test_reprojected_output_still_masks_outside_the_cutline(self):
        gdal = _REAL[0]
        dst = os.path.join(self.work, "reprojected_masked.tif")

        with _real_osgeo_active():
            ok, result = raster_export.export_masked_geotiff(self.src, self.cut, dst, dst_srs="EPSG:3857")

        self.assertTrue(ok, msg=result)
        out = gdal.Open(dst)
        width, height = out.RasterXSize, out.RasterYSize
        band = out.GetRasterBand(1)
        # The triangle's hypotenuse runs corner to corner, so the upper-right
        # of the cropped box is outside the shape and must be nodata.
        outside = struct.unpack("B", band.ReadRaster(width - 2, 1, 1, 1))[0]
        inside = struct.unpack("B", band.ReadRaster(1, height - 2, 1, 1))[0]
        self.assertEqual(band.GetNoDataValue(), 0)
        out = None
        self.assertEqual(outside, 0)
        self.assertEqual(inside, 101)

    def test_cutline_keeps_the_pixels_its_boundary_crosses(self):
        """CUTLINE_ALL_TOUCHED keeps the partial ring a centre-based mask
        drops. That ring is what would otherwise render as stair-stepped
        transparent notches just inside the shape overlay."""
        gdal = _REAL[0]
        kept = os.path.join(self.work, "all_touched.tif")

        with _real_osgeo_active():
            ok, msg = raster_export.export_masked_geotiff(self.src, self.cut, kept)
        self.assertTrue(ok, msg=msg)

        # The same warp with a centre-based cutline, for comparison.
        centre = os.path.join(self.work, "centre_based.tif")
        out = gdal.Warp(
            centre,
            self.src,
            options=gdal.WarpOptions(format="GTiff", cutlineDSName=self.cut, cropToCutline=True, dstNodata=0),
        )
        out.FlushCache()
        out = None

        kept_valid = sum(1 for v in self._band_values(kept, 1) if v)
        centre_valid = sum(1 for v in self._band_values(centre, 1) if v)
        self.assertGreater(kept_valid, centre_valid)

    def test_output_has_no_alpha_band(self):
        """The export writes the data bands and nothing else — an added alpha
        band changes the band count downstream tools and the QGIS renderer
        see."""
        gdal = _REAL[0]
        dst = os.path.join(self.work, "no_alpha.tif")

        with _real_osgeo_active():
            ok, msg = raster_export.export_masked_geotiff(self.src, self.cut, dst)
        self.assertTrue(ok, msg=msg)

        src_ds = gdal.Open(self.src)
        out_ds = gdal.Open(dst)
        src_bands, out_bands = src_ds.RasterCount, out_ds.RasterCount
        interps = [
            gdal.GetColorInterpretationName(out_ds.GetRasterBand(b).GetColorInterpretation())
            for b in range(1, out_bands + 1)
        ]
        src_ds = out_ds = None

        self.assertEqual(out_bands, src_bands)
        self.assertNotIn("Alpha", interps)

    def test_reprojection_preserves_the_source_values(self):
        """No resampling algorithm is forced, so a reprojected crop must not
        contain values the source never had."""
        dst = os.path.join(self.work, "reprojected_values.tif")

        with _real_osgeo_active():
            ok, msg = raster_export.export_masked_geotiff(self.src, self.cut, dst, dst_srs="EPSG:3857")
        self.assertTrue(ok, msg=msg)

        for band_no in (1, 2, 3):
            values = set(self._band_values(dst, band_no))
            self.assertTrue(
                values <= {0, 100 + band_no},
                f"band {band_no} gained values {sorted(values - {0, 100 + band_no})}",
            )


class TestCutlineDensificationRealGdal(unittest.TestCase):
    """A lat/lon boundary becomes a curve once reprojected into a metric grid.
    The reprojected cutline has to follow that curve, not cut across it."""

    def setUp(self):
        # The real binding imports osgeo.ogr from sys.modules while it runs, so
        # the real modules stay active for the whole test, not only the call.
        stack = contextlib.ExitStack()
        stack.enter_context(_real_osgeo_active())
        self.addCleanup(stack.close)
        self.work = tempfile.mkdtemp(prefix="bdc_gdal_cutline_")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.raster = os.path.join(self.work, "albers.tif")
        self.cut = os.path.join(self.work, "extent.geojson")
        self.pixel_size = 1000.0
        self._make_albers_raster(self.raster)
        self._write_extent_cutline(self.cut)

    def _make_albers_raster(self, path):
        """A raster on the BDC Albers grid, 1 km pixels, covering the cutline."""
        gdal, _ogr, osr, _mods = _REAL
        drv = gdal.GetDriverByName("GTiff")
        ds = drv.Create(path, 1600, 1600, 1, gdal.GDT_Byte)
        ds.SetGeoTransform([4_200_000.0, self.pixel_size, 0.0, 10_900_000.0, 0.0, -self.pixel_size])
        srs = osr.SpatialReference()
        srs.SetFromUserInput(
            "+proj=aea +lat_0=-12 +lon_0=-54 +lat_1=-2 +lat_2=-22 "
            "+x_0=5000000 +y_0=10000000 +ellps=GRS80 +units=m +no_defs"
        )
        ds.SetProjection(srs.ExportToWkt())
        ds.GetRasterBand(1).Fill(200)
        ds.FlushCache()
        ds = None

    def _write_extent_cutline(self, path):
        """The rectangle an extent crop produces: straight in lat/lon, curved
        once reprojected into Albers."""
        with open(path, "w") as f:
            f.write(
                '{"type":"FeatureCollection","features":[{"type":"Feature","properties":{},'
                '"geometry":{"type":"Polygon","coordinates":'
                "[[[-62,-14],[-52,-14],[-52,-6],[-62,-6],[-62,-14]]]}}]}"
            )

    def _max_deviation(self, reprojected_path, samples=400):
        """Largest distance, in raster units, between the reprojected cutline
        boundary and the true reprojected position of points sampled along the
        original lat/lon rectangle."""
        gdal, ogr, osr, _mods = _REAL

        # OGR geometries borrow their feature's memory, so every feature is
        # held in a name until its geometry has been cloned.
        cut_ds = ogr.Open(self.cut)
        cut_layer = cut_ds.GetLayer()
        cut_srs = cut_layer.GetSpatialRef().Clone()
        cut_feature = cut_layer.GetNextFeature()
        source_geom = cut_feature.GetGeometryRef().Clone()
        cut_feature = None
        cut_ds = None

        raster_ds = gdal.Open(self.raster)
        raster_srs = osr.SpatialReference()
        raster_srs.ImportFromWkt(raster_ds.GetProjection())
        raster_ds = None

        cut_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        raster_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        transform = osr.CoordinateTransformation(cut_srs, raster_srs)

        out_ds = ogr.Open(reprojected_path)
        out_feature = out_ds.GetLayer().GetNextFeature()
        out_boundary = out_feature.GetGeometryRef().GetBoundary().Clone()
        out_feature = None
        out_ds = None

        # Walk the true boundary densely and measure how far the reprojected
        # polygon's edge sits from where each point really lands.
        dense = source_geom.Clone()
        ring = dense.GetGeometryRef(0)
        perimeter = ring.Length()
        dense.Segmentize(perimeter / samples)
        dense.Transform(transform)
        dense_ring = dense.GetGeometryRef(0)

        worst = 0.0
        for index in range(dense_ring.GetPointCount()):
            x, y, *_rest = dense_ring.GetPoint(index)
            point = ogr.Geometry(ogr.wkbPoint)
            point.AddPoint_2D(x, y)
            worst = max(worst, out_boundary.Distance(point))
        return worst

    def test_reprojected_cutline_stays_within_a_pixel_of_the_true_curve(self):
        with _real_osgeo_active():
            reprojected = cutline._cutline_in_raster_srs(self.cut, self.raster)
        self.addCleanup(lambda: os.path.exists(reprojected) and os.remove(reprojected))

        self.assertNotEqual(reprojected, self.cut)  # a reprojection did happen
        self.assertLess(self._max_deviation(reprojected), self.pixel_size)

    def test_vertex_count_stays_bounded(self):
        """Following the curve must not mean an unbounded cutline: the warp
        pays for every vertex."""
        _gdal, ogr, _osr, _mods = _REAL

        with _real_osgeo_active():
            reprojected = cutline._cutline_in_raster_srs(self.cut, self.raster)
            max_chords = cutline.CUTLINE_MAX_CHORDS
        self.addCleanup(lambda: os.path.exists(reprojected) and os.remove(reprojected))

        out_ds = ogr.Open(reprojected)
        out_feature = out_ds.GetLayer().GetNextFeature()
        point_count = out_feature.GetGeometryRef().GetGeometryRef(0).GetPointCount()
        out_feature = None
        out_ds = None

        self.assertGreater(point_count, 100)
        self.assertLessEqual(point_count, 4 * max_chords + 8)


class TestIsValidLocalRasterRealGdal(unittest.TestCase):
    """is_valid_local_raster against real gdal.Open (default opener)."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="bdc_gdal_valid_")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def _make_geotiff(self, path):
        gdal, _ogr, osr, _mods = _REAL
        drv = gdal.GetDriverByName("GTiff")
        ds = drv.Create(path, 16, 16, 1, gdal.GDT_Byte)
        ds.SetGeoTransform([0.0, 0.1, 0.0, 1.6, 0.0, -0.1])
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)
        ds.SetProjection(srs.ExportToWkt())
        ds.GetRasterBand(1).Fill(42)
        ds.FlushCache()
        ds = None

    def test_valid_geotiff_is_reusable(self):
        path = os.path.join(self.work, "good.tif")
        self._make_geotiff(path)
        with _real_osgeo_active() as vb:
            self.assertTrue(vb.is_valid_local_raster(path))

    def test_empty_file_is_not_reusable(self):
        path = os.path.join(self.work, "empty.tif")
        open(path, "wb").close()
        with _real_osgeo_active() as vb:
            self.assertFalse(vb.is_valid_local_raster(path))

    def test_corrupt_file_is_not_reusable(self):
        path = os.path.join(self.work, "corrupt.tif")
        with open(path, "wb") as f:
            f.write(b"this is not a geotiff" * 8)
        with _real_osgeo_active() as vb:
            self.assertFalse(vb.is_valid_local_raster(path))

    def test_valid_geotiff_with_residual_part_is_not_reusable(self):
        path = os.path.join(self.work, "good_with_part.tif")
        self._make_geotiff(path)
        with open(path + ".part", "wb") as f:
            f.write(b"leftover")
        with _real_osgeo_active() as vb:
            self.assertFalse(vb.is_valid_local_raster(path))


class TestGroupedVrtInMemoryRealGdal(unittest.TestCase):
    """_build_grouped_vrt_vsimem composes one band per tile group, on one grid.

    Two tiles side by side, lon[0,1] and lon[1,2], lat[0,1]. Every tile is a
    constant 10 * band + tile, so each output band shows where its pixels came
    from: band order, placement on the grid and a tile missing from a band.
    """

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="bdc_gdal_group_")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def _tile(self, band, tile, pixel=0.01):
        gdal, _ogr, osr, _mods = _REAL
        path = os.path.join(self.work, f"b{band}_t{tile}_{pixel}.tif")
        size = round(1 / pixel)
        ds = gdal.GetDriverByName("GTiff").Create(path, size, size, 1, gdal.GDT_Byte)
        ds.SetGeoTransform([float(tile), pixel, 0.0, 1.0, 0.0, -pixel])
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)
        ds.SetProjection(srs.ExportToWkt())
        band_obj = ds.GetRasterBand(1)
        band_obj.SetNoDataValue(0)
        band_obj.Fill(10 * band + tile)
        ds = None
        return path

    def _compose(self, href_groups, mixed_res=False, cutline=None):
        gdal = _REAL[0]
        vrt_path = os.path.join(self.work, "out.vrt")
        with _real_osgeo_active() as vb:
            ok = vb._build_grouped_vrt_vsimem(
                {"href_groups": href_groups, "mixed_res": mixed_res, "vrt_path": vrt_path}, cutline
            )
            self.assertTrue(ok)
            ds = gdal.Open(vrt_path)
            arrays = [ds.GetRasterBand(i).ReadAsArray() for i in range(1, ds.RasterCount + 1)]
            pixel = ds.GetGeoTransform()[1]
            ds = None
            left = [p for p in (gdal.ReadDirRecursive("/vsimem/") or []) if "bdc_loader" in p]
        self.assertEqual(left, [], "in-memory VRTs must be released")
        return arrays, pixel

    def _assert_halves(self, array, left_value, right_value):
        """Interior columns of the left and right tile hold the expected constants."""
        half = array.shape[1] // 2
        self.assertTrue((array[:, 2 : half - 2] == left_value).all(), f"left half is not {left_value}")
        self.assertTrue((array[:, half + 2 : -2] == right_value).all(), f"right half is not {right_value}")

    def test_same_grid_bands_keep_their_order(self):
        groups = [[self._tile(b, 0), self._tile(b, 1)] for b in (1, 2, 3)]
        arrays, pixel = self._compose(groups)
        self.assertEqual(len(arrays), 3)
        self.assertEqual(arrays[0].shape, (100, 200))
        for band, array in enumerate(arrays, 1):
            self._assert_halves(array, 10 * band, 10 * band + 1)

    def test_coarser_band_is_aligned_to_the_finest_grid(self):
        groups = [
            [self._tile(1, 0), self._tile(1, 1)],
            [self._tile(2, 0, pixel=0.02), self._tile(2, 1, pixel=0.02)],
            [self._tile(3, 0), self._tile(3, 1)],
        ]
        arrays, pixel = self._compose(groups, mixed_res=True)
        self.assertAlmostEqual(pixel, 0.01)
        self.assertEqual({a.shape for a in arrays}, {(100, 200)})
        for band, array in enumerate(arrays, 1):
            self._assert_halves(array, 10 * band, 10 * band + 1)

    def test_band_missing_a_tile_is_empty_there_and_keeps_its_place(self):
        groups = [[self._tile(1, 0), self._tile(1, 1)], [self._tile(2, 1)], [self._tile(3, 0), self._tile(3, 1)]]
        arrays, _pixel = self._compose(groups)
        self.assertEqual({a.shape for a in arrays}, {(100, 200)})
        self._assert_halves(arrays[0], 10, 11)
        self._assert_halves(arrays[1], 0, 21)
        self._assert_halves(arrays[2], 30, 31)

    def test_cutline_off_the_pixel_grid_keeps_every_pixel_it_touches(self):
        # lon 0.505 to 1.505 and lat 0.255 to 0.755 cut through pixels on all four
        # sides; the clip widens to whole pixels: lon 0.50 to 1.51, lat 0.25 to 0.76.
        cutline = os.path.join(self.work, "off_grid.geojson")
        with open(cutline, "w") as f:
            f.write(
                '{"type":"FeatureCollection","features":[{"type":"Feature","properties":{},'
                '"geometry":{"type":"Polygon","coordinates":[[[0.505,0.255],[1.505,0.255],[1.505,0.755],'
                "[0.505,0.755],[0.505,0.255]]]}}]}"
            )
        groups = [[self._tile(b, 0), self._tile(b, 1)] for b in (1, 2, 3)]

        arrays, _pixel = self._compose(groups, cutline=cutline)

        self.assertEqual({a.shape for a in arrays}, {(51, 101)})

    def test_stack_export_writes_the_final_file_with_the_bands_in_order(self):
        gdal = _REAL[0]
        dst = os.path.join(self.work, "stack.tif")
        sources = [self._tile(b, 0) for b in (1, 2, 3)]

        with _real_osgeo_active():
            ok, result = raster_export.export_stack_geotiff(sources, dst, band_names=["B1", "B2", "B3"])
            ds = gdal.Open(dst) if ok else None
            maxima = [int(ds.GetRasterBand(i).ReadAsArray().max()) for i in (1, 2, 3)] if ds else None
            ds = None

        self.assertTrue(ok, result)
        self.assertEqual(result, dst)
        self.assertFalse(os.path.exists(dst + ".part"))
        self.assertEqual(maxima, [10, 20, 30])

    def test_cutline_clips_every_band_to_its_bbox(self):
        cutline = os.path.join(self.work, "cut.geojson")
        with open(cutline, "w") as f:
            f.write(
                '{"type":"FeatureCollection","features":[{"type":"Feature","properties":{},'
                '"geometry":{"type":"Polygon","coordinates":[[[0.5,0.25],[1.5,0.25],[1.5,0.75],[0.5,0.75],[0.5,0.25]]]}}]}'
            )
        groups = [
            [self._tile(1, 0), self._tile(1, 1)],
            [self._tile(2, 0, pixel=0.02), self._tile(2, 1, pixel=0.02)],
            [self._tile(3, 1)],
        ]
        arrays, pixel = self._compose(groups, mixed_res=True, cutline=cutline)
        self.assertAlmostEqual(pixel, 0.01)
        self.assertEqual({a.shape for a in arrays}, {(50, 100)})
        self._assert_halves(arrays[0], 10, 11)
        self._assert_halves(arrays[1], 20, 21)
        self._assert_halves(arrays[2], 0, 31)


if __name__ == "__main__":
    unittest.main()
