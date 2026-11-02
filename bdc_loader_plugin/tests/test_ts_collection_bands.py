"""Band list built for the time series panel from STAC item_assets."""

from unittest.mock import MagicMock, patch

_COG = "image/tiff; application=geotiff; profile=cloud-optimized"

# Shape of the landsat-2 collection on the BDC STAC: raster bands next to
# scene metadata sidecars that also carry the "data" role.
_LANDSAT = {
    "id": "landsat-2",
    "title": "Landsat Collection 2 - Level-2",
    "bdc:type": "collection",
    "extent": {"temporal": {"interval": [["1985-01-07T00:00:00Z", "2026-10-08T00:00:00Z"]]}},
    "item_assets": {
        "blue": {"type": _COG, "roles": ["data"]},
        "nir08": {"type": _COG, "roles": ["data"]},
        "qa_pixel": {"type": _COG, "roles": ["data"]},
        "ang": {"type": "text/plain", "roles": ["data"]},
        "mtl.txt": {"type": "text/plain", "roles": ["data"]},
        "mtl.json": {"type": "application/json", "roles": ["data"]},
        "mtl.xml": {"type": "application/xml", "roles": ["data"]},
        "sr_stac": {"type": "application/json", "roles": ["data"]},
        "thumbnail": {"type": "image/png", "roles": ["thumbnail"]},
    },
}


def _load(collections):
    import bdc_loader_plugin.core.ts_collections as module

    manager = module.TSCollectionManager.__new__(module.TSCollectionManager)
    manager._set_status = MagicMock()
    manager._populate_collection_combo = MagicMock()
    with (
        patch.object(module, "_fetch_all_stac_collections", return_value=collections),
        patch.object(module, "is_supported_image_collection", return_value=True),
    ):
        manager._load_collections_from_plugin()
    return manager


def test_metadata_assets_are_not_offered_as_bands():
    manager = _load([_LANDSAT])

    config = next(cfg for cfg in manager._collections.values() if cfg["id"] == "landsat-2")
    assert sorted(config["bands"]) == ["blue", "nir08", "qa_pixel"]


def test_collection_temporal_extent_is_kept_for_the_period_slider():
    manager = _load([_LANDSAT])

    config = next(cfg for cfg in manager._collections.values() if cfg["id"] == "landsat-2")
    assert config["temporal"] == ("1985-01-07", "2026-10-08")
