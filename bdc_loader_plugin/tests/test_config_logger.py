#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_config_logger.py — tests for config.py and logger.py

Covers: ConfigManager get/set, QgsSettings persistence, logger levels,
edge cases, reset between tests.

Run: python3 -m pytest bdc_loader_plugin/tests/test_config_logger.py -v
"""

import unittest

from bdc_loader_plugin.tests.qgis_mock import reset_state

# ── ConfigManager Tests ──────────────────────────────────────────────────────


# ── Logger Tests ─────────────────────────────────────────────────────────────


class TestLoggerOutput(unittest.TestCase):
    """Messages are sent to QgsMessageLog."""

    def setUp(self):
        reset_state()

    def test_info_logs_message(self):
        from qgis.core import QgsMessageLog

        from bdc_loader_plugin.logger import info

        info("Test info message")
        self.assertGreater(len(QgsMessageLog._messages), 0)
        last_msg = QgsMessageLog._messages[-1]
        self.assertEqual(last_msg[0], "Test info message")
        self.assertEqual(last_msg[2], 0)  # Info level

    def test_warning_logs_message(self):
        from qgis.core import QgsMessageLog

        from bdc_loader_plugin.logger import warning

        warning("Test warning")
        last_msg = QgsMessageLog._messages[-1]
        self.assertEqual(last_msg[0], "Test warning")
        self.assertEqual(last_msg[2], 1)  # Warning level

    def test_error_logs_message(self):
        from qgis.core import QgsMessageLog

        from bdc_loader_plugin.logger import error

        error("Test error")
        last_msg = QgsMessageLog._messages[-1]
        self.assertEqual(last_msg[0], "Test error")
        self.assertEqual(last_msg[2], 2)  # Critical level

    def test_tag_is_bdc(self):
        from qgis.core import QgsMessageLog

        from bdc_loader_plugin.logger import TAG, info

        info("Tag test")
        last_msg = QgsMessageLog._messages[-1]
        self.assertEqual(last_msg[1], TAG)

    def test_numeric_message_coerced(self):
        """The logger accepts non-string values (converted with str())."""
        from qgis.core import QgsMessageLog

        from bdc_loader_plugin.logger import info

        info(42)
        last_msg = QgsMessageLog._messages[-1]
        self.assertEqual(last_msg[0], "42")

    def test_none_message_coerced(self):
        from qgis.core import QgsMessageLog

        from bdc_loader_plugin.logger import info

        info(None)
        last_msg = QgsMessageLog._messages[-1]
        self.assertEqual(last_msg[0], "None")


class TestLogFileSize(unittest.TestCase):
    """The JSONL log keeps its last _MAX_FILE_LINES lines across sessions."""

    def test_the_first_entry_of_a_session_cuts_the_file(self):
        import os
        import tempfile
        from unittest.mock import patch

        from bdc_loader_plugin import logger

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bdc_loader.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(f'{{"msg": "old {i}"}}\n' for i in range(logger._MAX_FILE_LINES + 500))
            with patch.object(logger, "_log_path", return_value=path), patch.object(logger, "_file_trimmed", False):
                logger.info("first of the session")
                logger.info("second")
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()

        self.assertEqual(len(lines), logger._MAX_FILE_LINES + 2)
        self.assertIn('"old 500"', lines[0])
        self.assertIn("second", lines[-1])


if __name__ == "__main__":
    unittest.main()
