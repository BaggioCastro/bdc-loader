"""A load shown on the map turns on one date per series, so the canvas reads one image per series."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from bdc_loader_plugin.core import vrt_layers

KEY = ("S2-16D-2", "021018", "B11-B8A-B04")


def _layer(layer_id, name):
    return SimpleNamespace(id=lambda: layer_id, name=lambda: name)


def _info(layer, _root=None):
    parts = layer.name().split("_")
    return tuple(parts) if len(parts) == 4 else None


def _show(new_layers, earlier_layers=()):
    """Run _show_one_date_per_series; returns (its result, {layer id: last visibility set})."""
    all_layers = list(earlier_layers) + list(new_layers)
    nodes = {layer.id(): MagicMock() for layer in all_layers}
    root = MagicMock()
    root.findLayer.side_effect = nodes.get
    project = MagicMock()
    project.layerTreeRoot.return_value = root
    project.mapLayers.return_value = {layer.id(): layer for layer in all_layers}
    with (
        patch.object(vrt_layers, "_timeline_info_for_layer", side_effect=_info),
        patch.object(vrt_layers, "QgsProject", MagicMock(instance=MagicMock(return_value=project))),
    ):
        result = vrt_layers._show_one_date_per_series(new_layers)
    visibility = {
        lid: node.setItemVisibilityChecked.call_args.args[0]
        for lid, node in nodes.items()
        if node.setItemVisibilityChecked.called
    }
    return result, visibility


def test_only_the_earliest_date_of_a_series_is_turned_on():
    layers = [
        _layer("b", "S2-16D-2_021018_2023-09-30_B11-B8A-B04"),
        _layer("a", "S2-16D-2_021018_2023-09-14_B11-B8A-B04"),
        _layer("c", "S2-16D-2_021018_2023-10-16_B11-B8A-B04"),
    ]
    result, visibility = _show(layers)
    assert visibility == {"a": True, "b": False, "c": False}
    assert result == [(KEY, "a")]


def test_a_new_load_of_a_series_turns_off_its_earlier_dates():
    earlier = [
        _layer("jan", "S2-16D-2_021018_2023-01-01_B11-B8A-B04"),
        _layer("feb", "S2-16D-2_021018_2023-02-02_B11-B8A-B04"),
    ]
    new = [
        _layer("may", "S2-16D-2_021018_2023-05-09_B11-B8A-B04"),
        _layer("apr", "S2-16D-2_021018_2023-04-07_B11-B8A-B04"),
    ]
    result, visibility = _show(new, earlier)
    assert visibility == {"jan": False, "feb": False, "apr": True, "may": False}
    assert result == [(KEY, "apr")]


def test_each_band_composition_and_tile_keeps_its_own_date_on():
    layers = [
        _layer("rgb1", "S2-16D-2_021018_2023-09-14_B11-B8A-B04"),
        _layer("rgb2", "S2-16D-2_021018_2023-09-30_B11-B8A-B04"),
        _layer("ndvi1", "S2-16D-2_021018_2023-09-14_NDVI"),
        _layer("other1", "S2-16D-2_022018_2023-09-30_B11-B8A-B04"),
    ]
    result, visibility = _show(layers)
    assert {lid for lid, on in visibility.items() if on} == {"rgb1", "ndvi1", "other1"}
    # Sorted by series key, so the series the timeline shows does not depend on build order.
    assert [layer_id for _key, layer_id in result] == ["rgb1", "ndvi1", "other1"]


def test_series_not_in_this_load_and_undated_layers_are_left_as_they_are():
    untouched = _layer("other_tile", "S2-16D-2_099099_2023-01-01_B11-B8A-B04")
    plain = _layer("p", "mosaic")
    result, visibility = _show([plain], [untouched])
    assert result == []
    assert visibility == {}
