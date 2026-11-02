"""Timeline layer-name compatibility tests."""

from bdc_loader_plugin.widgets.timeline_slider import _parse_vrt_layer_name


def test_compact_single_band_name_without_group():
    assert _parse_vrt_layer_name("S2-16D-2_001014_2026-06-10_B04") == (
        "S2-16D-2",
        "001014",
        "2026-06-10",
        "B04",
    )


def test_compact_legacy_rgb_name_with_group():
    assert _parse_vrt_layer_name(
        "landsat-2_228061_2008-11-21_red_green_blue",
        group_name="landsat-2 / 228061",
    ) == (
        "landsat-2",
        "228061",
        "2008-11-21",
        "red_green_blue",
    )


def test_compact_current_rgb_name_with_group():
    assert _parse_vrt_layer_name(
        "landsat-2_228061_2008-11-21_red-green-blue",
        group_name="landsat-2 / 228061",
    ) == (
        "landsat-2",
        "228061",
        "2008-11-21",
        "red-green-blue",
    )


def test_stac_sentinel2_name_uses_group_and_item_acquisition_date():
    assert _parse_vrt_layer_name(
        "S2C_MSIL2A_20260707T132231_N0512_R038_T22KEU_20260707T175011_nir08-red-green",
        group_name="S2_L2A-1 / 22KEU",
        known_bands=("nir08", "red", "green"),
    ) == (
        "S2_L2A-1",
        "22KEU",
        "2026-07-07",
        "nir08-red-green",
    )


def test_stac_landsat_name_uses_first_date_and_known_band_suffix():
    assert _parse_vrt_layer_name(
        "LT05_L2SP_228061_20081121_20200828_02_T1_red",
        group_name="landsat-2 / 228061",
        known_bands=("red", "green", "blue"),
    ) == (
        "landsat-2",
        "228061",
        "2008-11-21",
        "red",
    )


def test_stac_sentinel1_preserves_band_name_with_underscore():
    item_id = "S1A_IW_RTCH_1SDV_20260620_065050_0832F0_8892"
    assert _parse_vrt_layer_name(
        f"{item_id}_Gamma0_VH",
        group_name=f"sentinel-1-rtc-1 / {item_id}",
    ) == (
        "sentinel-1-rtc-1",
        item_id,
        "2026-06-20",
        "Gamma0_VH",
    )


def test_extent_crop_uses_same_spatial_identity_across_dates():
    crop_id = "Crop_23_5S_45_7W_to_23_2S_45_4W"
    first = _parse_vrt_layer_name(
        f"sentinel-1-rtc-1_{crop_id}_2026-06-20_Gamma0_VH",
        group_name="sentinel-1-rtc-1 / Crop 2026-06-20",
        known_bands=("Gamma0_VH", "Gamma0_VV"),
    )
    second = _parse_vrt_layer_name(
        f"sentinel-1-rtc-1_{crop_id}_2026-06-21_Gamma0_VH",
        group_name="sentinel-1-rtc-1 / Crop 2026-06-21",
        known_bands=("Gamma0_VH", "Gamma0_VV"),
    )

    assert first == ("sentinel-1-rtc-1", crop_id, "2026-06-20", "Gamma0_VH")
    assert second == ("sentinel-1-rtc-1", crop_id, "2026-06-21", "Gamma0_VH")
    assert (first[0], first[1], first[3]) == (second[0], second[1], second[3])


def test_extent_crop_name_is_self_contained_without_layer_group():
    assert _parse_vrt_layer_name("sentinel-1-rtc-1_Crop_23_5S_45_7W_to_23_2S_45_4W_2026-06-20_Gamma0_VH") == (
        "sentinel-1-rtc-1",
        "Crop_23_5S_45_7W_to_23_2S_45_4W",
        "2026-06-20",
        "Gamma0_VH",
    )


def test_shape_mosaic_uses_feature_group_as_stable_spatial_identity():
    first = _parse_vrt_layer_name(
        "sentinel-1-rtc-1_Fazenda_Sao_Jose_2026-06-20_Gamma0_VH",
        group_name="sentinel-1-rtc-1 / Fazenda_Sao_Jose",
        known_bands=("Gamma0_VH", "Gamma0_VV"),
    )
    second = _parse_vrt_layer_name(
        "sentinel-1-rtc-1_Fazenda_Sao_Jose_2026-06-21_Gamma0_VH",
        group_name="sentinel-1-rtc-1 / Fazenda_Sao_Jose",
        known_bands=("Gamma0_VH", "Gamma0_VV"),
    )

    assert first == ("sentinel-1-rtc-1", "Fazenda_Sao_Jose", "2026-06-20", "Gamma0_VH")
    assert second == ("sentinel-1-rtc-1", "Fazenda_Sao_Jose", "2026-06-21", "Gamma0_VH")
    assert (first[0], first[1], first[3]) == (second[0], second[1], second[3])


def test_stac_name_without_group_is_not_guessed():
    assert (
        _parse_vrt_layer_name(
            "S2C_MSIL2A_20260707T132231_T22KEU_red",
            known_bands=("red",),
        )
        is None
    )
