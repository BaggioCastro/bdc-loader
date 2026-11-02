#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_export_coverage.py — Tests for the CSV export of chart/export.py.

Covers: csv_rows, export_csv (with mocked QFileDialog) and the empty history guard.

Run: python3 -m pytest bdc_loader_plugin/tests/test_export_coverage.py -v
"""

import csv
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch


class TestExportCsvEmptyHistory(unittest.TestCase):
    """Tests for export_csv with empty or missing history."""

    @patch("bdc_loader_plugin.chart.export.QMessageBox")
    def test_empty_history_shows_warning(self, mock_msgbox):
        from bdc_loader_plugin.chart.export import export_csv

        parent = MagicMock()
        status = MagicMock()
        export_csv(parent, [], status)
        mock_msgbox.warning.assert_called_once()

    @patch("bdc_loader_plugin.chart.export.QMessageBox")
    def test_none_history_shows_warning(self, mock_msgbox):
        from bdc_loader_plugin.chart.export import export_csv

        parent = MagicMock()
        status = MagicMock()
        export_csv(parent, None, status)
        mock_msgbox.warning.assert_called_once()


class TestExportCsvFileOutput(unittest.TestCase):
    """Tests for export_csv writing actual CSV files."""

    def _make_history(self):
        return [
            {
                "id": 1,
                "lon": -45.123456,
                "lat": -12.654321,
                "start": "2023-01-01",
                "end": "2023-12-31",
                "label": "Point_1",
                "collection": "S2-16D-2",
                "bands": ["NDVI", "EVI"],
                "data": {
                    "NDVI": [
                        (datetime(2023, 1, 1), 5000.0),
                        (datetime(2023, 3, 1), 7000.0),
                        (datetime(2023, 2, 1), 6000.0),
                    ],
                    "EVI": [
                        (datetime(2023, 1, 1), 3000.0),
                        (datetime(2023, 2, 1), 4000.0),
                    ],
                },
            }
        ]

    @patch("bdc_loader_plugin.chart.export.QMessageBox")
    @patch("bdc_loader_plugin.chart.export.QFileDialog")
    def test_csv_written_correctly(self, mock_filedialog, mock_msgbox):
        from bdc_loader_plugin.chart.export import export_csv

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            csv_path = f.name

        try:
            mock_filedialog.getSaveFileName.return_value = (csv_path, "")
            parent = MagicMock()
            status = MagicMock()

            export_csv(parent, self._make_history(), status)

            with open(csv_path, "r") as f:
                reader = csv.reader(f)
                rows = list(reader)

            # Header + 2 band rows
            self.assertEqual(len(rows), 3)
            # Header should start with standard columns
            self.assertEqual(rows[0][:7], ["id", "longitude", "latitude", "start_date", "end_date", "label", "band"])
            # NDVI row should have band name
            self.assertEqual(rows[1][6], "NDVI")
            # Dates should be sorted
            dates = rows[0][7:]
            self.assertEqual(dates, sorted(dates))
        finally:
            os.unlink(csv_path)

    @patch("bdc_loader_plugin.chart.export.QMessageBox")
    @patch("bdc_loader_plugin.chart.export.QFileDialog")
    def test_user_cancels_dialog(self, mock_filedialog, mock_msgbox):
        from bdc_loader_plugin.chart.export import export_csv

        mock_filedialog.getSaveFileName.return_value = ("", "")
        parent = MagicMock()
        status = MagicMock()
        export_csv(parent, self._make_history(), status)
        # No file written, no error
        mock_msgbox.warning.assert_not_called()
        mock_msgbox.information.assert_not_called()

    @patch("bdc_loader_plugin.chart.export.QMessageBox")
    @patch("bdc_loader_plugin.chart.export.QFileDialog")
    def test_csv_with_empty_band_data(self, mock_filedialog, mock_msgbox):
        from bdc_loader_plugin.chart.export import export_csv

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            csv_path = f.name

        try:
            mock_filedialog.getSaveFileName.return_value = (csv_path, "")
            history = [
                {
                    "id": 1,
                    "lon": 0,
                    "lat": 0,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                    "label": "P1",
                    "bands": ["NDVI"],
                    "data": {"NDVI": []},  # Empty data
                }
            ]
            parent = MagicMock()
            status = MagicMock()
            export_csv(parent, history, status)

            with open(csv_path, "r") as f:
                content = f.read()
            # File should be empty — no valid data to write
            self.assertEqual(content.strip(), "")
        finally:
            os.unlink(csv_path)

    @patch("bdc_loader_plugin.chart.export.QMessageBox")
    @patch("bdc_loader_plugin.chart.export.QFileDialog")
    def test_success_updates_status(self, mock_filedialog, mock_msgbox):
        from bdc_loader_plugin.chart.export import export_csv

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            csv_path = f.name

        try:
            mock_filedialog.getSaveFileName.return_value = (csv_path, "")
            parent = MagicMock()
            status = MagicMock()
            export_csv(parent, self._make_history(), status)
            status.setText.assert_called_once()
            mock_msgbox.information.assert_called_once()
        finally:
            os.unlink(csv_path)


class TestCsvRowsByDate(unittest.TestCase):
    """Each value sits under its own date when points and bands have different dates."""

    def _entry(self, pid, data):
        return {
            "id": pid,
            "lon": -47.0,
            "lat": -15.0,
            "start": "2024-01-01",
            "end": "2024-02-28",
            "label": f"P{pid}",
            "bands": list(data),
            "data": data,
        }

    def test_values_follow_their_dates_across_bands_and_points(self):
        from bdc_loader_plugin.chart.export import csv_rows

        d1, d2, d3 = datetime(2024, 1, 1), datetime(2024, 1, 17), datetime(2024, 2, 2)
        history = [
            self._entry(1, {"NDVI": [(d1, 1.0), (d2, 2.0), (d3, 3.0)], "EVI": [(d3, 30.0), (d1, 10.0)]}),
            self._entry(2, {"NDVI": [(d2, 200.0), (d3, 300.0)]}),
        ]

        rows = csv_rows(history)

        self.assertEqual(rows[0][7:], ["2024-01-01", "2024-01-17", "2024-02-02"])
        self.assertEqual(rows[1][6:], ["NDVI", "1.0000", "2.0000", "3.0000"])
        self.assertEqual(rows[2][6:], ["EVI", "10.0000", "", "30.0000"])
        self.assertEqual(rows[3][6:], ["NDVI", "", "200.0000", "300.0000"])

    def test_a_history_without_values_has_no_rows(self):
        from bdc_loader_plugin.chart.export import csv_rows

        self.assertEqual(csv_rows([self._entry(1, {"NDVI": []})]), [])


if __name__ == "__main__":
    unittest.main()
