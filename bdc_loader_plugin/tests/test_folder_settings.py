"""The main dialog opens when a folder chosen in Settings cannot hold files, and says so."""

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from bdc_loader_plugin import paths
from bdc_loader_plugin.ui.main_dialog import BDCLoaderDialog


def _settings(values):
    store = MagicMock()
    store.value.side_effect = lambda key, default=None, type=None: values.get(key, default)
    return store


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="needs symbolic links")
def test_a_download_folder_linked_to_a_missing_drive_is_replaced_for_the_session(tmp_path):
    profile = tmp_path / "profile"
    vrt_dir = tmp_path / "vrt"
    download_link = tmp_path / "bdc_downloads"
    os.symlink(tmp_path / "unmounted" / "bdc_downloads", download_link)
    values = {"bdc_loader/vrt_dir": str(vrt_dir), "bdc_loader/download_dir": str(download_link)}
    dialog = SimpleNamespace(_set_status=MagicMock())

    with (
        patch.object(paths, "_profile_dir", return_value=str(profile)),
        patch("bdc_loader_plugin.ui.main_dialog.QgsSettings", return_value=_settings(values)),
    ):
        BDCLoaderDialog._load_path_settings(dialog)
        BDCLoaderDialog._report_folder_problems(dialog)

    assert dialog._vrt_dir == str(vrt_dir)
    assert dialog._download_dir == os.path.join(str(profile), "bdc_loader", "downloads")
    assert os.path.isdir(dialog._download_dir)
    text, level = dialog._set_status.call_args.args
    assert str(download_link) in text and dialog._download_dir in text
    assert level == "warning"


def test_usable_folders_are_kept_without_a_warning(tmp_path):
    values = {"bdc_loader/vrt_dir": str(tmp_path / "vrt"), "bdc_loader/download_dir": str(tmp_path / "dl")}
    dialog = SimpleNamespace(_set_status=MagicMock())

    with patch("bdc_loader_plugin.ui.main_dialog.QgsSettings", return_value=_settings(values)):
        BDCLoaderDialog._load_path_settings(dialog)
        BDCLoaderDialog._report_folder_problems(dialog)

    assert (dialog._vrt_dir, dialog._download_dir) == (str(tmp_path / "vrt"), str(tmp_path / "dl"))
    dialog._set_status.assert_not_called()
