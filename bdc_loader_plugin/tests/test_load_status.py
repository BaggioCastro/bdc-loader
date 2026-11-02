"""The status line names the step of a layer load that is running, and when the wait is on the BDC."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from bdc_loader_plugin.core.vrt_overview_run import VrtOverviewRun


def _dialog():
    return SimpleNamespace(_set_status=MagicMock(), _display_status=None)


def test_the_overview_step_shows_its_count_and_time():
    dialog = _dialog()
    VrtOverviewRun._show_display_progress(dialog, 7, 24, 5.2, False, True)
    dialog._set_status.assert_called_once_with(
        "Preparing layers for display (overview and contrast): 7/24 (5 s)", "info"
    )


def test_a_stall_says_the_wait_is_on_the_bdc_server():
    dialog = _dialog()
    VrtOverviewRun._show_display_progress(dialog, 7, 24, 18.0, True, True)
    text, _level = dialog._set_status.call_args.args
    assert text.endswith(", waiting for the BDC server")


def test_without_overviews_only_the_contrast_step_is_named():
    dialog = _dialog()
    VrtOverviewRun._show_display_progress(dialog, 3, 24, 2.0, False, False)
    text, _level = dialog._set_status.call_args.args
    assert text == "Preparing layers for display (contrast): 3/24 (2 s)"


def test_the_same_line_is_not_set_again_on_every_poll():
    dialog = _dialog()
    for _ in range(5):
        VrtOverviewRun._show_display_progress(dialog, 7, 24, 5.2, False, True)
    assert dialog._set_status.call_count == 1
