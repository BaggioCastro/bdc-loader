"""Downloaded images found and loaded without the BDC (core/local_catalog.py)."""

import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace

from bdc_loader_plugin.core import local_catalog as lc

BBOX = (-47.3, -21.3, -47.05, -21.05)


def _reader(counts):
    """GDAL stand-in: band count by file name (1 when absent) and one bbox for every file."""
    return lambda path: (counts.get(os.path.basename(path), 1), BBOX)


class TestScanDownloads(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def _touch(self, *parts):
        path = os.path.join(self.root, "downloads", *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"tif")
        return path

    def _scan(self, counts=None):
        lc._FACTS_CACHE.clear()
        return {i.item_id: i for i in lc.scan_downloads(self.root, reader=_reader(counts or {}))}

    def test_scene_downloaded_per_band_is_one_image_with_its_date_and_tile(self):
        b04 = self._touch("S2-16D-2", "S2-16D_V2_033008_20230712", "S2-16D_V2_033008_20230712_B04.tif")
        self._touch("S2-16D-2", "S2-16D_V2_033008_20230712", "S2-16D_V2_033008_20230712_B03.tif")

        image = self._scan()["S2-16D_V2_033008_20230712"]

        self.assertEqual((image.kind, image.date, image.tile), ("scene", "2023-07-12", "033008"))
        self.assertEqual(sorted(image.band_files), ["B03", "B04"])
        self.assertEqual(image.band_files["B04"], b04)
        self.assertIsNone(image.layer_file)

    def test_crop_dates_are_separate_images_and_a_stack_keeps_its_band_order(self):
        area = "crop-47.300W-21.300S-47.050W-21.050S"
        for date in ("2024-09-29", "2024-10-15"):
            self._touch("S2-16D-2", area, f"{area}_{date}_B04-B03-B02.tif")

        images = self._scan({f"{area}_2024-09-29_B04-B03-B02.tif": 3, f"{area}_2024-10-15_B04-B03-B02.tif": 3})

        image = images[f"{area}_2024-10-15"]
        self.assertEqual((image.kind, image.date, image.tile), ("area", "2024-10-15", area))
        self.assertEqual(image.layer_bands, ("B04", "B03", "B02"))
        self.assertEqual(len(images), 2)

    def test_band_names_with_underscores_and_a_projection_tag(self):
        self._touch("sentinel-1-rtc-1", "S1D_IW_X_20260426", "S1D_IW_X_20260426_Gamma0_VV_epsg4326.tif")

        image = self._scan()["S1D_IW_X_20260426"]

        self.assertEqual(list(image.band_files), ["Gamma0_VV"])
        self.assertEqual(image.projection, "epsg4326")

    def test_earlier_crops_with_an_alpha_band_and_unfinished_files(self):
        self._touch("S2-16D-2", "crop_Crop_14_8S_45_9W_2026-05-25_B11-B08-B02_masked.tif")
        partial = self._touch("S2-16D-2", "S2-16D_V2_017017_20260626", "S2-16D_V2_017017_20260626_B02.tif")
        self._touch("S2-16D-2", "S2-16D_V2_017017_20260626", "S2-16D_V2_017017_20260626_B02.tif.part")

        images = self._scan({"crop_Crop_14_8S_45_9W_2026-05-25_B11-B08-B02_masked.tif": 4})

        self.assertEqual(images["crop_Crop_14_8S_45_9W_2026-05-25"].layer_bands, ("B11", "B08", "B02"))
        self.assertNotIn("S2-16D_V2_017017_20260626", images, f"{partial} is still being written")

    def test_sits_names_are_read_back(self):
        self._touch("S2-16D-2", "sits", "S2-16D-2_native_033008_B04_2023-07-12.tif")

        image = self._scan()["033008_2023-07-12"]

        self.assertEqual((image.tile, image.date, list(image.band_files)), ("033008", "2023-07-12", ["B04"]))


class TestSearchLocal(unittest.TestCase):
    def _image(self, item_id, date, tile, kind="scene", collection="S2-16D-2", bbox=BBOX):
        return lc.LocalImage(collection, item_id, date, tile, kind, band_files={"B04": "/x.tif"}, bbox=bbox)

    def test_collection_period_tiles_and_area_filter_like_the_online_search(self):
        images = [
            self._image("a", "2023-07-12", "033008"),
            self._image("b", "2023-07-12", "033009"),
            self._image("c", "2024-01-01", "033008"),
            self._image("d", "2023-07-12", "033008", collection="LANDSAT-16D-1"),
            self._image("e", "2023-08-01", "crop-x", kind="area"),
            self._image("f", "2023-09-01", "033008", bbox=(10.0, 10.0, 11.0, 11.0)),
            self._image("g", "", "033008"),
        ]

        by_tile = lc.search_local(images, "S2-16D-2", "2023-01-01", "2023-12-31", tiles=["033008"])
        by_area = lc.search_local(images, "S2-16D-2", "2023-01-01", "2023-12-31", bbox=(-47.2, -21.2, -47.1, -21.1))

        self.assertEqual([i.item_id for i in by_tile], ["f", "a"])
        self.assertEqual([i.item_id for i in by_area], ["e", "b", "a"])

    def test_dates_are_read_from_item_ids(self):
        self.assertEqual(lc.date_from_id("CBERS_4_AWFI_20260727_180_135_L2"), "2026-07-27")
        self.assertEqual(lc.date_from_id("MOD13Q1.A2026241.h09v08.061.2026257233917"), "2026-08-29")
        self.assertEqual(lc.date_from_id("no-date-here"), "")


class TestLocalItemsLoadFromDisk(unittest.TestCase):
    def test_item_assets_are_the_files_and_a_stack_offers_its_bands(self):
        from bdc_loader_plugin.core.band_selection import band_availability_issues

        scene = lc.LocalImage("S2-16D-2", "s", "2023-07-12", "033008", "scene", band_files={"B04": "/d/s_B04.tif"})
        stack = lc.LocalImage(
            "S2-16D-2", "c_2024-10-15", "2024-10-15", "c", "area", layer_file="/d/c.tif", layer_bands=("B04", "B03")
        )
        scene_item, stack_item = lc.to_stac_item(scene), lc.to_stac_item(stack)

        self.assertEqual(scene_item.assets["B04"].href, "/d/s_B04.tif")
        self.assertEqual(stack_item.properties["bdc:local_layer"], "/d/c.tif")
        self.assertEqual(band_availability_issues(["B04", "B03"], [stack_item]), [])
        self.assertEqual(band_availability_issues(["B08"], [stack_item])[0][1], ["B08"])

    def test_band_source_is_the_local_file_not_a_vsicurl_url(self):
        from bdc_loader_plugin.core.vrt_tasks import _band_href

        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        path = os.path.join(root, "elsewhere_B04.tif")
        with open(path, "wb") as f:
            f.write(b"tif")
        item = SimpleNamespace(id="crop_2024-10-15", assets={"B04": SimpleNamespace(href=path)})
        remote = SimpleNamespace(id="x", assets={"B04": SimpleNamespace(href="https://data/x_B04.tif")})

        self.assertEqual(_band_href("B04", item, root, "S2-16D-2"), path)
        self.assertEqual(_band_href("B04", remote, root, "S2-16D-2"), "/vsicurl/https://data/x_B04.tif")

    def test_a_downloaded_stack_loads_as_it_is(self):
        from bdc_loader_plugin.core.vrt_tasks import _local_layer

        stack = lc.LocalImage(
            "S2-16D-2", "c_2024-10-15", "2024-10-15", "c", "area", layer_file="/d/c.tif", layer_bands=("B04", "B03")
        )
        item = lc.to_stac_item(stack)

        path, layer_name, group = _local_layer(item, item.properties, "S2-16D-2", "2024-10-15", "stac")

        self.assertEqual(path, "/d/c.tif")
        self.assertEqual(group, "S2-16D-2 / c")
        self.assertIn("c_2024-10-15", layer_name)


if __name__ == "__main__":
    unittest.main()
