"""Collection display names."""

from bdc_loader_plugin.stac.parsers import build_display_name


def test_type_label_is_not_repeated():
    assert (
        build_display_name("mosaic-cbers4-brazil-3m-1", "CBERS-4/WFI 3M Mosaic", "mosaic")
        == "CBERS-4/WFI 3M Mosaic (mosaic-cbers4-brazil-3m-1)"
    )


def test_type_label_is_added_when_missing():
    assert build_display_name("x-1", "Sentinel-2 - Level 2A", "collection") == "Sentinel-2 Scenes (x-1)"
