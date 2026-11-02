"""File names and formats written by downloads (core/download_outputs.py)."""

import os

from bdc_loader_plugin.core import download_outputs as out


class _Settings:
    def __init__(self):
        self.values = {}

    def value(self, key, default=None):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value


def test_crop_tag_is_the_corner_coordinates():
    bbox = (-47.95, -15.85, -47.85, -15.75)

    assert out.crop_tag(bbox) == "crop-47.950W-15.850S-47.850W-15.750S"
    assert out.crop_label(bbox) == "47.950W 15.850S to 47.850W 15.750S"


def test_nearby_crops_get_different_tags():
    """The case that made two areas share files: same centre, different box."""
    a = (-47.95, -15.85, -47.85, -15.75)
    b = (-47.952, -15.848, -47.848, -15.752)

    assert out.crop_tag(a) != out.crop_tag(b)


def test_area_tag_joins_layer_and_feature_without_underscore():
    assert out.area_tag("MGRS", "23LKC") == "MGRS-23LKC"
    assert out.area_tag("fazendas_2024", "São José", None) == "fazendas-2024-Sao-Jose"
    assert "_" not in out.area_tag("a_b", "c_d", "fid7")


def test_sits_name_has_five_fields():
    name = out.sits_file_name("S2-16D-2", "epsg4326", "031_021", "B8A", "2024-01-01")

    assert name == "S2-16D-2_epsg4326_031-021_B8A_2024-01-01.tif"
    assert len(name[:-4].split("_")) == 5


def test_tile_per_band_native_keeps_the_names_the_vrt_builder_reads():
    plan = out.tile_outputs("/d", "S2-16D-2", "S2_ITEM", ["B04", "B03"], out.PER_BAND)

    assert [os.path.basename(p) for _b, p in plan.band_files] == ["S2_ITEM_B04.tif", "S2_ITEM_B03.tif"]
    assert plan.multiband is None and plan.vrt is None


def test_tile_multiband_and_vrt_names_carry_bands_and_projection():
    multi = out.tile_outputs("/d", "S2-16D-2", "ITEM", ["B04", "B03", "B02"], out.MULTIBAND, "epsg4326")
    vrt = out.tile_outputs("/d", "S2-16D-2", "ITEM", ["B04", "B03", "B02"], out.PER_BAND_VRT, "epsg4326")

    assert os.path.basename(multi.multiband) == "ITEM_B04-B03-B02_epsg4326.tif"
    assert multi.band_files == []
    assert os.path.basename(vrt.vrt) == "ITEM_B04-B03-B02_epsg4326.vrt"
    assert [os.path.basename(p) for _b, p in vrt.band_files][0] == "ITEM_B04_epsg4326.tif"


def test_one_band_is_always_a_single_file():
    for fmt in out.FORMATS:
        plan = out.area_outputs("/d", "C", "area-1", "2024-01-01", ["B04"], fmt)
        assert plan.paths() == [os.path.join("/d", "downloads", "C", "area-1", "area-1_2024-01-01_B04.tif")]


def test_sits_applies_only_to_per_band():
    sits = out.area_outputs("/d", "C", "area-1", "2024-01-01", ["B04"], out.PER_BAND, sits=True)
    vrt = out.area_outputs("/d", "C", "area-1", "2024-01-01", ["B04", "B03"], out.PER_BAND_VRT, sits=True)

    assert sits.paths() == [os.path.join("/d", "downloads", "C", "sits", "C_native_area-1_B04_2024-01-01.tif")]
    assert all("sits" not in p for p in vrt.paths())


def test_find_area_layer_prefers_requested_projection_order():
    present = {
        out.area_outputs("/d", "C", "a", "2024-01-01", ["B04", "B03"], out.MULTIBAND, "epsg4326").multiband,
    }
    found = out.find_area_layer("/d", "C", "a", "2024-01-01", ["B04", "B03"], ("", "epsg4326"), present.__contains__)

    assert found.endswith("a_2024-01-01_B04-B03_epsg4326.tif")
    assert out.find_area_layer("/d", "C", "a", "2024-01-01", ["B04"], ("",), present.__contains__) is None


def test_stored_format_round_trip_and_unknown_values():
    settings = _Settings()
    assert out.stored_format(settings) == (out.PER_BAND, False)

    out.save_format(settings, out.MULTIBAND, True)
    assert out.stored_format(settings) == (out.MULTIBAND, True)

    settings.values[out.FORMAT_SETTING] = "zip"
    assert out.stored_format(settings)[0] == out.PER_BAND


class TestFindAreaBandFiles:
    def test_per_band_download_is_found_in_band_order(self):
        from bdc_loader_plugin.core.download_outputs import PER_BAND, area_outputs, find_area_band_files

        plan = area_outputs("/d", "landsat-2", "crop-x", "2026-07-24", ["red", "green", "blue"], PER_BAND)
        on_disk = set(plan.paths())

        found = find_area_band_files(
            "/d", "landsat-2", "crop-x", "2026-07-24", ["red", "green", "blue"], exists=on_disk.__contains__
        )

        assert found == [path for _band, path in plan.band_files]
        assert found[0].endswith("crop-x_2026-07-24_red.tif")

    def test_sits_named_download_is_found(self):
        from bdc_loader_plugin.core.download_outputs import PER_BAND, area_outputs, find_area_band_files

        plan = area_outputs("/d", "landsat-2", "crop-x", "2026-07-24", ["red", "green"], PER_BAND, sits=True)
        on_disk = set(plan.paths())

        assert find_area_band_files(
            "/d", "landsat-2", "crop-x", "2026-07-24", ["red", "green"], exists=on_disk.__contains__
        ) == [path for _band, path in plan.band_files]

    def test_missing_band_gives_none(self):
        from bdc_loader_plugin.core.download_outputs import PER_BAND, area_outputs, find_area_band_files

        plan = area_outputs("/d", "landsat-2", "crop-x", "2026-07-24", ["red", "green", "blue"], PER_BAND)
        on_disk = set(plan.paths()[:2])

        assert (
            find_area_band_files(
                "/d", "landsat-2", "crop-x", "2026-07-24", ["red", "green", "blue"], exists=on_disk.__contains__
            )
            is None
        )
