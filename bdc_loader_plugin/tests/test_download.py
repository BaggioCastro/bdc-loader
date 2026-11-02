#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_download.py — Tests for core/download.py.

Covers: the LOCAL check, the shared download flow (options dialog, batch,
re-entrancy guard), crop/feature downloads in every format, STAC item
downloads in every format, prefetch, error/cancel handling, the background
export poller and _run_accelerated_downloads.

Run: python3 -m pytest bdc_loader_plugin/tests/test_download.py -v
"""

import functools
import http.server
import os
import shutil
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from bdc_loader_plugin.core import raster_export


class _FakeSettings:
    """QgsSettings stand-in backed by a dict."""

    def __init__(self, values=None):
        self.values = dict(values or {})

    def value(self, key, default=None, type=None):
        value = self.values.get(key, default)
        if type is bool:
            return str(value).lower() in ("true", "1")
        return value

    def setValue(self, key, value):
        self.values[key] = value


def _native_option():
    from bdc_loader_plugin.core import output_crs

    return output_crs.OutputCrsOption(output_crs.NATIVE, "Native", None, "")


def _wgs84_option():
    from bdc_loader_plugin.core import output_crs

    return output_crs.OutputCrsOption(output_crs.WGS84, "WGS 84", "EPSG:4326", "epsg4326")


def _choice(fmt="per_band", crs=None, sits=False):
    from bdc_loader_plugin.core.download import DownloadChoice

    return DownloadChoice(fmt, crs or _native_option(), sits)


def _bind(dialog, *names):
    """Give a MagicMock dialog the real DownloadManager methods ``names``."""
    import inspect

    import bdc_loader_plugin.core.download as module

    for name in names:
        attr = getattr(module.DownloadManager, name)
        if isinstance(inspect.getattr_static(module.DownloadManager, name), staticmethod):
            setattr(dialog, name, attr)
        else:
            setattr(dialog, name, functools.partial(attr, dialog))
    return dialog


def _make_dialog(download_dir):
    """A bare dialog exposing what DownloadManager's download paths use."""
    dialog = MagicMock()
    dialog._download_dir = download_dir
    dialog._cutline_for_item.return_value = "/tmp/feat_cutline.geojson"
    dialog._has_mixed_resolution.return_value = False
    dialog._download_cancelled = False
    dialog._run_accelerated_downloads.return_value = []
    dialog._run_masked_export.side_effect = lambda vrt, cut, dst, label, **kw: (True, dst)
    # The mosaic download's own steps run for real on the fake dialog.
    from bdc_loader_plugin.core.download import DownloadManager
    from bdc_loader_plugin.core.vrt_generator import VrtGenerator

    for name in ("_mosaic_source_items", "_prefetch_mosaic_tiles", "_mosaic_vrt_task", "_export_mosaic"):
        setattr(dialog, name, getattr(DownloadManager, name).__get__(dialog))
    dialog._composition_task = VrtGenerator._composition_task.__get__(dialog)
    return dialog


def _valid_raster_dataset():
    """A gdal.Open stand-in dataset that passes is_valid_local_raster (positive
    dimensions and one accessible band). The suite runs under a fake GDAL whose
    real Open returns None, so a genuinely local, finished tile is simulated by
    patching gdal.Open to return this."""
    ds = MagicMock()
    ds.RasterXSize = ds.RasterYSize = 8
    ds.RasterCount = 1
    ds.GetRasterBand.return_value = object()
    return ds


def _make_source_item(item_id, href="https://example.org/B04.tif", tile=None):
    properties = {"bdc:tiles": [tile]} if tile else {}
    assets = {"B04": SimpleNamespace(href=href), "B03": SimpleNamespace(href=href.replace("B04", "B03"))}
    return SimpleNamespace(id=item_id, assets=assets, properties=properties)


def _make_mosaic_item(source_items, area="Sao-Paulo-abc123", is_extent_crop=False):
    return SimpleNamespace(
        id=f"{area}_2024-01-01",
        datetime=None,
        properties={
            "bdc:is_shape_mosaic": True,
            "bdc:is_extent_crop": is_extent_crop,
            "bdc:feature_name": "Sao Paulo",
            "bdc:area_tag": area,
            "bdc:mosaic_date": "2024-01-01",
        },
        _source_items=source_items,
    )


def _make_tile_item(item_id="S2-16D_V2_031021_20240101", bands=("B04", "B03", "B02")):
    assets = {b: SimpleNamespace(href=f"https://example.org/{item_id}_{b}.tif") for b in bands}
    return SimpleNamespace(
        id=item_id,
        datetime=None,
        properties={"datetime": "2024-01-01T00:00:00Z", "bdc:tiles": ["031021"]},
        assets=assets,
    )


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"fake")


_MOSAIC_PATCHES = dict(
    cutline_wgs84_bbox=None,
)


def _mosaic_env(module, build=("ok", "/tmp/intermediate.vrt", "layer", "grp"), bbox=None):
    from contextlib import ExitStack

    stack = ExitStack()
    stack.enter_context(patch.object(module, "cutline_wgs84_bbox", return_value=bbox))
    stack.enter_context(patch.object(module.download_engine, "probe_all", return_value={}))
    stack.enter_context(patch.object(module, "build_single_vrt", return_value=build))
    return stack


class TestCheckItemDownloaded(unittest.TestCase):
    """The LOCAL badge: exact file names in any delivered format."""

    def setUp(self):
        self.download_dir = tempfile.mkdtemp(prefix="bdc_test_badge_")
        self.addCleanup(shutil.rmtree, self.download_dir, ignore_errors=True)
        self.dialog = _bind(MagicMock(), "_plan_for", "_resolve_item_bands")
        self.dialog._download_dir = self.download_dir

    def _check(self, widget, bands, sits=False):
        import bdc_loader_plugin.core.download as module

        return module.DownloadManager._check_item_downloaded(self.dialog, widget, (bands, ("",), sits))

    def _mosaic_widget(self, area="Sao-Paulo-abc123"):
        widget = MagicMock()
        widget.item = _make_mosaic_item([_make_source_item("t1")], area=area)
        widget.collection_id = "S2-16D-2"
        return widget

    def test_multiband_crop_on_disk_counts(self):
        from bdc_loader_plugin.core.download_outputs import area_outputs

        widget = self._mosaic_widget()
        plan = area_outputs(
            self.download_dir, "S2-16D-2", "Sao-Paulo-abc123", "2024-01-01", ["B04", "B03"], "multiband"
        )
        _touch(plan.multiband)

        self.assertTrue(self._check(widget, ["B04", "B03"]))

    def test_per_band_crop_needs_every_band(self):
        from bdc_loader_plugin.core.download_outputs import area_outputs

        widget = self._mosaic_widget()
        plan = area_outputs(self.download_dir, "S2-16D-2", "Sao-Paulo-abc123", "2024-01-01", ["B04", "B03"], "per_band")
        _touch(plan.band_files[0][1])
        self.assertFalse(self._check(widget, ["B04", "B03"]))

        _touch(plan.band_files[1][1])
        self.assertTrue(self._check(widget, ["B04", "B03"]))

    def test_another_area_with_the_same_label_is_not_local(self):
        """Two crops whose readable names match must not share files."""
        from bdc_loader_plugin.core.download_outputs import area_outputs

        plan = area_outputs(
            self.download_dir, "S2-16D-2", "crop-15.80S-47.90W-aaaaaa", "2024-01-01", ["B04"], "per_band"
        )
        _touch(plan.band_files[0][1])

        self.assertTrue(self._check(self._mosaic_widget("crop-15.80S-47.90W-aaaaaa"), ["B04"]))
        self.assertFalse(self._check(self._mosaic_widget("crop-15.80S-47.90W-bbbbbb"), ["B04"]))

    def test_tile_band_name_is_matched_exactly(self):
        """BAND1 is not on disk just because BAND14 is."""
        item = _make_tile_item("CBERS_4_AWFI_20240101_180_135_L2", bands=("BAND1", "BAND14"))
        widget = MagicMock()
        widget.item = item
        widget.collection_id = "CB4-WFI"
        folder = os.path.join(self.download_dir, "downloads", "CB4-WFI", item.id)
        _touch(os.path.join(folder, f"{item.id}_BAND14.tif"))

        self.assertTrue(self._check(widget, ["BAND14"]))
        self.assertFalse(self._check(widget, ["BAND1"]))

    def test_sits_named_files_count_when_sits_was_chosen(self):
        from bdc_loader_plugin.core.download_outputs import tile_outputs

        item = _make_tile_item()
        widget = MagicMock()
        widget.item = item
        widget.collection_id = "S2-16D-2"
        plan = tile_outputs(
            self.download_dir, "S2-16D-2", item.id, ["B04"], "per_band", sits=True, tile="031021", date="2024-01-01"
        )
        _touch(plan.band_files[0][1])

        self.assertFalse(self._check(widget, ["B04"], sits=False))
        self.assertTrue(self._check(widget, ["B04"], sits=True))

    def test_item_without_the_band_is_not_local(self):
        widget = MagicMock()
        widget.item = _make_tile_item(bands=("B04",))
        widget.collection_id = "S2-16D-2"

        self.assertFalse(self._check(widget, ["B08"]))


class TestDownloadOneDispatch(unittest.TestCase):
    def test_mosaic_goes_to_masked_download(self):
        import bdc_loader_plugin.core.download as module

        dialog = MagicMock()
        dialog._download_masked_mosaic.return_value = ("error", "x")
        widget = MagicMock()
        widget.item = _make_mosaic_item([_make_source_item("t1")])
        choice = _choice()

        module.DownloadManager._download_one(dialog, widget, ["B04"], choice, "")

        dialog._download_masked_mosaic.assert_called_once_with(widget, ["B04"], choice, "")
        dialog._download_regular_item.assert_not_called()

    def test_stac_item_goes_to_regular_download(self):
        import bdc_loader_plugin.core.download as module

        dialog = MagicMock()
        dialog._download_regular_item.return_value = ("error", "x")
        widget = MagicMock()
        widget.item = _make_tile_item()
        choice = _choice()

        module.DownloadManager._download_one(dialog, widget, ["B04"], choice, "")

        dialog._download_regular_item.assert_called_once_with(widget, ["B04"], choice, "")
        dialog._download_masked_mosaic.assert_not_called()


class TestDownloadReentrancyGuard(unittest.TestCase):
    """A second download must not start while one is already running.

    The download paths pump the Qt event loop with processEvents(), so a
    re-entrant click could otherwise launch a concurrent operation on the
    shared progress bar / cancel flag. The flag is released in finally on
    every outcome (success, error, cancellation).
    """

    def _probe(self, behaviour):
        import bdc_loader_plugin.core.download as module

        class _Probe(module.DownloadManager):
            def __init__(self):
                self._download_in_progress = False
                self._download_cancelled = False
                self.runs = 0
                self.search_btn = MagicMock()
                self.load_btn = MagicMock()
                self.collection_combo = MagicMock()

            def _download_widgets_unguarded(self, widgets):
                self.runs += 1
                behaviour(self, widgets)

        return _Probe()

    def test_reentrant_click_is_rejected(self):
        def reenter(probe, widgets):
            probe._download_item(widgets[0])

        probe = self._probe(reenter)
        probe._download_item(MagicMock())

        self.assertEqual(probe.runs, 1)
        self.assertFalse(probe._download_in_progress)

    def test_search_and_load_are_off_while_downloading(self):
        seen = {}

        def record(probe, widgets):
            seen["search"] = probe.search_btn.setEnabled.call_args
            seen["load"] = probe.load_btn.setEnabled.call_args

        probe = self._probe(record)
        probe._download_item(MagicMock())

        self.assertEqual(seen["search"].args, (False,))
        self.assertEqual(seen["load"].args, (False,))
        probe.search_btn.setEnabled.assert_called_with(True)
        probe.load_btn.setEnabled.assert_called_with(True)

    def test_flag_released_after_exception(self):
        def boom(probe, widgets):
            raise RuntimeError("boom")

        probe = self._probe(boom)
        with self.assertRaises(RuntimeError):
            probe._download_item(MagicMock())
        self.assertFalse(probe._download_in_progress)

    def test_flag_released_after_cancellation_and_next_download_runs(self):
        def cancel(probe, widgets):
            probe._download_cancelled = True

        probe = self._probe(cancel)
        probe._download_item(MagicMock())
        probe._download_item(MagicMock())

        self.assertEqual(probe.runs, 2)
        self.assertFalse(probe._download_in_progress)


class _StubOptionsDialog:
    """DownloadOptionsDialog stand-in answering a fixed choice."""

    instances = []

    def __init__(self, message, options, selected_key, **kwargs):
        self.message = message
        self.options = options
        self.selected_key = selected_key
        self.kwargs = kwargs
        self.answer = dict(_StubOptionsDialog.answer)
        self.sits_check = MagicMock()
        self.sits_check.isChecked.return_value = self.answer.get("sits", False)
        _StubOptionsDialog.instances.append(self)

    def exec(self):
        from PyQt5.QtWidgets import QDialog

        return QDialog.DialogCode.Accepted if self.answer.get("accept", True) else QDialog.DialogCode.Rejected

    def selected_option(self):
        key = self.answer.get("crs", self.selected_key)
        return next((o for o in self.options if o.key == key), None)

    def selected_format(self):
        return self.answer.get("fmt", "per_band")

    def sits_names(self):
        return self.answer.get("sits", False) and self.selected_format() == "per_band"

    def folder(self):
        return self.answer.get("folder", self.kwargs.get("folder"))

    def remember_choice(self):
        return self.answer.get("remember", False)


class TestDownloadWidgets(unittest.TestCase):
    """The shared flow behind the card button and "Download selected"."""

    def setUp(self):
        self.download_dir = tempfile.mkdtemp(prefix="bdc_test_flow_")
        self.addCleanup(shutil.rmtree, self.download_dir, ignore_errors=True)
        _StubOptionsDialog.instances = []
        _StubOptionsDialog.answer = {}

    def _dialog(self, bands=("B04", "B03", "B02")):
        dialog = MagicMock()
        dialog._download_dir = self.download_dir
        dialog._download_cancelled = False
        dialog._selected_band_list.return_value = list(bands)
        dialog._size_note.return_value = ""
        dialog._download_one.return_value = ("done", "/data/out")
        plan = MagicMock()
        plan.complete.return_value = False
        dialog._plan_for.return_value = plan
        return _bind(dialog, "_ask_download_choice", "_report_downloads")

    def _run(self, dialog, widgets, settings, answer=None):
        import bdc_loader_plugin.core.download as module

        _StubOptionsDialog.answer = answer or {}
        options = [_native_option(), _wgs84_option()]
        with (
            patch.object(module, "QgsSettings", return_value=settings),
            patch.object(module.output_crs, "build_options", return_value=options),
            patch.object(module, "DownloadOptionsDialog", _StubOptionsDialog),
            patch.object(module, "QMessageBox") as mbox,
            patch.object(module, "QCoreApplication"),
        ):
            module.DownloadManager._download_widgets_unguarded(dialog, widgets)
        return mbox

    def test_no_band_selected_warns(self):
        dialog = self._dialog(bands=())
        mbox = self._run(dialog, [MagicMock()], _FakeSettings())

        mbox.warning.assert_called_once()
        dialog._download_one.assert_not_called()

    def test_dialog_opens_even_when_the_last_choice_is_on_disk(self):
        """The same result may be wanted in another format or projection."""
        dialog = self._dialog()
        dialog._plan_for.return_value.complete.return_value = True

        self._run(dialog, [MagicMock()], _FakeSettings(), {"fmt": "multiband"})

        self.assertEqual(len(_StubOptionsDialog.instances), 1)
        self.assertEqual(dialog._download_one.call_args.args[2].fmt, "multiband")

    def test_without_asking_a_complete_result_is_skipped(self):
        from bdc_loader_plugin.core.download import SKIP_CONFIRM_SETTING

        dialog = self._dialog()
        dialog._plan_for.return_value.complete.return_value = True
        dialog._plan_for.return_value.paths.return_value = ["/data/x/a.tif"]
        widget = MagicMock()

        self._run(dialog, [widget], _FakeSettings({SKIP_CONFIRM_SETTING: True}))

        self.assertEqual(_StubOptionsDialog.instances, [])
        dialog._download_one.assert_not_called()
        widget.set_downloaded.assert_called_once_with(True)

    def test_choice_from_the_dialog_reaches_every_result_and_is_stored(self):
        from bdc_loader_plugin.core import output_crs
        from bdc_loader_plugin.core.download_outputs import FORMAT_SETTING, SITS_SETTING

        dialog = self._dialog()
        settings = _FakeSettings()
        widgets = [MagicMock(), MagicMock()]

        self._run(dialog, widgets, settings, {"fmt": "per_band", "sits": True, "crs": output_crs.WGS84})

        self.assertEqual(len(_StubOptionsDialog.instances), 1)
        self.assertIn("2 selected results", _StubOptionsDialog.instances[0].message)
        self.assertEqual(dialog._download_one.call_count, 2)
        choice = dialog._download_one.call_args.args[2]
        self.assertEqual((choice.fmt, choice.sits, choice.crs.key), ("per_band", True, output_crs.WGS84))
        self.assertEqual(dialog._download_one.call_args_list[0].args[3], "[1/2] ")
        self.assertEqual(settings.values[FORMAT_SETTING], "per_band")
        self.assertTrue(settings.values[SITS_SETTING])
        self.assertEqual(settings.values[output_crs.OUTPUT_CRS_SETTING], output_crs.WGS84)
        for widget in widgets:
            widget.set_downloaded.assert_called_once_with(True)

    def test_declining_downloads_nothing(self):
        dialog = self._dialog()
        self._run(dialog, [MagicMock()], _FakeSettings(), {"accept": False})

        dialog._download_one.assert_not_called()

    def test_remember_skips_the_dialog_next_time(self):
        from bdc_loader_plugin.core.download import SKIP_CONFIRM_SETTING
        from bdc_loader_plugin.core.download_outputs import FORMAT_SETTING

        dialog = self._dialog()
        settings = _FakeSettings()
        self._run(dialog, [MagicMock()], settings, {"fmt": "multiband", "remember": True})
        self.assertTrue(settings.values[SKIP_CONFIRM_SETTING])

        _StubOptionsDialog.instances = []
        self._run(dialog, [MagicMock()], settings)

        self.assertEqual(_StubOptionsDialog.instances, [])
        self.assertEqual(settings.values[FORMAT_SETTING], "multiband")
        self.assertEqual(dialog._download_one.call_args.args[2].fmt, "multiband")

    def test_single_band_does_not_overwrite_the_stored_format(self):
        from bdc_loader_plugin.core.download_outputs import FORMAT_SETTING

        dialog = self._dialog(bands=("B04",))
        settings = _FakeSettings({FORMAT_SETTING: "multiband"})

        self._run(dialog, [MagicMock()], settings, {"fmt": "per_band"})

        self.assertEqual(settings.values[FORMAT_SETTING], "multiband")
        self.assertEqual(dialog._download_one.call_args.args[2].fmt, "per_band")

    def test_folder_changed_in_the_dialog_becomes_the_download_folder(self):
        dialog = self._dialog()
        settings = _FakeSettings()

        self._run(dialog, [MagicMock()], settings, {"folder": "/elsewhere"})

        self.assertEqual(dialog._download_dir, "/elsewhere")
        self.assertEqual(settings.values["bdc_loader/download_dir"], "/elsewhere")

    def test_errors_of_a_batch_are_reported_together(self):
        dialog = self._dialog()
        dialog._download_one.side_effect = [("done", "/a"), ("error", "B failed"), ("skipped", "/c")]
        widgets = [MagicMock(), MagicMock(), MagicMock()]

        mbox = self._run(dialog, widgets, _FakeSettings())

        mbox.warning.assert_called_once()
        self.assertIn("B failed", mbox.warning.call_args.args[2])
        status = dialog._set_status.call_args.args[0]
        self.assertIn("1 image downloaded", status)
        self.assertIn("1 already on disk", status)
        self.assertIn("1 failed", status)
        widgets[1].set_downloaded.assert_not_called()

    def test_cancel_stops_the_batch(self):
        dialog = self._dialog()

        def _cancel(*_args):
            dialog._download_cancelled = True
            return ("cancelled", "x")

        dialog._download_one.side_effect = _cancel
        self._run(dialog, [MagicMock(), MagicMock()], _FakeSettings())

        self.assertEqual(dialog._download_one.call_count, 1)


class TestDownloadMaskedMosaic(unittest.TestCase):
    """Crop and vector-feature mosaics: VRT over the source tiles, cut with gdal.Warp."""

    def setUp(self):
        self.download_dir = tempfile.mkdtemp(prefix="bdc_test_dl_")
        self.addCleanup(shutil.rmtree, self.download_dir, ignore_errors=True)

    def _widget(self, sources=None, **kwargs):
        widget = MagicMock()
        widget.item = _make_mosaic_item(sources if sources is not None else [_make_source_item("tile_a")], **kwargs)
        widget.collection_id = "S2-16D-2"
        return widget

    def _run(self, dialog, widget, bands, choice, **env):
        import bdc_loader_plugin.core.download as module

        with _mosaic_env(module, **env):
            return module.DownloadManager._download_masked_mosaic(dialog, widget, bands, choice, "")

    def test_no_source_items_is_an_error(self):
        dialog = _make_dialog(self.download_dir)
        status, detail = self._run(dialog, self._widget(sources=[]), ["B04"], _choice())

        self.assertEqual(status, "error")
        self.assertIn("no source tiles", detail)

    def test_no_boundary_is_an_error(self):
        dialog = _make_dialog(self.download_dir)
        dialog._cutline_for_item.return_value = None

        status, detail = self._run(dialog, self._widget(), ["B04"], _choice())

        self.assertEqual(status, "error")
        self.assertIn("boundary", detail)

    def test_single_band_is_cut_straight_into_its_file(self):
        from bdc_loader_plugin.core.download_outputs import area_outputs

        dialog = _make_dialog(self.download_dir)
        dialog._build_single_band_task.return_value = {"vrt_path": "x"}

        status, _detail = self._run(dialog, self._widget(), ["B04"], _choice())

        expected = area_outputs(self.download_dir, "S2-16D-2", "Sao-Paulo-abc123", "2024-01-01", ["B04"], "per_band")
        self.assertEqual(status, "done")
        vrt_arg, cutline_arg, dst_arg, _label = dialog._run_masked_export.call_args.args
        self.assertEqual((vrt_arg, cutline_arg), ("/tmp/intermediate.vrt", "/tmp/feat_cutline.geojson"))
        self.assertEqual(dst_arg, expected.band_files[0][1])
        self.assertTrue(dst_arg.endswith(os.path.join("Sao-Paulo-abc123", "Sao-Paulo-abc123_2024-01-01_B04.tif")))
        self.assertIsNone(dialog._run_masked_export.call_args.kwargs["dst_srs"])
        self.assertEqual(dialog._run_masked_export.call_args.kwargs["band_names"], ["B04"])

    def test_multiband_writes_one_file_with_any_number_of_bands(self):
        """More than three bands are accepted; they go through the stacked task."""
        dialog = _make_dialog(self.download_dir)
        dialog._build_rgb_task.return_value = {"vrt_path": "x"}
        bands = ["B02", "B03", "B04", "B08", "B11"]

        status, _detail = self._run(dialog, self._widget(), bands, _choice("multiband"))

        self.assertEqual(status, "done")
        self.assertEqual(dialog._build_rgb_task.call_args.args[0], bands)
        dst = dialog._run_masked_export.call_args.args[2]
        self.assertTrue(dst.endswith("Sao-Paulo-abc123_2024-01-01_B02-B03-B04-B08-B11.tif"))

    def test_per_band_splits_the_masked_stack_and_writes_the_vrt(self):
        import bdc_loader_plugin.core.download as module

        dialog = _make_dialog(self.download_dir)
        dialog._build_rgb_task.return_value = {"vrt_path": "x"}
        with (
            patch.object(module, "split_bands", return_value=(True, [])) as split,
            patch.object(module, "write_band_vrt", return_value=(True, "v")) as vrt,
        ):
            status, _detail = self._run(dialog, self._widget(), ["B04", "B03"], _choice("per_band_vrt"))

        self.assertEqual(status, "done")
        stack_path = dialog._run_masked_export.call_args.args[2]
        self.assertEqual(os.path.basename(stack_path), "stack.tif")
        self.assertEqual(split.call_args.args[0], stack_path)
        names = [os.path.basename(p) for p in split.call_args.args[1]]
        self.assertEqual(names, ["Sao-Paulo-abc123_2024-01-01_B04.tif", "Sao-Paulo-abc123_2024-01-01_B03.tif"])
        self.assertTrue(vrt.call_args.args[0].endswith("Sao-Paulo-abc123_2024-01-01_B04-B03.vrt"))

    def test_sits_names_go_to_the_sits_folder(self):
        import bdc_loader_plugin.core.download as module

        dialog = _make_dialog(self.download_dir)
        dialog._build_rgb_task.return_value = {"vrt_path": "x"}
        with patch.object(module, "split_bands", return_value=(True, [])) as split:
            self._run(dialog, self._widget(), ["B04", "B03"], _choice("per_band", sits=True))

        paths = split.call_args.args[1]
        self.assertEqual(os.path.dirname(paths[0]), os.path.join(self.download_dir, "downloads", "S2-16D-2", "sits"))
        self.assertEqual(os.path.basename(paths[0]), "S2-16D-2_native_Sao-Paulo-abc123_B04_2024-01-01.tif")

    def test_chosen_projection_reaches_the_warp_and_the_file_name(self):
        dialog = _make_dialog(self.download_dir)
        dialog._build_single_band_task.return_value = {"vrt_path": "x"}

        self._run(dialog, self._widget(), ["B04"], _choice(crs=_wgs84_option()))

        self.assertEqual(dialog._run_masked_export.call_args.kwargs["dst_srs"], "EPSG:4326")
        self.assertTrue(dialog._run_masked_export.call_args.args[2].endswith("_B04_epsg4326.tif"))

    def test_extent_crop_is_written_as_a_straight_rectangle(self):
        """A drawn box goes through export_bbox_geotiff, not the diagonal mask."""

        dialog = _make_dialog(self.download_dir)
        dialog._build_single_band_task.return_value = {"vrt_path": "x"}
        dialog._run_export.return_value = (True, "/x")
        widget = self._widget(is_extent_crop=True)
        widget.item.properties["bdc:crop_bbox"] = [-47.95, -15.85, -47.85, -15.75]

        status, _detail = self._run(dialog, widget, ["B04"], _choice(crs=_wgs84_option()))

        self.assertEqual(status, "done")
        dialog._run_masked_export.assert_not_called()
        _label, func, vrt, bbox, dst = dialog._run_export.call_args.args
        self.assertIs(func, raster_export.export_bbox_geotiff)
        self.assertEqual(bbox, [-47.95, -15.85, -47.85, -15.75])
        self.assertTrue(dst.endswith("_B04_epsg4326.tif"))
        self.assertEqual(dialog._run_export.call_args.kwargs["dst_srs"], "EPSG:4326")

    def test_already_on_disk_is_skipped(self):
        from bdc_loader_plugin.core.download_outputs import area_outputs

        plan = area_outputs(self.download_dir, "S2-16D-2", "Sao-Paulo-abc123", "2024-01-01", ["B04"], "per_band")
        _touch(plan.band_files[0][1])
        dialog = _make_dialog(self.download_dir)

        status, _detail = self._run(dialog, self._widget(), ["B04"], _choice())

        self.assertEqual(status, "skipped")
        dialog._run_masked_export.assert_not_called()

    def test_unchecked_extent_crop_tiles_are_excluded(self):
        sources = [
            _make_source_item("tile_a", tile="031021"),
            _make_source_item("tile_b", tile="031022"),
            _make_source_item("tile_c", tile="031023"),
        ]
        dialog = _make_dialog(self.download_dir)
        dialog._current_result_mode = "extent_crop"
        dialog._tile_filter_dict = {
            "031021": {"display": "031021", "checked": True},
            "031022": {"display": "031022", "checked": False},
            "031023": {"display": "031023", "checked": True},
        }
        dialog._build_single_band_task.return_value = {"vrt_path": "x"}

        self._run(dialog, self._widget(sources=sources, is_extent_crop=True), ["B04"], _choice())

        included = {si.id for si in dialog._build_single_band_task.call_args.args[1]}
        self.assertEqual(included, {"tile_a", "tile_c"})

    def test_regenerates_missing_boundary_before_export(self):
        vanished = os.path.join(self.download_dir, "vanished.geojson")
        regenerated = os.path.join(self.download_dir, "regenerated.geojson")
        _touch(regenerated)
        dialog = _make_dialog(self.download_dir)
        dialog._cutline_for_item.side_effect = [vanished, regenerated]
        dialog._build_single_band_task.return_value = {"vrt_path": "x"}

        status, _detail = self._run(dialog, self._widget(), ["B04"], _choice())

        self.assertEqual(status, "done")
        self.assertEqual(dialog._run_masked_export.call_args.args[1], regenerated)

    def test_cancelled_export_reports_cancellation(self):
        dialog = _make_dialog(self.download_dir)
        dialog._build_single_band_task.return_value = {"vrt_path": "x"}

        def _cancel(*_a, **_kw):
            dialog._download_cancelled = True
            return False, "cancelled by user"

        dialog._run_masked_export.side_effect = _cancel

        status, _detail = self._run(dialog, self._widget(), ["B04"], _choice())

        self.assertEqual(status, "cancelled")

    def test_export_failure_is_an_error(self):
        dialog = _make_dialog(self.download_dir)
        dialog._build_single_band_task.return_value = {"vrt_path": "x"}
        dialog._run_masked_export.side_effect = None
        dialog._run_masked_export.return_value = (False, "boom")

        status, detail = self._run(dialog, self._widget(), ["B04"], _choice())

        self.assertEqual(status, "error")
        self.assertIn("boom", detail)

    def test_vrt_build_failure_skips_export(self):
        dialog = _make_dialog(self.download_dir)
        dialog._build_single_band_task.return_value = {"vrt_path": "x"}

        status, detail = self._run(dialog, self._widget(), ["B04"], _choice(), build=("error", "tile_a", "boom"))

        self.assertEqual(status, "error")
        self.assertIn("boom", detail)
        dialog._run_masked_export.assert_not_called()


class TestDownloadMaskedMosaicPrefetch(unittest.TestCase):
    """A source tile the area mostly covers is pre-fetched whole via
    _run_accelerated_downloads (fast, parallel) instead of read windowed
    through the VRT/gdal.Warp path; a tile it barely touches is not."""

    def setUp(self):
        self.download_dir = tempfile.mkdtemp(prefix="bdc_test_dl_")
        self.addCleanup(shutil.rmtree, self.download_dir, ignore_errors=True)

    def _widget(self, src):
        widget = MagicMock()
        widget.item = _make_mosaic_item([src])
        widget.collection_id = "S2-16D-2"
        return widget

    def test_high_overlap_tile_is_prefetched_via_accelerated_downloads(self):
        import bdc_loader_plugin.core.download as module

        src = _make_source_item("tile_a")
        src.bbox = (-50.0, -20.0, -49.0, -19.0)
        dialog = _make_dialog(self.download_dir)
        dialog._build_single_band_task.return_value = {"vrt_path": "x"}

        with (
            _mosaic_env(module, bbox=(-50.0, -20.0, -49.0, -19.0)),
            patch.object(
                module.download_engine, "probe_all", return_value={"https://example.org/B04.tif": (12345, True)}
            ) as probe_mock,
        ):
            module.DownloadManager._download_masked_mosaic(dialog, self._widget(src), ["B04"], _choice(), "")

        probe_mock.assert_called_once_with(["https://example.org/B04.tif"])
        tasks = dialog._run_accelerated_downloads.call_args.args[0]
        self.assertEqual(len(tasks), 1)
        href, dest_file = tasks[0]
        self.assertEqual(href, "https://example.org/B04.tif")
        self.assertTrue(dest_file.endswith(os.path.join("tile_a", "tile_a_B04.tif")))
        self.assertEqual(dialog._run_accelerated_downloads.call_args.kwargs["total_size_hint"], 12345)
        self.assertEqual(
            dialog._run_accelerated_downloads.call_args.kwargs["probes"],
            {"https://example.org/B04.tif": (12345, True)},
        )

    def test_low_overlap_tile_is_not_prefetched(self):
        import bdc_loader_plugin.core.download as module

        src = _make_source_item("tile_a")
        src.bbox = (0.0, 0.0, 10.0, 10.0)
        dialog = _make_dialog(self.download_dir)
        dialog._build_single_band_task.return_value = {"vrt_path": "x"}

        with _mosaic_env(module, bbox=(9.5, 0.0, 10.5, 10.0)):
            module.DownloadManager._download_masked_mosaic(dialog, self._widget(src), ["B04"], _choice(), "")

        dialog._run_accelerated_downloads.assert_not_called()
        info_calls = [c.args[0] for c in dialog._set_status.call_args_list if c.args[1] == "info"]
        self.assertTrue(any("directly from the BDC" in msg for msg in info_calls))

    def test_already_local_band_is_not_prefetched_again(self):
        import bdc_loader_plugin.core.download as module

        src = _make_source_item("tile_a")
        src.bbox = (-50.0, -20.0, -49.0, -19.0)
        _touch(os.path.join(self.download_dir, "downloads", "S2-16D-2", "tile_a", "tile_a_B04.tif"))
        dialog = _make_dialog(self.download_dir)
        dialog._build_single_band_task.return_value = {"vrt_path": "x"}

        with (
            _mosaic_env(module, bbox=(-50.0, -20.0, -49.0, -19.0)),
            patch("bdc_loader_plugin.core.vrt_builder.gdal.Open", return_value=_valid_raster_dataset()),
        ):
            module.DownloadManager._download_masked_mosaic(dialog, self._widget(src), ["B04"], _choice(), "")

        dialog._run_accelerated_downloads.assert_not_called()

    def test_cancellation_during_prefetch_skips_vrt_build(self):
        import bdc_loader_plugin.core.download as module

        src = _make_source_item("tile_a")
        src.bbox = (-50.0, -20.0, -49.0, -19.0)
        dialog = _make_dialog(self.download_dir)

        def _cancel(*a, **kw):
            dialog._download_cancelled = True
            return [("https://example.org/B04.tif", "/tmp/x.tif", "cancelled mid-download")]

        dialog._run_accelerated_downloads.side_effect = _cancel

        with (
            _mosaic_env(module, bbox=(-50.0, -20.0, -49.0, -19.0)),
            patch.object(module, "build_single_vrt") as vrt_mock,
        ):
            status, _detail = module.DownloadManager._download_masked_mosaic(
                dialog, self._widget(src), ["B04"], _choice(), ""
            )

        vrt_mock.assert_not_called()
        self.assertEqual(status, "cancelled")


class TestDownloadRegularItem(unittest.TestCase):
    """STAC items: original COGs first, then the chosen format."""

    def setUp(self):
        self.download_dir = tempfile.mkdtemp(prefix="bdc_test_tile_")
        self.addCleanup(shutil.rmtree, self.download_dir, ignore_errors=True)
        self.item = _make_tile_item()
        self.widget = MagicMock()
        self.widget.item = self.item
        self.widget.collection_id = "S2-16D-2"
        self.folder = os.path.join(self.download_dir, "downloads", "S2-16D-2", self.item.id)

    def _dialog(self):
        dialog = _make_dialog(self.download_dir)

        def _fetch(tasks, **_kw):
            for _href, dest in tasks:
                _touch(dest)
            return []

        dialog._run_accelerated_downloads.side_effect = _fetch
        dialog._run_export.side_effect = lambda label, func, sources, dst, bands, **kw: (_touch(dst), (True, dst))[1]
        return _bind(dialog, "_plan_for", "_resolve_item_bands", "_write_outputs")

    def _run(self, dialog, bands, choice):
        import bdc_loader_plugin.core.download as module

        with (
            patch.object(module.download_engine, "probe_all", return_value={}),
            patch.object(module, "is_valid_local_raster", side_effect=os.path.isfile),
            patch.object(
                module, "write_band_vrt", side_effect=lambda path, files, names: (_touch(path), (True, path))[1]
            ),
        ):
            return module.DownloadManager._download_regular_item(dialog, self.widget, bands, choice, "")

    def test_per_band_native_keeps_the_original_files(self):
        dialog = self._dialog()

        status, _detail = self._run(dialog, ["B04", "B03"], _choice())

        self.assertEqual(status, "done")
        names = sorted(os.listdir(self.folder))
        self.assertEqual(names, [f"{self.item.id}_B03.tif", f"{self.item.id}_B04.tif"])
        dialog._run_export.assert_not_called()

    def test_multiband_stacks_and_removes_the_fetched_originals(self):

        dialog = self._dialog()

        status, _detail = self._run(dialog, ["B04", "B03", "B02"], _choice("multiband", crs=_wgs84_option()))

        self.assertEqual(status, "done")
        label, func, sources, dst, bands = dialog._run_export.call_args.args
        self.assertIs(func, raster_export.export_stack_geotiff)
        self.assertEqual(os.path.basename(dst), f"{self.item.id}_B04-B03-B02_epsg4326.tif")
        self.assertEqual(dialog._run_export.call_args.kwargs["dst_srs"], "EPSG:4326")
        self.assertEqual(os.listdir(self.folder), [os.path.basename(dst)])

    def test_multiband_keeps_originals_that_were_already_local(self):
        dialog = self._dialog()
        _touch(os.path.join(self.folder, f"{self.item.id}_B04.tif"))

        self._run(dialog, ["B04", "B03"], _choice("multiband"))

        self.assertIn(f"{self.item.id}_B04.tif", os.listdir(self.folder))
        self.assertNotIn(f"{self.item.id}_B03.tif", os.listdir(self.folder))

    def test_per_band_reprojected_writes_tagged_files(self):
        dialog = self._dialog()

        self._run(dialog, ["B04"], _choice(crs=_wgs84_option()))

        dst = dialog._run_export.call_args.args[3]
        self.assertEqual(os.path.basename(dst), f"{self.item.id}_B04_epsg4326.tif")

    def test_per_band_with_vrt(self):
        dialog = self._dialog()

        self._run(dialog, ["B04", "B03"], _choice("per_band_vrt"))

        self.assertIn(f"{self.item.id}_B04-B03.vrt", os.listdir(self.folder))

    def test_sits_names_are_links_to_the_originals(self):
        dialog = self._dialog()

        self._run(dialog, ["B04"], _choice(sits=True))

        sits = os.path.join(self.download_dir, "downloads", "S2-16D-2", "sits")
        self.assertEqual(os.listdir(sits), ["S2-16D-2_native_031021_B04_2024-01-01.tif"])
        self.assertIn(f"{self.item.id}_B04.tif", os.listdir(self.folder))

    def test_missing_band_is_an_error(self):
        dialog = self._dialog()

        status, detail = self._run(dialog, ["B08"], _choice())

        self.assertEqual(status, "error")
        self.assertIn("B08", detail)
        dialog._run_accelerated_downloads.assert_not_called()

    def test_failed_transfer_is_an_error(self):
        dialog = self._dialog()
        dialog._run_accelerated_downloads.side_effect = None
        dialog._run_accelerated_downloads.return_value = [("u", "/x/a_B04.tif", "HTTP 500")]

        status, detail = self._run(dialog, ["B04"], _choice())

        self.assertEqual(status, "error")
        self.assertIn("HTTP 500", detail)


class TestRunMaskedExport(unittest.TestCase):
    """_run_masked_export against the real implementation, with
    export_masked_geotiff mocked — exercises the main-thread polling loop
    that keeps GDAL's own Warp progress off the worker thread."""

    def test_returns_export_masked_geotiff_result(self):
        import bdc_loader_plugin.core.download as module

        dialog = _bind(MagicMock(), "_run_export")
        dialog._download_cancelled = False
        dialog.progress_bar = MagicMock()

        with patch.object(module, "export_masked_geotiff", return_value=(True, "/final/masked.tif")) as export_mock:
            result = module.DownloadManager._run_masked_export(
                dialog, "/tmp/x.vrt", "/tmp/cut.geojson", "/tmp/out.tif", "item-1"
            )

        self.assertEqual(result, (True, "/final/masked.tif"))
        export_mock.assert_called_once()
        vrt_arg, cutline_arg, dst_arg = export_mock.call_args.args[:3]
        self.assertEqual((vrt_arg, cutline_arg, dst_arg), ("/tmp/x.vrt", "/tmp/cut.geojson", "/tmp/out.tif"))

    def test_output_projection_reaches_export_masked_geotiff(self):
        """The projection choice rides along to the same Warp, so it must
        arrive at the exporter rather than being dropped here."""
        import bdc_loader_plugin.core.download as module

        dialog = _bind(MagicMock(), "_run_export")
        dialog._download_cancelled = False
        dialog.progress_bar = MagicMock()

        with patch.object(module, "export_masked_geotiff", return_value=(True, "/final/masked.tif")) as export_mock:
            module.DownloadManager._run_masked_export(
                dialog,
                "/tmp/x.vrt",
                "/tmp/cut.geojson",
                "/tmp/out.tif",
                "item-1",
                dst_srs="EPSG:4326",
            )

        self.assertEqual(export_mock.call_args.kwargs["dst_srs"], "EPSG:4326")

    def test_default_keeps_the_export_on_the_native_grid(self):
        import bdc_loader_plugin.core.download as module

        dialog = _bind(MagicMock(), "_run_export")
        dialog._download_cancelled = False
        dialog.progress_bar = MagicMock()

        with patch.object(module, "export_masked_geotiff", return_value=(True, "/final/masked.tif")) as export_mock:
            module.DownloadManager._run_masked_export(
                dialog, "/tmp/x.vrt", "/tmp/cut.geojson", "/tmp/out.tif", "item-1"
            )

        self.assertIsNone(export_mock.call_args.kwargs["dst_srs"])

    def test_progress_callback_updates_bar_via_polling(self):
        """export_masked_geotiff calls progress_cb from the worker thread;
        the main-thread loop must be the one touching progress_bar."""
        import bdc_loader_plugin.core.download as module

        dialog = _bind(MagicMock(), "_run_export")
        dialog._download_cancelled = False
        dialog.progress_bar = MagicMock()

        def _slow_export(vrt_path, cutline_path, dst_path, progress_cb=None, cancel_check=None, **_options):
            progress_cb(0.5)
            time.sleep(0.25)  # outlast at least one 0.1s poll so the bar update is observed
            return True, dst_path

        with patch.object(module, "export_masked_geotiff", side_effect=_slow_export):
            result = module.DownloadManager._run_masked_export(
                dialog, "/tmp/x.vrt", "/tmp/cut.geojson", "/tmp/out.tif", "item-1"
            )

        self.assertEqual(result, (True, "/tmp/out.tif"))
        dialog.progress_bar.setValue.assert_any_call(50)

    def test_zero_progress_shows_elapsed_time_not_a_stuck_percentage(self):
        """GDAL only reports progress once it starts copying pixels; a small
        windowed crop can spend its whole (short) runtime in cutline/metadata
        setup before that, so this must not just repeat "0%" the whole time."""
        import bdc_loader_plugin.core.download as module

        dialog = _bind(MagicMock(), "_run_export")
        dialog._download_cancelled = False
        dialog.progress_bar = MagicMock()

        def _stalled_export(vrt_path, cutline_path, dst_path, progress_cb=None, cancel_check=None, **_options):
            time.sleep(0.25)  # outlast at least one 0.1s poll with progress still at 0
            return True, dst_path

        with patch.object(module, "export_masked_geotiff", side_effect=_stalled_export):
            module.DownloadManager._run_masked_export(dialog, "/tmp/x.vrt", "/tmp/cut.geojson", "/tmp/out.tif", "X")

        status_texts = [c.args[0] for c in dialog._set_status.call_args_list]
        self.assertTrue(any(t.startswith("Writing X: ") and t.endswith(" s") for t in status_texts))
        self.assertFalse(any("0%" in t for t in status_texts))

    def test_cancel_check_reflects_dialog_cancelled_flag(self):
        import bdc_loader_plugin.core.download as module

        dialog = _bind(MagicMock(), "_run_export")
        dialog._download_cancelled = False
        dialog.progress_bar = MagicMock()
        seen_cancel_states = []

        def _export(vrt_path, cutline_path, dst_path, progress_cb=None, cancel_check=None, **_options):
            seen_cancel_states.append(cancel_check())
            dialog._download_cancelled = True
            seen_cancel_states.append(cancel_check())
            return False, "cancelled"

        with patch.object(module, "export_masked_geotiff", side_effect=_export):
            result = module.DownloadManager._run_masked_export(
                dialog, "/tmp/x.vrt", "/tmp/cut.geojson", "/tmp/out.tif", "item-1"
            )

        self.assertEqual(result, (False, "cancelled"))
        self.assertEqual(seen_cancel_states, [False, True])


class TestRunAcceleratedDownloads(unittest.TestCase):
    """_run_accelerated_downloads against a real local HTTP server — exercises
    the real download_engine (not mocked) plus the main-thread polling loop
    that keeps Qt widget updates off the worker thread."""

    def setUp(self):
        self.serve_dir = tempfile.mkdtemp(prefix="bdc_test_serve_")
        self.addCleanup(shutil.rmtree, self.serve_dir, ignore_errors=True)
        self.download_dir = tempfile.mkdtemp(prefix="bdc_test_dl_")
        self.addCleanup(shutil.rmtree, self.download_dir, ignore_errors=True)

        self.payload = os.urandom(50_000)
        with open(os.path.join(self.serve_dir, "band.tif"), "wb") as f:
            f.write(self.payload)

        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=self.serve_dir)
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_port
        thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.httpd.shutdown)
        self.addCleanup(self.httpd.server_close)

    def test_real_download_succeeds_and_writes_correct_bytes(self):
        import bdc_loader_plugin.core.download as module

        dialog = MagicMock()
        dialog._download_cancelled = False

        dest = os.path.join(self.download_dir, "band.tif")
        url = f"http://127.0.0.1:{self.port}/band.tif"

        results = module.DownloadManager._run_accelerated_downloads(
            dialog, [(url, dest)], total_size_hint=len(self.payload), label="1 band"
        )

        self.assertEqual(results, [])
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), self.payload)

    def test_empty_tasks_returns_immediately_without_polling(self):
        import bdc_loader_plugin.core.download as module

        dialog = MagicMock()
        results = module.DownloadManager._run_accelerated_downloads(dialog, [])
        self.assertEqual(results, [])
        dialog._set_status.assert_not_called()


def _prefetch_item(item_id, bbox, assets):
    """A source-tile stand-in for plan_prefetch_tasks: id, bbox, and an assets
    dict of band -> object with an .href."""
    return SimpleNamespace(
        id=item_id,
        bbox=bbox,
        assets={band: SimpleNamespace(href=href) for band, href in assets.items()},
    )


class TestPlanPrefetchTasks(unittest.TestCase):
    """plan_prefetch_tasks — the pure prefetch decision extracted from
    _download_masked_mosaic. Overlap is fed in as an explicit cutline bbox and
    local-file presence as an injected predicate, so these tests touch no
    network, GDAL, Qt, or disk."""

    FULL = (0.0, 0.0, 1.0, 1.0)  # a 1x1-deg tile
    NONE_EXISTS = staticmethod(lambda path: False)
    ALL_EXIST = staticmethod(lambda path: True)

    def _plan(self, items, bands, cutline_bbox, is_reusable):
        import bdc_loader_plugin.core.download as module

        return module.plan_prefetch_tasks(items, bands, "/dl", "COLL", cutline_bbox, is_reusable=is_reusable)

    def _expected_dest(self, item_id, band):
        return os.path.join("/dl", "downloads", "COLL", item_id, f"{item_id}_{band}.tif")

    def test_sufficient_overlap_enters_prefetch(self):
        item = _prefetch_item("tile_a", self.FULL, {"B04": "http://x/B04.tif"})

        plan = self._plan([item], ["B04"], self.FULL, self.NONE_EXISTS)

        self.assertEqual(plan.tasks, [("http://x/B04.tif", self._expected_dest("tile_a", "B04"))])
        self.assertEqual(plan.max_fraction, 1.0)

    def test_low_overlap_stays_windowed(self):
        # 10x10-deg tile (area 100) touched only on a 1x1 corner -> 1% overlap,
        # well under the 12% prefetch threshold.
        item = _prefetch_item("tile_a", (0.0, 0.0, 10.0, 10.0), {"B04": "http://x/B04.tif"})

        plan = self._plan([item], ["B04"], (0.0, 0.0, 1.0, 1.0), self.NONE_EXISTS)

        self.assertEqual(plan.tasks, [])
        self.assertAlmostEqual(plan.max_fraction, 0.01)

    def test_missing_band_is_skipped_others_still_prefetched(self):
        item = _prefetch_item("tile_a", self.FULL, {"B04": "http://x/B04.tif"})

        plan = self._plan([item], ["B99", "B04"], self.FULL, self.NONE_EXISTS)

        # B99 has no asset -> resolve_band returns None -> skipped; B04 remains.
        self.assertEqual(plan.tasks, [("http://x/B04.tif", self._expected_dest("tile_a", "B04"))])

    def test_valid_local_file_is_not_downloaded(self):
        item = _prefetch_item("tile_a", self.FULL, {"B04": "http://x/B04.tif"})

        plan = self._plan([item], ["B04"], self.FULL, self.ALL_EXIST)

        self.assertEqual(plan.tasks, [])
        # It still cleared the overlap bar; it was just already on disk.
        self.assertEqual(plan.max_fraction, 1.0)

    def test_absent_file_is_queued(self):
        item = _prefetch_item("tile_a", self.FULL, {"B04": "http://x/B04.tif"})
        dest = self._expected_dest("tile_a", "B04")

        plan = self._plan([item], ["B04"], self.FULL, lambda path: path != dest)

        self.assertEqual(plan.tasks, [("http://x/B04.tif", dest)])

    def test_empty_source_items(self):
        plan = self._plan([], ["B04"], self.FULL, self.NONE_EXISTS)

        self.assertEqual(plan.tasks, [])
        self.assertEqual(plan.max_fraction, 0.0)

    def test_empty_bands_yields_no_tasks(self):
        item = _prefetch_item("tile_a", self.FULL, {"B04": "http://x/B04.tif"})

        plan = self._plan([item], [], self.FULL, self.NONE_EXISTS)

        self.assertEqual(plan.tasks, [])
        self.assertEqual(plan.max_fraction, 1.0)

    def test_multiple_bands_each_become_a_task(self):
        item = _prefetch_item(
            "tile_a", self.FULL, {"B02": "http://x/B02.tif", "B03": "http://x/B03.tif", "B04": "http://x/B04.tif"}
        )

        plan = self._plan([item], ["B02", "B03", "B04"], self.FULL, self.NONE_EXISTS)

        self.assertEqual(
            plan.tasks,
            [
                ("http://x/B02.tif", self._expected_dest("tile_a", "B02")),
                ("http://x/B03.tif", self._expected_dest("tile_a", "B03")),
                ("http://x/B04.tif", self._expected_dest("tile_a", "B04")),
            ],
        )

    def test_prefetch_reuses_only_valid_local_raster(self):
        """With the default reuse gate (is_valid_local_raster, fed a GDAL
        stand-in here), a finished tile is skipped while an interrupted one
        (empty file) is re-queued — so prefetch reuses only real rasters."""
        import bdc_loader_plugin.core.download as module
        from bdc_loader_plugin.core.vrt_builder import is_valid_local_raster

        work = tempfile.mkdtemp(prefix="bdc_test_prefetch_reuse_")
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)

        item = _prefetch_item("tile_a", self.FULL, {"B02": "http://x/B02.tif", "B04": "http://x/B04.tif"})

        def dest(band):
            return os.path.join(work, "downloads", "COLL", "tile_a", f"tile_a_{band}.tif")

        os.makedirs(os.path.dirname(dest("B02")), exist_ok=True)
        # B02: a finished, openable raster -> reused (not queued).
        with open(dest("B02"), "wb") as f:
            f.write(b"GTIFF-BYTES")
        # B04: an empty file from an interrupted write -> not reusable -> queued.
        open(dest("B04"), "wb").close()

        def fake_open(path, mode=0):
            # A real-GDAL stand-in: any non-empty file opens as a 1-band raster.
            if os.path.getsize(path) <= 0:
                return None
            ds = MagicMock()
            ds.RasterXSize = ds.RasterYSize = 8
            ds.RasterCount = 1
            ds.GetRasterBand.return_value = object()
            return ds

        plan = module.plan_prefetch_tasks(
            [item],
            ["B02", "B04"],
            work,
            "COLL",
            self.FULL,
            is_reusable=lambda p: is_valid_local_raster(p, opener=fake_open),
        )

        self.assertEqual(plan.tasks, [("http://x/B04.tif", dest("B04"))])

    def test_deterministic_order_across_items_and_bands(self):
        item_a = _prefetch_item("tile_a", self.FULL, {"B02": "http://a/B02.tif", "B04": "http://a/B04.tif"})
        item_b = _prefetch_item("tile_b", self.FULL, {"B02": "http://b/B02.tif", "B04": "http://b/B04.tif"})

        plan = self._plan([item_a, item_b], ["B02", "B04"], self.FULL, self.NONE_EXISTS)

        self.assertEqual(
            plan.tasks,
            [
                ("http://a/B02.tif", self._expected_dest("tile_a", "B02")),
                ("http://a/B04.tif", self._expected_dest("tile_a", "B04")),
                ("http://b/B02.tif", self._expected_dest("tile_b", "B02")),
                ("http://b/B04.tif", self._expected_dest("tile_b", "B04")),
            ],
        )


class TestDownloadConnectionsSetting:
    def test_values_are_kept_within_engine_bounds(self):
        from bdc_loader_plugin.core import download_engine
        from bdc_loader_plugin.core.download import CONNECTIONS_SETTING, download_connections

        class _S:
            def __init__(self, value):
                self.value_ = value

            def value(self, key, default=None):
                assert key == CONNECTIONS_SETTING
                return default if self.value_ is None else self.value_

        assert download_connections(_S(None)) == download_engine.DEFAULT_MAX_WORKERS == 24
        assert download_connections(_S("36")) == 36
        assert download_connections(_S(500)) == download_engine.MAX_WORKERS_LIMIT
        assert download_connections(_S(1)) == download_engine.MIN_WORKERS
        assert download_connections(_S("abc")) == 24


if __name__ == "__main__":
    unittest.main()
