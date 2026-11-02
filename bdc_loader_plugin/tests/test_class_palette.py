"""Class bands whose color table is a gray ramp get one color per class (real GDAL)."""

import contextlib
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np
import pytest

from bdc_loader_plugin.tests.real_osgeo import patch_plugin_osgeo
from bdc_loader_plugin.tests.test_gdal_integration import _REAL

pytestmark = [
    pytest.mark.gdal,
    pytest.mark.skipif(_REAL is None, reason="real GDAL Python binding not available"),
]


class TestClassPalette(unittest.TestCase):
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
        import bdc_loader_plugin.core.render_ranges as render_ranges

        self.render_ranges = render_ranges
        stack = contextlib.ExitStack()
        patch_plugin_osgeo(stack, gdal, ogr, osr)
        self.addCleanup(stack.close)
        self.gdal = gdal
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _write(self, name, table):
        gdal = self.gdal
        path = os.path.join(self.tmp, name)
        ds = gdal.GetDriverByName("GTiff").Create(path, 40, 40, 1, gdal.GDT_Byte)
        ds.SetGeoTransform((0, 1, 0, 40, 0, -1))
        values = np.zeros((40, 40), dtype=np.uint8)
        for k, value in enumerate((1, 2, 3, 5)):
            values[k * 10 : (k + 1) * 10, :] = value
        band = ds.GetRasterBand(1)
        if table is not None:
            ct = gdal.ColorTable()
            for i in range(256):
                ct.SetColorEntry(i, table(i))
            band.SetColorTable(ct)
        band.SetNoDataValue(0)
        band.WriteArray(values)
        ds = None
        return path

    def test_gray_identity_table_lists_the_classes(self):
        path = self._write("gray.tif", lambda i: (i, i, i, 255))
        self.assertEqual(self.render_ranges.estimate_vrt_render_ranges(path).classes, [1, 2, 3, 5])

    def test_shifted_gray_ramp_is_also_a_gray_table(self):
        path = self._write("shifted.tif", lambda i: (max(i - 1, 0),) * 3 + (255,))
        self.assertEqual(self.render_ranges.estimate_vrt_render_ranges(path).classes, [1, 2, 3, 5])

    def test_a_real_palette_is_kept(self):
        path = self._write("color.tif", lambda i: (255 - i, i, 0, 255))
        self.assertIsNone(self.render_ranges.estimate_vrt_render_ranges(path).classes)

    def test_no_table_is_a_continuous_band(self):
        path = self._write("plain.tif", None)
        self.assertIsNone(self.render_ranges.estimate_vrt_render_ranges(path).classes)

    def test_table_is_read_from_the_source_when_the_sample_is_an_overview(self):
        gray = self._write("gray.tif", lambda i: (i, i, i, 255))
        plain = self._write("ovr.tif", None)
        sample_band = self.gdal.Open(plain).GetRasterBand(1)
        self.assertTrue(self.render_ranges._has_gray_table(sample_band, plain, gray))
        self.assertFalse(self.render_ranges._has_gray_table(sample_band, plain, plain))

    def test_continuous_byte_band_with_gray_table_stays_continuous(self):
        gdal = self.gdal
        path = os.path.join(self.tmp, "hillshade.tif")
        ds = gdal.GetDriverByName("GTiff").Create(path, 256, 4, 1, gdal.GDT_Byte)
        ds.SetGeoTransform((0, 1, 0, 4, 0, -1))
        band = ds.GetRasterBand(1)
        ct = gdal.ColorTable()
        for i in range(256):
            ct.SetColorEntry(i, (i, i, i, 255))
        band.SetColorTable(ct)
        band.WriteArray(np.tile(np.arange(256, dtype=np.uint8), (4, 1)))
        ds = None
        self.assertIsNone(self.render_ranges.estimate_vrt_render_ranges(path).classes)


class TestConstantRange(unittest.TestCase):
    def test_uniform_area_gets_a_centred_range(self):
        import numpy as np

        from bdc_loader_plugin.core.render_ranges import _constant_range

        self.assertEqual(_constant_range(np.full((4, 4), 1023), 0), (1022.0, 1024.0))
        self.assertIsNone(_constant_range(np.zeros((4, 4)), None))
        self.assertIsNone(_constant_range(np.array([1, 2, 2]), None))
        self.assertIsNone(_constant_range(np.full((2, 2), -9999.0), -9999.0))
