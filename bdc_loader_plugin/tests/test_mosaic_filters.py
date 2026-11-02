#!/usr/bin/env python3
"""Catalog type-filter contracts for mosaic collections."""

import unittest
from unittest.mock import MagicMock, patch

from bdc_loader_plugin.tests.catalog_patch import patch_catalog


class _Combo:
    def __init__(self):
        self.items = []
        self.data = []
        self.current = -1

    def clear(self):
        self.items.clear()
        self.data.clear()
        self.current = -1

    def addItem(self, text):
        self.items.append(text)
        self.data.append({})
        if self.current < 0:
            self.current = 0

    def count(self):
        return len(self.items)

    def setItemData(self, index, value, role):
        self.data[index][role] = value

    def itemData(self, index, role):
        if index < 0 or index >= len(self.data):
            return None
        return self.data[index].get(role)

    def currentIndex(self):
        return self.current

    def setCurrentIndex(self, index):
        self.current = index

    def currentText(self):
        return self.items[self.current] if self.current >= 0 else ""

    def blockSignals(self, _blocked):
        pass


class TestMosaicCollectionFilters(unittest.TestCase):
    def setUp(self):
        self.collections = {
            "Cube": {"id": "cube-1", "type": "cube"},
            "Scenes": {"id": "collection-1", "type": "collection"},
            "Mosaic": {"id": "mosaic-1", "type": "mosaic"},
        }

    def test_main_catalog_filters_mosaics(self):
        from bdc_loader_plugin.core.catalog import CatalogManager

        manager = CatalogManager.__new__(CatalogManager)
        manager.collection_combo = _Combo()
        manager._hidden_collections = set()

        with patch_catalog(*(self.collections, {}, {})):
            manager._populate_collections("mosaic")

        self.assertEqual(manager.collection_combo.items, ["Mosaic"])

    def test_main_catalog_orders_collections_alphabetically(self):
        from bdc_loader_plugin.core.catalog import CatalogManager

        collections = {
            "zulu": {"id": "zulu", "type": "collection"},
            "Alpha": {"id": "alpha", "type": "cube"},
            "beta": {"id": "beta", "type": "mosaic"},
        }
        manager = CatalogManager.__new__(CatalogManager)
        manager.collection_combo = _Combo()
        manager._hidden_collections = set()

        with patch_catalog(*(collections, {}, {})):
            manager._populate_collections("all")

        self.assertEqual(
            manager.collection_combo.items,
            ["Alpha", "beta", "zulu"],
        )

    def test_main_catalog_mosaic_button_selects_mosaic_filter(self):
        from bdc_loader_plugin.core.catalog import CatalogManager

        manager = CatalogManager.__new__(CatalogManager)
        manager.collection_combo = _Combo()
        manager.filter_all_btn = MagicMock()
        manager.filter_cube_btn = MagicMock()
        manager.filter_collection_btn = MagicMock()
        manager.filter_mosaic_btn = MagicMock()
        manager.filter_all_btn.isChecked.return_value = False
        manager.filter_cube_btn.isChecked.return_value = False
        manager.filter_collection_btn.isChecked.return_value = False
        manager.filter_mosaic_btn.isChecked.return_value = True
        manager._populate_collections = MagicMock()

        manager._filter_collections()

        manager._populate_collections.assert_called_once_with("mosaic")

    def test_time_series_combo_has_no_mosaic_filter(self):
        """Mosaics have no regular temporal axis, so the WTSS panel never shows
        them, even when 'all' is selected — there is no 'mosaic' filter type."""
        from bdc_loader_plugin.core.ts_collections import TSCollectionManager

        manager = TSCollectionManager.__new__(TSCollectionManager)
        manager._collections = self.collections
        manager._visible_ids = {"cube-1", "collection-1", "mosaic-1"}
        manager.ts_collection_combo = _Combo()
        manager._on_collection_changed = MagicMock()

        manager._populate_collection_combo("all")

        self.assertEqual(manager.ts_collection_combo.items, ["Cube", "Scenes"])

    def test_time_series_combo_orders_collections_alphabetically(self):
        from bdc_loader_plugin.core.ts_collections import TSCollectionManager

        collections = {
            "zulu": {"id": "zulu", "type": "collection"},
            "Alpha": {"id": "alpha", "type": "cube"},
            "beta": {"id": "beta", "type": "collection"},
        }
        manager = TSCollectionManager.__new__(TSCollectionManager)
        manager._collections = collections
        manager._visible_ids = {"zulu", "alpha", "beta"}
        manager.ts_collection_combo = _Combo()
        manager._on_collection_changed = MagicMock()

        manager._populate_collection_combo("all")

        self.assertEqual(
            manager.ts_collection_combo.items,
            ["Alpha", "beta", "zulu"],
        )

    def test_time_series_orders_band_checkboxes_alphabetically(self):
        from bdc_loader_plugin.core.ts_collections import TSCollectionManager

        class _CheckBox:
            def __init__(self, text):
                self.text = text
                self.properties = {}

            def setChecked(self, _checked):
                pass

            def setProperty(self, name, value):
                self.properties[name] = value

            def setStyleSheet(self, _style):
                pass

        manager = TSCollectionManager.__new__(TSCollectionManager)
        manager._band_checkboxes = []
        manager._bands_grid_layout = MagicMock()
        manager.ts_collection_combo = MagicMock()
        manager.ts_collection_combo.itemData.return_value = "test-cube"
        manager._collections = {
            "Test": {
                "id": "test-cube",
                "type": "cube",
                "bands": ["zeta", "Alpha", "beta"],
            }
        }
        manager._band_info = {}
        manager.ts_collection_info = MagicMock()

        with (
            patch("qgis.PyQt.QtWidgets.QCheckBox", _CheckBox),
            patch("bdc_loader_plugin.core.ts_collections.apply_click_cursors"),
        ):
            manager._on_collection_changed(0)

        self.assertEqual(
            [checkbox.properties["band_name"] for checkbox in manager._band_checkboxes],
            ["Alpha", "beta", "zeta"],
        )

    def test_time_series_load_excludes_mosaics(self):
        """_load_collections_from_plugin drops bdc:type == mosaic before it ever
        reaches the TS collections dict, regardless of the active type filter."""
        from bdc_loader_plugin.core.ts_collections import TSCollectionManager

        manager = TSCollectionManager.__new__(TSCollectionManager)
        manager._collections = {}
        manager._band_info = {}
        manager._visible_ids = set()
        manager._stac_client = None
        manager._set_status = MagicMock()
        manager._populate_collection_combo = MagicMock()
        manager.ts_collection_combo = MagicMock()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "collections": [
                {
                    "id": "cube-1",
                    "title": "Cube",
                    "bdc:type": "cube",
                    "item_assets": {"B04": {"type": "image/tiff; application=geotiff; profile=cloud-optimized"}},
                    "extent": {"temporal": {"interval": [["2017-01-01", "2024-01-01"]]}},
                },
                {
                    "id": "mosaic-1",
                    "title": "Mosaic",
                    "bdc:type": "mosaic",
                    "item_assets": {"visual": {"type": "image/tiff; application=geotiff; profile=cloud-optimized"}},
                    "extent": {"temporal": {"interval": [["2020-01-01", "2020-12-31"]]}},
                },
            ]
        }

        with (
            patch("bdc_loader_plugin.stac.client.requests.get", return_value=mock_resp),
            patch("bdc_loader_plugin.core.ts_collections.QCoreApplication.processEvents"),
        ):
            manager._load_collections_from_plugin()

        loaded_ids = {config["id"] for config in manager._collections.values()}
        self.assertEqual(loaded_ids, {"cube-1"})
