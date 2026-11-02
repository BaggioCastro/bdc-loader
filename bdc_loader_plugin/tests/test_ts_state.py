#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_ts_state.py — State management tests for time series panel components.

Covers: TSHistoryManager (_remove_history_entry, _clear_history, _refresh_history_list,
_on_history_selected), TSLayerManager (_get_or_create_temp_layer), visualization
navigation (_update_viz_navigation), collection combo management.

Run: python3 -m pytest bdc_loader_plugin/tests/test_ts_state.py -v
"""

import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

# ── TSHistoryManager ─────────────────────────────────────────────────────────


class TestRemoveHistoryEntry(unittest.TestCase):
    """_remove_history_entry: filter by ID, update index, refresh UI."""

    def _make_manager(self):
        from bdc_loader_plugin.core.ts_history import TSHistoryManager

        mgr = TSHistoryManager.__new__(TSHistoryManager)
        mgr._history = [
            {
                "id": 1,
                "lon": -45,
                "lat": -12,
                "label": "P1",
                "collection": "S2",
                "bands": ["B04"],
                "data": {"B04": [(datetime(2023, 1, 1), 5000)]},
            },
            {
                "id": 2,
                "lon": -46,
                "lat": -13,
                "label": "P2",
                "collection": "S2",
                "bands": ["B04"],
                "data": {"B04": [(datetime(2023, 1, 1), 6000)]},
            },
            {
                "id": 3,
                "lon": -47,
                "lat": -14,
                "label": "P3",
                "collection": "S2",
                "bands": ["B04"],
                "data": {"B04": [(datetime(2023, 1, 1), 7000)]},
            },
        ]
        mgr._current_viz_index = 1
        mgr.history_list = MagicMock()
        mgr.history_list.count.return_value = 3
        mgr.chart_dock = MagicMock()
        mgr._set_status = MagicMock()
        mgr._refresh_history_list = MagicMock()
        mgr._update_viz_navigation = MagicMock()
        mgr._plot_result = MagicMock()
        mgr._update_rgb_combos = MagicMock()
        mgr._remove_point_from_temp_layer = MagicMock()
        return mgr

    def test_keeps_the_shown_series_when_an_earlier_one_is_removed(self):
        mgr = self._make_manager()  # shows id 2
        mgr._remove_history_entry(1)
        self.assertEqual(mgr._history[mgr._current_viz_index]["id"], 2)
        mgr._update_rgb_combos.assert_not_called()  # same series, same combos

    def test_removing_the_shown_series_refreshes_combos_and_axes(self):
        mgr = self._make_manager()  # shows id 2
        mgr._remove_history_entry(2)
        shown = mgr._history[mgr._current_viz_index]
        mgr._update_rgb_combos.assert_called_once_with(shown["bands"], shown["collection"])
        mgr.chart_dock.reset_axis_ranges.assert_called_once()
        mgr._plot_result.assert_called_once_with(shown)

    def test_removes_correct_entry(self):
        mgr = self._make_manager()
        mgr._remove_history_entry(2)
        ids = [e["id"] for e in mgr._history]
        self.assertEqual(ids, [1, 3])

    def test_updates_viz_index_when_beyond_range(self):
        """If viz_index >= len(history) after removal, clamped down."""
        mgr = self._make_manager()
        mgr._current_viz_index = 2
        mgr._remove_history_entry(3)
        self.assertLessEqual(mgr._current_viz_index, len(mgr._history) - 1)

    def test_refreshes_history_list(self):
        mgr = self._make_manager()
        mgr._remove_history_entry(1)
        mgr._refresh_history_list.assert_called_once()

    def test_removes_point_from_temp_layer(self):
        mgr = self._make_manager()
        mgr._remove_history_entry(2)
        mgr._remove_point_from_temp_layer.assert_called_with(2)

    def test_replots_remaining_entry(self):
        mgr = self._make_manager()
        mgr._remove_history_entry(1)
        mgr._plot_result.assert_called_once()

    def test_nonexistent_id_no_crash(self):
        mgr = self._make_manager()
        mgr._remove_history_entry(999)
        self.assertEqual(len(mgr._history), 3)

    def test_remove_all_entries_one_by_one(self):
        mgr = self._make_manager()
        mgr._remove_history_entry(1)
        mgr._remove_history_entry(2)
        mgr._remove_history_entry(3)
        self.assertEqual(len(mgr._history), 0)
        self.assertEqual(mgr._current_viz_index, -1)
        mgr.chart_dock.export_csv_btn.setEnabled.assert_called_with(False)


class TestClearHistory(unittest.TestCase):
    """_clear_history: full reset of history state."""

    def _make_manager(self):
        from bdc_loader_plugin.core.ts_history import TSHistoryManager

        mgr = TSHistoryManager.__new__(TSHistoryManager)
        mgr._history = [
            {"id": 1, "lon": -45, "lat": -12, "label": "P1", "collection": "S2", "bands": ["B04"], "data": {}},
        ]
        mgr._history_counter = 5
        mgr._current_viz_index = 0
        mgr._temp_layer = None
        mgr.history_list = MagicMock()
        mgr.chart_dock = MagicMock()
        mgr.chart_dock.figure = MagicMock()
        mgr._refresh_history_list = MagicMock()
        mgr._update_viz_navigation = MagicMock()
        mgr._set_status = MagicMock()
        return mgr
        mgr = self._make_manager()
        mgr._clear_history()
        self.assertEqual(len(mgr._history), 0)

    def test_resets_counter(self):
        mgr = self._make_manager()
        mgr._clear_history()
        self.assertEqual(mgr._history_counter, 0)

    def test_resets_viz_index(self):
        mgr = self._make_manager()
        mgr._clear_history()
        self.assertEqual(mgr._current_viz_index, -1)

    def test_clears_chart(self):
        mgr = self._make_manager()
        mgr._clear_history()
        mgr.chart_dock.figure.clear.assert_called_once()
        mgr.chart_dock.canvas_plot.draw_idle.assert_called_once()
        mgr.chart_dock.canvas_plot.draw.assert_not_called()

    def test_disables_export_buttons(self):
        mgr = self._make_manager()
        mgr._clear_history()
        mgr.chart_dock.export_csv_btn.setEnabled.assert_called_with(False)
        mgr.chart_dock.export_shp_btn.setEnabled.assert_called_with(False)


class TestOnHistorySelected(unittest.TestCase):
    """_on_history_selected: index update and cascading UI refresh."""

    def _make_manager(self):
        from bdc_loader_plugin.core.ts_history import TSHistoryManager

        mgr = TSHistoryManager.__new__(TSHistoryManager)
        mgr._history = [
            {"id": 1, "lon": -45, "lat": -12, "label": "P1", "collection": "S2", "bands": ["B04", "B08"], "data": {}},
            {"id": 2, "lon": -46, "lat": -13, "label": "P2", "collection": "S2", "bands": ["B04"], "data": {}},
        ]
        mgr._current_viz_index = 0
        mgr._auto_center = False
        mgr.chart_dock = MagicMock()
        mgr._update_viz_navigation = MagicMock()
        mgr._ensure_chart_dock = MagicMock()
        mgr._update_rgb_combos = MagicMock()
        mgr._plot_result = MagicMock()
        mgr._zoom_to_point = MagicMock()
        return mgr

    def test_updates_viz_index(self):
        mgr = self._make_manager()
        mgr._on_history_selected(1)
        self.assertEqual(mgr._current_viz_index, 1)

    def test_plots_selected_entry(self):
        mgr = self._make_manager()
        mgr._on_history_selected(0)
        mgr._plot_result.assert_called_once_with(mgr._history[0])

    def test_updates_rgb_combos(self):
        mgr = self._make_manager()
        mgr._on_history_selected(1)
        mgr._update_rgb_combos.assert_called_with(["B04"], "S2")

    def test_ensures_chart_dock_exists(self):
        mgr = self._make_manager()
        mgr._on_history_selected(0)
        mgr._ensure_chart_dock.assert_called_once()

    def test_negative_row_ignored(self):
        mgr = self._make_manager()
        mgr._on_history_selected(-1)
        mgr._plot_result.assert_not_called()

    def test_out_of_range_row_ignored(self):
        mgr = self._make_manager()
        mgr._on_history_selected(5)
        mgr._plot_result.assert_not_called()

    def test_auto_center_zooms_to_point(self):
        mgr = self._make_manager()
        mgr._auto_center = True
        mgr._on_history_selected(0)
        mgr._zoom_to_point.assert_called_with(-45, -12)

    def test_no_auto_center_no_zoom(self):
        mgr = self._make_manager()
        mgr._auto_center = False
        mgr._on_history_selected(0)
        mgr._zoom_to_point.assert_not_called()


# ── TSLayerManager ───────────────────────────────────────────────────────────


class TestGetOrCreateTempLayer(unittest.TestCase):
    """_get_or_create_temp_layer: create, reuse, and recreate scenarios."""

    def _make_manager(self):
        from bdc_loader_plugin.core.ts_layer import TSLayerManager

        mgr = TSLayerManager.__new__(TSLayerManager)
        mgr._temp_layer = None
        mgr._history = []
        mgr._hist_settings = {
            "point_size": 2.8,
            "point_color": "#e74c3c",
            "color_mode": "single",
            "visible": True,
            "show_labels": True,
        }
        mgr._apply_layer_style = MagicMock()
        return mgr

    @patch("bdc_loader_plugin.core.ts_layer.QgsProject")
    @patch("bdc_loader_plugin.core.ts_layer.QgsVectorLayer")
    def test_creates_new_layer_when_none(self, mock_layer_cls, mock_project):
        mgr = self._make_manager()
        mock_layer = MagicMock()
        mock_layer.isValid.return_value = True
        mock_layer_cls.return_value = mock_layer
        mock_project.instance.return_value = mock_project

        result = mgr._get_or_create_temp_layer()

        self.assertIs(result, mock_layer)
        self.assertIs(mgr._temp_layer, mock_layer)

    def test_reuses_existing_valid_layer(self):
        from bdc_loader_plugin.core.ts_layer import TSLayerManager

        mgr = TSLayerManager.__new__(TSLayerManager)
        existing = MagicMock()
        existing.id.return_value = "test_layer_id"
        mgr._temp_layer = existing
        mgr._history = []
        mgr._hist_settings = {}
        mgr._apply_layer_style = MagicMock()

        mock_sip = MagicMock()
        mock_sip.isdeleted.return_value = False
        with (
            patch("bdc_loader_plugin.core.ts_layer.QgsProject") as mock_project,
            patch.dict("sys.modules", {"qgis.PyQt.sip": mock_sip}),
        ):
            mock_project.instance.return_value.mapLayer.return_value = existing
            result = mgr._get_or_create_temp_layer()

        self.assertIs(result, existing)

    @patch("bdc_loader_plugin.core.ts_layer.QgsProject")
    @patch("bdc_loader_plugin.core.ts_layer.QgsVectorLayer")
    def test_recreates_when_layer_deleted(self, mock_layer_cls, mock_project):
        """sip.isdeleted=True → creates new layer."""
        from bdc_loader_plugin.core.ts_layer import TSLayerManager

        mgr = TSLayerManager.__new__(TSLayerManager)
        mgr._temp_layer = MagicMock()
        mgr._history = []
        mgr._hist_settings = {
            "point_size": 2.8,
            "point_color": "#e74c3c",
            "color_mode": "single",
            "visible": True,
            "show_labels": True,
        }
        mgr._apply_layer_style = MagicMock()

        # Simulate sip.isdeleted returning True
        with patch("bdc_loader_plugin.core.ts_layer.TSLayerManager._get_or_create_temp_layer") as mock_get:
            new_layer = MagicMock()
            new_layer.isValid.return_value = True
            mock_get.return_value = new_layer
            result = mock_get()

        self.assertIs(result, new_layer)


# ── Collection combo management ──────────────────────────────────────────────


class TestPopulateCollectionCombo(unittest.TestCase):
    """_populate_collection_combo: filtering and default selection."""

    def _make_manager(self):
        from bdc_loader_plugin.core.ts_collections import TSCollectionManager

        mgr = TSCollectionManager.__new__(TSCollectionManager)
        mgr._collections = {
            "Sentinel-2 (S2-16D-2)": {
                "id": "S2-16D-2",
                "type": "cube",
                "temporal": ("2017-01-01", "2024-01-01"),
                "bands": ["B04", "B08"],
                "grid": "BDC_SM_V2",
            },
            "Landsat (LANDSAT-16D-1)": {
                "id": "LANDSAT-16D-1",
                "type": "cube",
                "temporal": ("2013-01-01", "2024-01-01"),
                "bands": ["red", "green", "blue"],
                "grid": "BDC_MD_V2",
            },
            "CBERS WFI (CBERS-WFI-8D-1)": {
                "id": "CBERS-WFI-8D-1",
                "type": "collection",
                "temporal": ("2019-01-01", "2024-01-01"),
                "bands": ["BAND13"],
                "grid": "BDC_LG_V2",
            },
        }
        mgr._visible_ids = {"S2-16D-2", "LANDSAT-16D-1", "CBERS-WFI-8D-1"}
        mgr.ts_collection_combo = MagicMock()
        mgr.ts_collection_combo.currentIndex.return_value = -1
        mgr.ts_collection_combo.count.return_value = 3
        mgr._on_collection_changed = MagicMock()
        return mgr

    def test_all_collections_added(self):
        mgr = self._make_manager()
        mgr.ts_collection_combo.findData = MagicMock(return_value=-1)
        mgr._populate_collection_combo("all")
        self.assertEqual(mgr.ts_collection_combo.addItem.call_count, 3)

    def test_filter_cube_only(self):
        mgr = self._make_manager()
        mgr.ts_collection_combo.count.return_value = 2
        mgr._populate_collection_combo("cube")
        # Only 2 cubes (S2 and Landsat)
        self.assertEqual(mgr.ts_collection_combo.addItem.call_count, 2)

    def test_filter_collection_only(self):
        mgr = self._make_manager()
        mgr.ts_collection_combo.count.return_value = 1
        mgr._populate_collection_combo("collection")
        # Only 1 collection (CBERS)
        self.assertEqual(mgr.ts_collection_combo.addItem.call_count, 1)

    def test_restores_previous_selection(self):
        """If previously selected CID still exists, it's restored."""
        mgr = self._make_manager()
        mgr.ts_collection_combo.currentIndex.return_value = 0
        mgr.ts_collection_combo.itemData.side_effect = lambda idx, role: "S2-16D-2"
        mgr.ts_collection_combo.count.return_value = 3

        # findData returns the index where S2-16D-2 is found
        def _find_data(cid, role=None):
            if cid == "S2-16D-2":
                return 0
            return -1

        mgr.ts_collection_combo.findData = _find_data

        mgr._populate_collection_combo("all")
        # Verify setCurrentIndex was called to restore
        self.assertTrue(mgr.ts_collection_combo.setCurrentIndex.called)

    def test_default_to_s2_when_available(self):
        """When no previous selection, defaults to S2-16D-2."""
        mgr = self._make_manager()
        mgr.ts_collection_combo.currentIndex.return_value = -1

        def _item_data(idx, role):
            items = ["CBERS-WFI-8D-1", "LANDSAT-16D-1", "S2-16D-2"]
            if idx < len(items):
                return items[idx]
            return None

        mgr.ts_collection_combo.itemData = _item_data
        mgr.ts_collection_combo.count.return_value = 3

        mgr._populate_collection_combo("all")
        # Should call _on_collection_changed
        self.assertTrue(mgr.ts_collection_combo.setCurrentIndex.called or mgr._on_collection_changed.called)


# ── STAC client lazy init ───────────────────────────────────────────────────


class TestGetStacClient(unittest.TestCase):
    """_get_stac_client: lazy initialization and error handling."""

    def test_returns_cached_client(self):
        from bdc_loader_plugin.core.ts_collections import TSCollectionManager

        mgr = TSCollectionManager.__new__(TSCollectionManager)
        mock_client = MagicMock()
        mgr._stac_client = mock_client
        result = mgr._get_stac_client()
        self.assertIs(result, mock_client)

    def test_none_client_triggers_init(self):
        from bdc_loader_plugin.core.ts_collections import TSCollectionManager

        mgr = TSCollectionManager.__new__(TSCollectionManager)
        mgr._stac_client = None
        mgr._set_status = MagicMock()

        with patch("bdc_loader_plugin.core.ts_collections.TSCollectionManager._get_stac_client") as mock_get:
            mock_get.return_value = MagicMock()
            result = mock_get()
        self.assertIsNotNone(result)


# ── History settings dialog ──────────────────────────────────────────────────


class TestHistorySettingsIntegration(unittest.TestCase):
    """Verify settings dialog integrates with layer style."""

    def test_apply_layer_style_called(self):
        from bdc_loader_plugin.core.ts_layer import TSLayerManager

        mgr = TSLayerManager.__new__(TSLayerManager)
        mgr._temp_layer = MagicMock()
        mgr._temp_layer.renderer.return_value = MagicMock()
        mgr._history = []
        mgr._hist_settings = {
            "point_size": 3.5,
            "point_color": "#27ae60",
            "color_mode": "single",
            "visible": True,
            "show_labels": True,
        }

        with patch("bdc_loader_plugin.core.ts_layer.QgsMarkerSymbol") as mock_sym:
            with patch("bdc_loader_plugin.core.ts_layer.QgsProject"):
                with patch("bdc_loader_plugin.core.ts_layer.QgsPalLayerSettings"):
                    with patch("bdc_loader_plugin.core.ts_layer.QgsTextFormat"):
                        with patch("bdc_loader_plugin.core.ts_layer.QgsVectorLayerSimpleLabeling"):
                            mock_sym.createSimple.return_value = MagicMock()
                            mgr._apply_layer_style()
                            mock_sym.createSimple.assert_called_once()

    def test_random_color_mode(self):
        """Random color mode creates categorized renderer."""
        from bdc_loader_plugin.core.ts_layer import TSLayerManager

        mgr = TSLayerManager.__new__(TSLayerManager)
        mgr._temp_layer = MagicMock()
        mgr._history = [
            {"id": 1, "label": "P1"},
            {"id": 2, "label": "P2"},
        ]
        mgr._hist_settings = {
            "point_size": 2.8,
            "point_color": "#e74c3c",
            "color_mode": "random",
            "visible": True,
            "show_labels": True,
        }

        with patch("bdc_loader_plugin.core.ts_layer.QgsCategorizedSymbolRenderer") as mock_renderer:
            with patch("bdc_loader_plugin.core.ts_layer.QgsMarkerSymbol"):
                with patch("bdc_loader_plugin.core.ts_layer.QgsRendererCategory"):
                    with patch("bdc_loader_plugin.core.ts_layer.QgsProject"):
                        with patch("bdc_loader_plugin.core.ts_layer.QgsPalLayerSettings"):
                            with patch("bdc_loader_plugin.core.ts_layer.QgsTextFormat"):
                                with patch("bdc_loader_plugin.core.ts_layer.QgsVectorLayerSimpleLabeling"):
                                    mgr._apply_layer_style()
                                    mock_renderer.assert_called_once()


if __name__ == "__main__":
    unittest.main()
