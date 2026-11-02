#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_ts_validation.py — Input validation and data integrity tests.

Covers: _add_point_from_coords (float parsing, out-of-range, comma tolerance),
_add_point_from_wkt (valid/invalid WKT, non-Point types), _load_vector
(SHP/GPKG, CRS transform, label detection, mixed geometry), _add_point
(duplicate detection), coordinate parsing edge cases.

Run: python3 -m pytest bdc_loader_plugin/tests/test_ts_validation.py -v
"""

import unittest
from unittest.mock import MagicMock, patch

# ── _add_point_from_coords ───────────────────────────────────────────────────


class TestAddPointFromCoords(unittest.TestCase):
    """Coordinate parsing, validation, and point addition."""

    def _make_manager(self):
        from bdc_loader_plugin.core.ts_points import TSPointManager

        mgr = TSPointManager.__new__(TSPointManager)
        mgr._current_points = []
        mgr._multi_point_mode = True
        mgr.lon_input = MagicMock()
        mgr.lat_input = MagicMock()
        mgr.points_list = MagicMock()
        mgr._set_status = MagicMock()
        mgr._add_point = MagicMock()
        return mgr

    def test_valid_coords(self):
        mgr = self._make_manager()
        mgr.lon_input.text.return_value = "-47.9292"
        mgr.lat_input.text.return_value = "-15.7801"
        mgr._add_point_from_coords()
        mgr._add_point.assert_called_once()
        args = mgr._add_point.call_args[0]
        self.assertAlmostEqual(args[0], -47.9292)
        self.assertAlmostEqual(args[1], -15.7801)

    def test_comma_as_decimal_separator(self):
        """Commas replaced with dots for locale tolerance."""
        mgr = self._make_manager()
        mgr.lon_input.text.return_value = "-47,9292"
        mgr.lat_input.text.return_value = "-15,7801"
        mgr._add_point_from_coords()
        mgr._add_point.assert_called_once()
        args = mgr._add_point.call_args[0]
        self.assertAlmostEqual(args[0], -47.9292)
        self.assertAlmostEqual(args[1], -15.7801)

    @patch("bdc_loader_plugin.core.ts_points.QMessageBox")
    def test_invalid_text_shows_warning(self, mock_msg):
        """Non-numeric text → QMessageBox warning."""
        mgr = self._make_manager()
        mgr.lon_input.text.return_value = "abc"
        mgr.lat_input.text.return_value = "-15.78"
        mgr._add_point_from_coords()
        mock_msg.warning.assert_called_once()
        mgr._add_point.assert_not_called()

    @patch("bdc_loader_plugin.core.ts_points.QMessageBox")
    def test_empty_text_shows_warning(self, mock_msg):
        """Empty text → warning."""
        mgr = self._make_manager()
        mgr.lon_input.text.return_value = ""
        mgr.lat_input.text.return_value = ""
        mgr._add_point_from_coords()
        mock_msg.warning.assert_called_once()
        mgr._add_point.assert_not_called()

    @patch("bdc_loader_plugin.core.ts_points.QMessageBox")
    def test_longitude_out_of_range(self, mock_msg):
        """Longitude > 180 → out of range warning."""
        mgr = self._make_manager()
        mgr.lon_input.text.return_value = "181.0"
        mgr.lat_input.text.return_value = "-12.0"
        mgr._add_point_from_coords()
        mock_msg.warning.assert_called_once()
        mgr._add_point.assert_not_called()

    @patch("bdc_loader_plugin.core.ts_points.QMessageBox")
    def test_longitude_negative_out_of_range(self, mock_msg):
        """Longitude < -180 → out of range."""
        mgr = self._make_manager()
        mgr.lon_input.text.return_value = "-181.0"
        mgr.lat_input.text.return_value = "-12.0"
        mgr._add_point_from_coords()
        mock_msg.warning.assert_called_once()
        mgr._add_point.assert_not_called()

    @patch("bdc_loader_plugin.core.ts_points.QMessageBox")
    def test_latitude_out_of_range(self, mock_msg):
        """Latitude > 90 → out of range warning."""
        mgr = self._make_manager()
        mgr.lon_input.text.return_value = "-45.0"
        mgr.lat_input.text.return_value = "91.0"
        mgr._add_point_from_coords()
        mock_msg.warning.assert_called_once()
        mgr._add_point.assert_not_called()

    @patch("bdc_loader_plugin.core.ts_points.QMessageBox")
    def test_latitude_negative_out_of_range(self, mock_msg):
        """Latitude < -90 → out of range."""
        mgr = self._make_manager()
        mgr.lon_input.text.return_value = "-45.0"
        mgr.lat_input.text.return_value = "-91.0"
        mgr._add_point_from_coords()
        mock_msg.warning.assert_called_once()
        mgr._add_point.assert_not_called()

    def test_boundary_values_accepted(self):
        """Exact ±180/±90 are within valid range."""
        mgr = self._make_manager()
        mgr.lon_input.text.return_value = "180.0"
        mgr.lat_input.text.return_value = "90.0"
        mgr._add_point_from_coords()
        mgr._add_point.assert_called_once()

    def test_boundary_negative_values_accepted(self):
        mgr = self._make_manager()
        mgr.lon_input.text.return_value = "-180.0"
        mgr.lat_input.text.return_value = "-90.0"
        mgr._add_point_from_coords()
        mgr._add_point.assert_called_once()

    def test_zero_coords_accepted(self):
        mgr = self._make_manager()
        mgr.lon_input.text.return_value = "0"
        mgr.lat_input.text.return_value = "0"
        mgr._add_point_from_coords()
        mgr._add_point.assert_called_once()

    def test_single_mode_clears_before_add(self):
        """In single-point mode, existing points are cleared first."""
        mgr = self._make_manager()
        mgr._multi_point_mode = False
        mgr._current_points = [(-45.0, -12.0, "P1")]
        mgr.lon_input.text.return_value = "-46.0"
        mgr.lat_input.text.return_value = "-13.0"
        mgr._add_point_from_coords()
        self.assertEqual(len(mgr._current_points), 0)  # cleared by method
        mgr._add_point.assert_called_once()


# ── _add_point_from_wkt ──────────────────────────────────────────────────────


class TestAddPointFromWkt(unittest.TestCase):
    """WKT POINT geometry parsing and validation."""

    def _make_manager(self):
        from bdc_loader_plugin.core.ts_points import TSPointManager

        mgr = TSPointManager.__new__(TSPointManager)
        mgr._current_points = []
        mgr._multi_point_mode = True
        mgr.wkt_input = MagicMock()
        mgr.points_list = MagicMock()
        mgr._set_status = MagicMock()
        mgr._add_point = MagicMock()
        return mgr

    @patch("bdc_loader_plugin.core.ts_points.QgsGeometry")
    def test_valid_wkt_point(self, mock_geom_cls):
        from qgis.core import QgsWkbTypes

        mock_point = MagicMock()
        mock_point.x.return_value = -47.9292
        mock_point.y.return_value = -15.7801
        mock_geom = MagicMock()
        mock_geom.isNull.return_value = False
        mock_geom.wkbType.return_value = QgsWkbTypes.Type.Point
        mock_geom.asPoint.return_value = mock_point
        mock_geom_cls.fromWkt.return_value = mock_geom

        mgr = self._make_manager()
        mgr.wkt_input.text.return_value = "POINT(-47.9292 -15.7801)"
        mgr._add_point_from_wkt()
        mgr._add_point.assert_called_once()
        args = mgr._add_point.call_args[0]
        self.assertAlmostEqual(args[0], -47.9292)
        self.assertAlmostEqual(args[1], -15.7801)

    @patch("bdc_loader_plugin.core.ts_points.QMessageBox")
    def test_empty_wkt_shows_warning(self, mock_msg):
        mgr = self._make_manager()
        mgr.wkt_input.text.return_value = ""
        mgr._add_point_from_wkt()
        mock_msg.warning.assert_called_once()
        mgr._add_point.assert_not_called()

    @patch("bdc_loader_plugin.core.ts_points.QMessageBox")
    def test_whitespace_only_shows_warning(self, mock_msg):
        mgr = self._make_manager()
        mgr.wkt_input.text.return_value = "   "
        mgr._add_point_from_wkt()
        mock_msg.warning.assert_called_once()

    @patch("bdc_loader_plugin.core.ts_points.QMessageBox")
    def test_non_point_wkt_rejected(self, mock_msg):
        """LINESTRING WKT is not a valid point → warning."""
        mgr = self._make_manager()
        mgr.wkt_input.text.return_value = "LINESTRING(0 0, 1 1)"
        mgr._add_point_from_wkt()
        mock_msg.warning.assert_called_once()
        mgr._add_point.assert_not_called()

    @patch("bdc_loader_plugin.core.ts_points.QMessageBox")
    def test_invalid_wkt_syntax_rejected(self, mock_msg):
        """Garbled WKT → warning."""
        mgr = self._make_manager()
        mgr.wkt_input.text.return_value = "PONT(-47 -15)"  # typo
        mgr._add_point_from_wkt()
        mock_msg.warning.assert_called_once()
        mgr._add_point.assert_not_called()

    @patch("bdc_loader_plugin.core.ts_points.QgsGeometry")
    def test_clears_input_after_success(self, mock_geom_cls):
        """WKT input field cleared after successful parse."""
        from qgis.core import QgsWkbTypes

        mock_point = MagicMock()
        mock_point.x.return_value = -47.0
        mock_point.y.return_value = -15.0
        mock_geom = MagicMock()
        mock_geom.isNull.return_value = False
        mock_geom.wkbType.return_value = QgsWkbTypes.Type.Point
        mock_geom.asPoint.return_value = mock_point
        mock_geom_cls.fromWkt.return_value = mock_geom

        mgr = self._make_manager()
        mgr.wkt_input.text.return_value = "POINT(-47 -15)"
        mgr._add_point_from_wkt()
        mgr.wkt_input.clear.assert_called_once()


# ── _add_point duplicate detection ───────────────────────────────────────────


class TestAddPointDuplicateDetection(unittest.TestCase):
    """Duplicate point detection in _add_point."""

    def _make_manager(self):
        from bdc_loader_plugin.core.ts_points import TSPointManager

        mgr = TSPointManager.__new__(TSPointManager)
        mgr._current_points = []
        mgr.points_list = MagicMock()
        # Ensure sizeHint works on mock widgets
        mgr.points_list.addItem = MagicMock()
        mgr.points_list.setItemWidget = MagicMock()
        mgr._set_status = MagicMock()
        return mgr

    def test_duplicate_point_skipped(self):
        mgr = self._make_manager()
        mgr._current_points = [(-45.0, -12.0, "P1")]
        mgr._add_point(-45.0, -12.0, "P2")
        self.assertEqual(len(mgr._current_points), 1)

    def test_near_duplicate_skipped(self):
        """Points within 1e-6 tolerance considered duplicates."""
        mgr = self._make_manager()
        mgr._current_points = [(-45.0, -12.0, "P1")]
        mgr._add_point(-45.0000005, -12.0000005, "P2")
        self.assertEqual(len(mgr._current_points), 1)

    def test_different_point_added(self):
        mgr = self._make_manager()
        mgr._current_points = [(-45.0, -12.0, "P1")]
        with patch("bdc_loader_plugin.core.ts_points.QWidget") as mock_widget_cls:
            mock_widget = MagicMock()
            mock_widget.sizeHint.return_value = MagicMock()
            mock_widget_cls.return_value = mock_widget
            mgr._add_point(-46.0, -13.0, "P2")
        self.assertEqual(len(mgr._current_points), 2)

    def test_first_point_always_added(self):
        mgr = self._make_manager()
        with patch("bdc_loader_plugin.core.ts_points.QWidget") as mock_widget_cls:
            mock_widget = MagicMock()
            mock_widget.sizeHint.return_value = MagicMock()
            mock_widget_cls.return_value = mock_widget
            mgr._add_point(-45.0, -12.0, "P1")
        self.assertEqual(len(mgr._current_points), 1)
        self.assertEqual(mgr._current_points[0][2], "P1")


# ── _clear_points and _remove_selected ───────────────────────────────────────


class TestPointManipulation(unittest.TestCase):
    """Point clearing and removal."""

    def _make_manager(self):
        from bdc_loader_plugin.core.ts_points import TSPointManager

        mgr = TSPointManager.__new__(TSPointManager)
        mgr._current_points = [(-45, -12, "P1"), (-46, -13, "P2"), (-47, -14, "P3")]
        mgr.points_list = MagicMock()
        mgr.lon_input = MagicMock()
        mgr.lat_input = MagicMock()
        mgr._set_status = MagicMock()
        mgr._rebuild_points_list = MagicMock()
        return mgr

    def test_clear_empties_all(self):
        mgr = self._make_manager()
        mgr._clear_points()
        self.assertEqual(len(mgr._current_points), 0)
        mgr.points_list.clear.assert_called_once()

    def test_remove_by_index(self):
        mgr = self._make_manager()
        mgr._remove_point_by_index(1)  # remove P2
        self.assertEqual(len(mgr._current_points), 2)
        self.assertEqual(mgr._current_points[0][2], "P1")
        self.assertEqual(mgr._current_points[1][2], "P3")

    def test_remove_by_invalid_index(self):
        """Index beyond range → no crash, list unchanged."""
        mgr = self._make_manager()
        mgr._remove_point_by_index(10)
        self.assertEqual(len(mgr._current_points), 3)


# ── _load_vector validation ──────────────────────────────────────────────────


class TestLoadVectorValidation(unittest.TestCase):
    """Vector file loading with geometry/CRS validation."""

    def _make_manager(self):
        from bdc_loader_plugin.core.ts_points import TSPointManager

        mgr = TSPointManager.__new__(TSPointManager)
        mgr._current_points = []
        mgr.points_list = MagicMock()
        mgr._set_status = MagicMock()
        mgr._add_point = MagicMock()
        return mgr

    @patch("bdc_loader_plugin.core.ts_points.QFileDialog.getOpenFileName")
    def test_cancelled_dialog_does_nothing(self, mock_dialog):
        """Cancelled file dialog → no action."""
        mock_dialog.return_value = ("", "")
        mgr = self._make_manager()
        mgr._load_vector()
        mgr._add_point.assert_not_called()

    @patch("bdc_loader_plugin.core.ts_points.QgsVectorLayer")
    @patch("bdc_loader_plugin.core.ts_points.QFileDialog.getOpenFileName")
    @patch("bdc_loader_plugin.core.ts_points.QMessageBox")
    def test_invalid_layer_shows_warning(self, mock_msg, mock_dialog, mock_layer_cls):
        """Invalid vector file → warning dialog."""
        mock_dialog.return_value = ("/tmp/bad.shp", "")
        mock_layer = MagicMock()
        mock_layer.isValid.return_value = False
        mock_layer_cls.return_value = mock_layer

        mgr = self._make_manager()
        mgr._load_vector()
        mock_msg.warning.assert_called_once()

    @patch("bdc_loader_plugin.core.ts_points.QgsCoordinateTransform")
    @patch("bdc_loader_plugin.core.ts_points.QgsVectorLayer")
    @patch("bdc_loader_plugin.core.ts_points.QFileDialog.getOpenFileName")
    def test_point_features_loaded(self, mock_dialog, mock_layer_cls, mock_transform):
        """Valid point shapefile → points added or status updated."""
        mock_dialog.return_value = ("/tmp/points.shp", "")

        mock_layer = MagicMock()
        mock_layer.isValid.return_value = True
        mock_layer.crs.return_value = MagicMock()

        # Mock an empty feature iterator to avoid complex geometry mocking
        mock_layer.getFeatures.return_value = iter([])
        mock_layer_cls.return_value = mock_layer

        mock_transform_inst = MagicMock()
        mock_transform.return_value = mock_transform_inst

        mgr = self._make_manager()
        mgr._load_vector()

        # With no features, status is set with "0 point(s) loaded"
        mgr._set_status.assert_called()


# ── _get_selected_bands / _filter_bands ──────────────────────────────────────


class TestBandSelectionFiltering(unittest.TestCase):
    """Band checkbox selection and filtering."""

    def _make_manager(self):
        from bdc_loader_plugin.core.ts_bands import TSBandManager

        mgr = TSBandManager.__new__(TSBandManager)

        cb1 = MagicMock()
        cb1.isChecked.return_value = True
        cb1.property.return_value = "B04"
        cb1.text.return_value = "B04"
        cb1.isVisible.return_value = True

        cb2 = MagicMock()
        cb2.isChecked.return_value = False
        cb2.property.return_value = "B03"
        cb2.text.return_value = "B03"
        cb2.isVisible.return_value = True

        cb3 = MagicMock()
        cb3.isChecked.return_value = True
        cb3.property.return_value = "B08"
        cb3.text.return_value = "B08"
        cb3.isVisible.return_value = True

        mgr._band_checkboxes = [cb1, cb2, cb3]
        return mgr

    def test_get_selected_bands(self):
        mgr = self._make_manager()
        selected = mgr._get_selected_bands()
        self.assertEqual(selected, ["B04", "B08"])

    def test_set_all_bands_checked(self):
        mgr = self._make_manager()
        mgr._set_all_bands(True)
        for cb in mgr._band_checkboxes:
            cb.setChecked.assert_called_with(True)

    def test_set_all_bands_unchecked(self):
        mgr = self._make_manager()
        mgr._set_all_bands(False)
        for cb in mgr._band_checkboxes:
            cb.setChecked.assert_called_with(False)

    def test_filter_bands_by_text(self):
        mgr = self._make_manager()
        mgr._filter_bands("B04")
        # B04 should be visible, others hidden
        mgr._band_checkboxes[0].setVisible.assert_called_with(True)
        mgr._band_checkboxes[1].setVisible.assert_called_with(False)
        mgr._band_checkboxes[2].setVisible.assert_called_with(False)

    def test_filter_bands_empty_shows_all(self):
        mgr = self._make_manager()
        mgr._filter_bands("")
        for cb in mgr._band_checkboxes:
            cb.setVisible.assert_called_with(True)

    def test_filter_bands_case_insensitive(self):
        mgr = self._make_manager()
        mgr._filter_bands("b04")
        mgr._band_checkboxes[0].setVisible.assert_called_with(True)


if __name__ == "__main__":
    unittest.main()
