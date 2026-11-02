#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_status_logging.py — Tests for BDCLoaderDialog._set_status's bridge into
the persistent activity log (ui/log_panel.py).

Every download and VRT-generation status update reaches the log as well as
the transient status label, throttled so a
long-running download's ~100ms progress ticks don't flood it with thousands
of near-identical lines.

Run: python3 -m pytest bdc_loader_plugin/tests/test_status_logging.py -v
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _make_dialog():
    import bdc_loader_plugin.ui.main_dialog as module

    # A real BDCLoaderDialog instance resolves _STATUS_LOG_THROTTLE_S via
    # normal class-attribute inheritance; this bare stand-in needs it copied
    # over explicitly since it isn't actually an instance of the class.
    return SimpleNamespace(
        _status_icon=MagicMock(),
        status_label=MagicMock(),
        _stac_online=None,
        _STATUS_LOG_THROTTLE_S=module.BDCLoaderDialog._STATUS_LOG_THROTTLE_S,
    )


class TestSetStatusLogging(unittest.TestCase):
    def test_first_call_always_logs(self):
        import bdc_loader_plugin.ui.main_dialog as module

        dialog = _make_dialog()
        with patch.object(module, "_log_info") as log_info:
            module.BDCLoaderDialog._set_status(dialog, "Starting up", "info")

        log_info.assert_called_once_with("Starting up")

    def test_error_status_routes_to_log_error(self):
        import bdc_loader_plugin.ui.main_dialog as module

        dialog = _make_dialog()
        with patch.object(module, "_log_error") as log_error:
            module.BDCLoaderDialog._set_status(dialog, "Download failed for X", "error")

        log_error.assert_called_once_with("Download failed for X")

    def test_warning_status_routes_to_log_warning(self):
        import bdc_loader_plugin.ui.main_dialog as module

        dialog = _make_dialog()
        with patch.object(module, "_log_warning") as log_warning:
            module.BDCLoaderDialog._set_status(dialog, "Download cancelled", "warning")

        log_warning.assert_called_once_with("Download cancelled")

    def test_rapid_same_type_progress_ticks_are_throttled(self):
        import bdc_loader_plugin.ui.main_dialog as module

        dialog = _make_dialog()
        with patch.object(module, "_log_info") as log_info:
            module.BDCLoaderDialog._set_status(dialog, "Downloading: 10%", "download")
            module.BDCLoaderDialog._set_status(dialog, "Downloading: 20%", "download")
            module.BDCLoaderDialog._set_status(dialog, "Downloading: 30%", "download")

        log_info.assert_called_once_with("Downloading: 10%")

    def test_status_type_change_always_logs_even_if_rapid(self):
        import bdc_loader_plugin.ui.main_dialog as module

        dialog = _make_dialog()
        with patch.object(module, "_log_info") as log_info, patch.object(module, "_log_error") as log_error:
            module.BDCLoaderDialog._set_status(dialog, "Downloading: 90%", "download")
            module.BDCLoaderDialog._set_status(dialog, "Download failed", "error")

        log_info.assert_called_once_with("Downloading: 90%")
        log_error.assert_called_once_with("Download failed")

    def test_same_type_logs_again_after_throttle_window_elapses(self):
        import bdc_loader_plugin.ui.main_dialog as module

        dialog = _make_dialog()
        with patch.object(module, "_log_info") as log_info:
            module.BDCLoaderDialog._set_status(dialog, "Downloading: 10%", "download")
            # simulate the throttle window having elapsed
            dialog._last_logged_status_time -= module.BDCLoaderDialog._STATUS_LOG_THROTTLE_S + 1
            module.BDCLoaderDialog._set_status(dialog, "Downloading: 50%", "download")

        self.assertEqual(log_info.call_count, 2)

    def test_status_label_is_still_updated(self):
        import bdc_loader_plugin.ui.main_dialog as module

        dialog = _make_dialog()
        with patch.object(module, "_log_info"):
            module.BDCLoaderDialog._set_status(dialog, "Hello", "info")

        dialog.status_label.setText.assert_called_once_with("Hello")


if __name__ == "__main__":
    unittest.main()
