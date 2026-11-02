"""The timeline follows the layer made active, also when it joined a known group after the last scan."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from bdc_loader_plugin.widgets import timeline_slider
from bdc_loader_plugin.widgets.timeline_slider import VRTTimelineSlider

KEY = ("S2-16D-2", "001014", "red-green-blue")


def _layer(layer_id, date):
    return SimpleNamespace(
        id=lambda: layer_id,
        name=lambda: f"S2-16D-2_001014_{date}_red-green-blue",
        type=lambda: "raster",
        RasterLayer="raster",
        date=date,
    )


def _timeline():
    timeline = VRTTimelineSlider.__new__(VRTTimelineSlider)
    timeline._groups = {}
    timeline._current_key = None
    timeline._current_idx = 0
    timeline._enabled = True
    timeline._update_tile_combo = MagicMock()
    timeline._update_ui_state = MagicMock()
    timeline.setVisible = MagicMock()
    return timeline


def _project(layers):
    project = MagicMock()
    project.mapLayers.return_value = {layer.id(): layer for layer in layers}
    return project


def _info(layer):
    return KEY[0], KEY[1], layer.date, KEY[2]


def test_a_layer_added_to_a_group_already_on_the_timeline_becomes_its_position():
    first, second = _layer("a", "2023-01-01"), _layer("b", "2023-01-17")
    added = _layer("c", "2023-02-02")
    timeline = _timeline()

    with (
        patch.object(timeline_slider, "_timeline_info_for_layer", side_effect=_info),
        patch.object(timeline_slider.QgsProject, "instance", return_value=_project([first, second])),
    ):
        timeline.scan_project_layers()
        timeline._current_idx = 0
    with (
        patch.object(timeline_slider, "_timeline_info_for_layer", side_effect=_info),
        patch.object(timeline_slider.QgsProject, "instance", return_value=_project([first, second, added])),
    ):
        timeline._on_active_layer_changed(added)

    assert [e["layer_id"] for e in timeline._groups[KEY]] == ["a", "b", "c"]
    assert timeline.position() == (KEY, 2)


def test_a_layer_already_on_the_timeline_does_not_trigger_a_new_scan():
    first, second = _layer("a", "2023-01-01"), _layer("b", "2023-01-17")
    timeline = _timeline()

    with (
        patch.object(timeline_slider, "_timeline_info_for_layer", side_effect=_info),
        patch.object(timeline_slider.QgsProject, "instance", return_value=_project([first, second])),
    ):
        timeline.scan_project_layers()
        with patch.object(timeline, "scan_project_layers") as scan:
            timeline._on_active_layer_changed(second)

    scan.assert_not_called()
    assert timeline.position() == (KEY, 1)
