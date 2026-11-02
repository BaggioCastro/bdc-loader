#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_plugin_core.py — Tests for bdc_loader_plugin.py and logger.py core logic.

Covers: BDCLoaderPlugin._cleanup_temp_files, logger functions, TAG constant.

Run: python3 -m pytest bdc_loader_plugin/tests/test_plugin_core.py -v
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock


class TestCleanupTempFiles(unittest.TestCase):
    """Tests for BDCLoaderPlugin._cleanup_temp_files static method.

    The system temp folder is swapped for a private one, so the files of a
    QGIS running on this machine are never touched.
    """

    def setUp(self):
        self._private = tempfile.TemporaryDirectory()
        self._saved_tempdir = tempfile.tempdir
        tempfile.tempdir = self._private.name

    def tearDown(self):
        tempfile.tempdir = self._saved_tempdir
        self._private.cleanup()

    def test_removes_thumbs_dir(self):
        from bdc_loader_plugin.bdc_loader_plugin import BDCLoaderPlugin

        thumbs_dir = os.path.join(tempfile.gettempdir(), "bdc_loader_thumbs")
        os.makedirs(thumbs_dir, exist_ok=True)
        # Create a dummy file inside
        dummy = os.path.join(thumbs_dir, "test.png")
        with open(dummy, "w") as f:
            f.write("test")

        BDCLoaderPlugin._cleanup_temp_files()
        self.assertFalse(os.path.isdir(thumbs_dir))

    def test_removes_cutline_files(self):
        from bdc_loader_plugin.bdc_loader_plugin import BDCLoaderPlugin

        tmp = tempfile.gettempdir()
        names = ("bdc_cutline_test123.geojson", "bdc_shape_cutline_t.geojson", "bdc_extent_cutline_t.geojson")
        for name in names:
            with open(os.path.join(tmp, name), "w") as f:
                f.write("{}")

        BDCLoaderPlugin._cleanup_temp_files()
        for name in names:
            self.assertFalse(os.path.exists(os.path.join(tmp, name)), name)

    def test_no_error_when_nothing_to_clean(self):
        from bdc_loader_plugin.bdc_loader_plugin import BDCLoaderPlugin
        from bdc_loader_plugin.paths import temp_files

        BDCLoaderPlugin._cleanup_temp_files()
        BDCLoaderPlugin._cleanup_temp_files()
        self.assertEqual(temp_files(), [])


class TestLogger(unittest.TestCase):
    """Tests for logger.py functions."""

    def test_info_calls_log_message(self):
        from bdc_loader_plugin.logger import info

        qgs_log = sys.modules["qgis.core"].QgsMessageLog
        qgs_log.logMessage = MagicMock()
        info("Test info message")
        qgs_log.logMessage.assert_called_once()
        args = qgs_log.logMessage.call_args[0]
        self.assertEqual(args[0], "Test info message")
        self.assertEqual(args[1], "BDC Loader")

    def test_warning_calls_log_message(self):
        from bdc_loader_plugin.logger import warning

        qgs_log = sys.modules["qgis.core"].QgsMessageLog
        qgs_log.logMessage = MagicMock()
        warning("Test warning")
        qgs_log.logMessage.assert_called_once()

    def test_error_calls_log_message(self):
        from bdc_loader_plugin.logger import error

        qgs_log = sys.modules["qgis.core"].QgsMessageLog
        qgs_log.logMessage = MagicMock()
        error("Test error")
        qgs_log.logMessage.assert_called_once()

    def test_info_converts_non_string(self):
        from bdc_loader_plugin.logger import info

        qgs_log = sys.modules["qgis.core"].QgsMessageLog
        qgs_log.logMessage = MagicMock()
        info(42)
        args = qgs_log.logMessage.call_args[0]
        self.assertEqual(args[0], "42")


if __name__ == "__main__":
    unittest.main()
