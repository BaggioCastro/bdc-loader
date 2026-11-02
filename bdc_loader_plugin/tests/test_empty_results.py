"""Results with no valid pixel are reported instead of loading or downloading silently blank."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

from bdc_loader_plugin.core import render_ranges


def _dataset(*bands, nodata=0.0):
    ds = MagicMock()
    ds.RasterXSize, ds.RasterYSize, ds.RasterCount = 8, 8, len(bands)

    def _band(index):
        band = MagicMock()
        band.GetNoDataValue.return_value = nodata
        band.ReadAsArray.return_value = bands[index - 1]
        return band

    ds.GetRasterBand.side_effect = _band
    return ds


def test_has_valid_pixels_ignores_nodata_zero_and_nan():
    from bdc_loader_plugin.core.render_ranges import has_valid_pixels

    assert not has_valid_pixels(np.array([0, 0, np.nan]), nodata=-9999)
    assert not has_valid_pixels(np.array([-9999, -9999]), nodata=-9999)
    assert has_valid_pixels(np.array([0, 0, 812]), nodata=0)


def test_render_ranges_mark_an_all_nodata_sample_as_empty():
    import bdc_loader_plugin.core.vrt_builder as module

    blank = np.zeros((8, 8))
    with patch.object(module.gdal, "Open", return_value=_dataset(blank, blank, blank)):
        ranges = render_ranges.estimate_vrt_render_ranges("/tmp/x.vrt")

    assert ranges == {}
    assert ranges.empty is True


def test_render_ranges_with_data_are_not_empty():
    import bdc_loader_plugin.core.vrt_builder as module

    data = np.arange(64, dtype=float).reshape(8, 8) + 100
    with patch.object(module.gdal, "Open", return_value=_dataset(data)):
        ranges = render_ranges.estimate_vrt_render_ranges("/tmp/x.vrt")

    assert ranges.empty is False
    assert 1 in ranges


def test_unreadable_source_is_not_called_empty():
    import bdc_loader_plugin.core.vrt_builder as module

    with patch.object(module.gdal, "Open", return_value=None):
        assert render_ranges.estimate_vrt_render_ranges("/tmp/x.vrt").empty is False
        assert render_ranges.raster_has_valid_pixels("/tmp/x.tif") is None


def test_loading_warns_about_empty_layers_only():
    from bdc_loader_plugin.core.render_ranges import RenderRanges
    from bdc_loader_plugin.core.vrt_generator import VrtGenerator

    empty = RenderRanges()
    empty.empty = True
    full = RenderRanges({1: (1.0, 2.0)})
    dialog = SimpleNamespace(
        _render_ranges_cache={"/a.vrt": empty, "/b.vrt": full},
        _set_status=MagicMock(),
        iface=MagicMock(),
    )

    VrtGenerator._warn_empty_layers(dialog, [("/a.vrt", "scene_0731", "g"), ("/b.vrt", "scene_0724", "g")])

    message = dialog._set_status.call_args.args[0]
    assert "1 of 2 layers has no valid pixel" in message
    assert "scene_0731" in message and "scene_0724" not in message
    dialog.iface.messageBar().pushWarning.assert_called_once()


def test_loading_says_nothing_when_every_layer_has_data():
    from bdc_loader_plugin.core.vrt_generator import VrtGenerator

    dialog = SimpleNamespace(
        _render_ranges_cache={"/b.vrt": {1: (1.0, 2.0)}}, _set_status=MagicMock(), iface=MagicMock()
    )

    VrtGenerator._warn_empty_layers(dialog, [("/b.vrt", "scene", "g")])

    dialog._set_status.assert_not_called()


def test_download_of_an_empty_result_is_reported_as_empty():
    import bdc_loader_plugin.core.download as module

    dialog = MagicMock()
    dialog._download_regular_item.return_value = ("done", "/data/x")
    plan = MagicMock()
    plan.paths.return_value = ["/data/x/a_B04.tif", "/data/x/a_B03.tif", "/data/x/a.vrt"]
    dialog._plan_for.return_value = plan
    dialog._written_files_are_empty = lambda *a: module.DownloadManager._written_files_are_empty(dialog, *a)
    widget = MagicMock()
    widget.item = SimpleNamespace(id="scene", properties={})
    choice = module.DownloadChoice("per_band_vrt", SimpleNamespace(tag="", warp_srs=None), False)

    with patch.object(module, "raster_has_valid_pixels", return_value=False) as sample:
        assert module.DownloadManager._download_one(dialog, widget, ["B04", "B03"], choice) == ("empty", "/data/x")
    assert [c.args[0] for c in sample.call_args_list] == ["/data/x/a_B04.tif", "/data/x/a_B03.tif"]

    with patch.object(module, "raster_has_valid_pixels", side_effect=[False, True]):
        assert module.DownloadManager._download_one(dialog, widget, ["B04", "B03"], choice) == ("done", "/data/x")
