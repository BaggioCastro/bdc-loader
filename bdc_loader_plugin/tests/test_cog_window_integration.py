#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Block-window copies of a COG (core/cog_window.py) and crop VRTs cut by a
mask band (core/vrt_builder.attach_area_mask), against a real GDAL and a local
HTTP server.

A tiled COG is generated on disk and served with Range support, read through
/vsicurl/ exactly like a BDC asset, and every crop made from the block copy
is compared pixel by pixel with the same crop made from the original file.
Marked ``integration`` and ``gdal`` like test_gdal_integration.py; skipped
without a real GDAL binding. No internet access.
"""

import contextlib
import os
import shutil
import sys
import tempfile
import unittest

import pytest

from bdc_loader_plugin.core import cutline, overview_cache, overviews, raster_export
from bdc_loader_plugin.tests.test_download_engine import _RangeHTTPHandler, _TestServer
from bdc_loader_plugin.tests.test_gdal_integration import _REAL

from .real_osgeo import patch_plugin_osgeo

pytestmark = [
    pytest.mark.gdal,
    pytest.mark.skipif(_REAL is None, reason="real GDAL Python binding not available"),
]


@contextlib.contextmanager
def _real_gdal():
    real_gdal, real_ogr, real_osr, real_mods = _REAL
    import bdc_loader_plugin.core.cog_window as cw
    import bdc_loader_plugin.core.crop_preview  # noqa: F401  (patched with the real bindings)
    import bdc_loader_plugin.core.vrt_builder as vb

    saved = {k: sys.modules[k] for k in list(sys.modules) if k == "osgeo" or k.startswith("osgeo.")}
    for k in list(saved):
        del sys.modules[k]
    sys.modules.update(real_mods)
    try:
        with contextlib.ExitStack() as stack:
            patch_plugin_osgeo(stack, real_gdal, real_ogr, real_osr)
            yield real_gdal, real_osr, cw, None, vb
    finally:
        for k in list(sys.modules):
            if k == "osgeo" or k.startswith("osgeo."):
                del sys.modules[k]
        sys.modules.update(saved)


class TestCogWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = _TestServer()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def setUp(self):
        _RangeHTTPHandler.routes.clear()
        self.work = tempfile.mkdtemp(prefix="bdc_cogwin_")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        from bdc_loader_plugin.core import download_engine

        self.engine = download_engine
        download_engine.reset_throttling()

    def _make_cog(self, gdal, name, bands=1):
        import numpy as np

        mem = gdal.GetDriverByName("MEM").Create("", 2048, 2048, bands, gdal.GDT_UInt16)
        mem.SetGeoTransform((500000.0, 10.0, 0.0, 9200000.0, 0.0, -10.0))
        srs = _REAL[2].SpatialReference()
        srs.ImportFromEPSG(32722)
        mem.SetProjection(srs.ExportToWkt())
        yy, xx = np.mgrid[0:2048, 0:2048]
        for b in range(1, bands + 1):
            mem.GetRasterBand(b).WriteArray(((xx * 7 + yy * 13 + b * 101) % 9000 + 1).astype("uint16"))
        path = os.path.join(self.work, name)
        gdal.Translate(path, mem, format="COG", creationOptions=["BLOCKSIZE=256", "COMPRESS=DEFLATE"])
        with open(path, "rb") as f:
            data = f.read()
        self.server.register(f"/{name}", data)
        return path, "/vsicurl/" + self.server.url(f"/{name}"), len(data)

    def _bbox(self, osr, x0, y0, x1, y1):
        """Lon/lat bbox of a UTM 22S rectangle."""
        src = osr.SpatialReference()
        src.ImportFromEPSG(32722)
        dst = osr.SpatialReference()
        dst.ImportFromEPSG(4326)
        for s in (src, dst):
            s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        tr = osr.CoordinateTransformation(src, dst)
        pts = [tr.TransformPoint(x, y)[:2] for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))]
        return [min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)]

    def _read(self, gdal, path):
        ds = gdal.Open(path)
        out = (ds.ReadAsArray(), ds.GetGeoTransform())
        ds = None
        return out

    def test_block_copy_crop_matches_the_original_and_fetches_a_fraction(self):
        import numpy as np

        with _real_gdal() as (gdal, osr, cw, _lc, vb):
            original, href, size = self._make_cog(gdal, "a.tif")
            bbox = self._bbox(osr, 503000, 9190000, 506000, 9193000)

            plan = cw.plan_window(href, cw.bbox_wkt(bbox))
            self.assertIsNotNone(plan)
            self.assertLess(plan.nbytes, size / 4)
            limiter = self.engine.ConnectionLimiter(8)
            session = self.engine.make_session(8, on_throttle=limiter.throttle)
            copy = cw.fetch(plan, os.path.join(self.work, "copy.tif"), session, limiter)
            session.close()
            self.assertTrue(cw.verify(plan, copy))

            ok_a, _ = raster_export.export_bbox_geotiff(original, bbox, os.path.join(self.work, "from_original.tif"))
            ok_b, _ = raster_export.export_bbox_geotiff(copy, bbox, os.path.join(self.work, "from_copy.tif"))
            self.assertTrue(ok_a and ok_b)
            a, gt_a = self._read(gdal, os.path.join(self.work, "from_original.tif"))
            b, gt_b = self._read(gdal, os.path.join(self.work, "from_copy.tif"))
            self.assertEqual(gt_a, gt_b)
            self.assertTrue(np.array_equal(a, b))
            self.assertGreater(int((a > 0).sum()), 0)

    def test_copy_with_a_damaged_index_fails_verification(self):
        with _real_gdal() as (gdal, osr, cw, _lc, _vb):
            _original, href, _size = self._make_cog(gdal, "b.tif")
            plan = cw.plan_window(href, cw.bbox_wkt(self._bbox(osr, 503000, 9190000, 506000, 9193000)))
            broken = os.path.join(self.work, "broken.tif")
            with open(broken, "wb") as f:
                f.truncate(plan.size)  # no header, no blocks

            self.assertFalse(cw.verify(plan, broken))

    def test_localize_is_all_or_nothing_under_a_budget(self):
        with _real_gdal() as (gdal, osr, cw, _lc, _vb):
            _o1, href1, _ = self._make_cog(gdal, "c1.tif")
            _o2, href2, _ = self._make_cog(gdal, "c2.tif")
            area = cw.bbox_wkt(self._bbox(osr, 503000, 9190000, 506000, 9193000))
            limiter = self.engine.ConnectionLimiter(8)
            session = self.engine.make_session(8, on_throttle=limiter.throttle)
            try:
                refused, n = cw.localize(
                    [href1, href2], area, os.path.join(self.work, "r"), session, limiter, budget=lambda nbytes: False
                )
                self.assertEqual((refused, n), ({}, 0))
                mapping, fetched = cw.localize(
                    [href1, href2, "/local/file.tif"], area, os.path.join(self.work, "ok"), session, limiter
                )
            finally:
                session.close()
            self.assertEqual(set(mapping), {href1, href2})
            self.assertGreater(fetched, 0)

    def test_plan_covers_the_window_the_crop_vrt_reads_in_a_rotated_grid(self):
        # BDC Albers is centred on 54W; at 47W its grid is rotated ~1.4 deg
        # against lon/lat, so the reprojected box of a triangle reaches
        # hundreds of metres past the reprojected triangle.
        import json

        import numpy as np

        albers = (
            'PROJCS["BDC Albers",GEOGCS["GRS80",DATUM["unknown",SPHEROID["GRS 1980",6378137,298.257222101]],'
            'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],PROJECTION["Albers_Conic_Equal_Area"],'
            'PARAMETER["latitude_of_center",-12],PARAMETER["longitude_of_center",-54],'
            'PARAMETER["standard_parallel_1",-2],PARAMETER["standard_parallel_2",-22],'
            'PARAMETER["false_easting",5000000],PARAMETER["false_northing",10000000],UNIT["metre",1]]'
        )
        with _real_gdal() as (gdal, osr, cw, _lc, vb):
            wgs = osr.SpatialReference()
            wgs.ImportFromEPSG(4326)
            dst = osr.SpatialReference()
            dst.ImportFromWkt(albers)
            for srs in (wgs, dst):
                srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
            cx, cy, _ = osr.CoordinateTransformation(wgs, dst).TransformPoint(-47.2, -21.2)
            gt = (round(cx) - 20480.0, 10.0, 0.0, round(cy) + 20480.0, 0.0, -10.0)
            mem = gdal.GetDriverByName("MEM").Create("", 4096, 4096, 1, gdal.GDT_UInt16)
            mem.SetGeoTransform(gt)
            mem.SetProjection(albers)
            mem.GetRasterBand(1).WriteArray(np.full((4096, 4096), 7, dtype="uint16"))
            path = os.path.join(self.work, "albers.tif")
            gdal.Translate(path, mem, format="COG", creationOptions=["BLOCKSIZE=256", "COMPRESS=DEFLATE"])
            with open(path, "rb") as f:
                self.server.register("/albers.tif", f.read())
            href = "/vsicurl/" + self.server.url("/albers.tif")

            ring = [[-47.30, -21.30], [-47.10, -21.28], [-47.18, -21.10], [-47.30, -21.30]]
            cut = os.path.join(self.work, "tri_albers.geojson")
            with open(cut, "w") as f:
                json.dump(
                    {
                        "type": "FeatureCollection",
                        "features": [
                            {
                                "type": "Feature",
                                "properties": {},
                                "geometry": {"type": "Polygon", "coordinates": [ring]},
                            }
                        ],
                    },
                    f,
                )

            plan = cw.plan_window(href, cw.area_wkt_from_cutline(cut))
            xmin, ymin, xmax, ymax = cutline._aligned_clip_bounds(cut, path)
            clip = (
                round((xmin - gt[0]) / gt[1]),
                round((ymax - gt[3]) / gt[5]),
                round((xmax - gt[0]) / gt[1]),
                round((ymin - gt[3]) / gt[5]),
            )
            x0, y0, x1, y1 = plan.window
            self.assertLessEqual(x0, clip[0])
            self.assertLessEqual(y0, clip[1])
            self.assertGreaterEqual(x1, clip[2])
            self.assertGreaterEqual(y1, clip[3])

    def test_mask_band_cuts_the_vrt_to_the_shape_and_is_shared_between_dates(self):
        import json

        import numpy as np

        with _real_gdal() as (gdal, osr, _cw, _lc, vb):
            original, href, _ = self._make_cog(gdal, "m.tif", bands=3)
            x0, y0, x1, y1 = self._bbox(osr, 503000, 9188000, 512000, 9197000)
            cut = os.path.join(self.work, "shape.geojson")
            ring = [[x0, y0], [x1, y0], [x0, y1], [x0, y0]]  # lower-left half of the box
            with open(cut, "w") as f:
                json.dump(
                    {
                        "type": "FeatureCollection",
                        "features": [
                            {
                                "type": "Feature",
                                "properties": {},
                                "geometry": {"type": "Polygon", "coordinates": [ring]},
                            }
                        ],
                    },
                    f,
                )
            vrts = []
            for date in ("d1", "d2"):
                path = os.path.join(self.work, f"{date}.vrt")
                full = os.path.join(self.work, f"{date}_full.vrt")
                gdal.BuildVRT(full, [href])
                self.assertTrue(cutline._bbox_clip(cut, full, path))
                self.assertTrue(vb.attach_area_mask(path, cut, os.path.join(self.work, "masks")))
                self.assertTrue(vb.vrt_has_mask_band(path))
                vrts.append(path)
            self.assertEqual(len(os.listdir(os.path.join(self.work, "masks"))), 1)  # one mask, both dates

            ds = gdal.Open(vrts[0])
            mask = ds.GetRasterBand(1).GetMaskBand().ReadAsArray()
            flags = ds.GetRasterBand(1).GetMaskFlags()
            data = ds.GetRasterBand(1).ReadAsArray()
            ds = None
            self.assertEqual(flags, gdal.GMF_PER_DATASET)
            self.assertEqual(set(np.unique(mask).tolist()), {0, 255})
            h, w = mask.shape
            self.assertEqual(mask[h - 2, 1], 255)  # lower-left corner: inside the triangle
            self.assertEqual(mask[1, w - 2], 0)  # upper-right corner: outside
            self.assertTrue((data[mask == 255] > 0).all())  # the data under the shape is intact

    def test_overview_is_rebuilt_when_its_vrt_changes(self):
        with _real_gdal() as (gdal, _osr, _cw, _lc, vb):
            original, _href, _ = self._make_cog(gdal, "o.tif")
            vrt = os.path.join(self.work, "o.vrt")
            gdal.BuildVRT(vrt, [original])
            ovr = overviews.build_overview(vrt)
            self.assertTrue(ovr and overview_cache._overview_is_current(ovr, vrt))
            with open(vrt, "a") as f:
                f.write("\n")  # any change to the VRT
            self.assertFalse(overview_cache._overview_is_current(ovr, vrt))

    def test_crop_preview_shows_the_area_and_clears_the_outside(self):
        from types import SimpleNamespace

        import numpy as np

        import bdc_loader_plugin.core.crop_preview as cp

        with _real_gdal() as (gdal, osr, cw, _lc, _vb):
            _original, href, _ = self._make_cog(gdal, "p.tif", bands=1)
            url = href[len("/vsicurl/") :]
            items = [SimpleNamespace(assets={b: SimpleNamespace(href=url) for b in ("r", "g", "b")})]
            x0, y0, x1, y1 = self._bbox(osr, 503000, 9188000, 512000, 9197000)
            triangle = f"POLYGON(({x0} {y0},{x1} {y0},{x0} {y1},{x0} {y0}))"

            data = cp.render_preview(items, ["r", "g", "b"], [x0, y0, x1, y1], triangle, size=64)

            self.assertTrue(data and data.startswith(b"\x89PNG"))
            path = os.path.join(self.work, "preview.png")
            with open(path, "wb") as f:
                f.write(data)
            ds = gdal.Open(path)
            alpha = ds.GetRasterBand(4).ReadAsArray()
            red = ds.GetRasterBand(1).ReadAsArray()
            ds = None
            h, w = alpha.shape
            self.assertEqual(max(h, w), 64)
            self.assertEqual(alpha[h - 3, 2], 255)  # inside the triangle
            self.assertEqual(alpha[2, w - 3], 0)  # outside
            self.assertGreater(int(np.ptp(red[alpha == 255])), 0)  # stretched, not flat
