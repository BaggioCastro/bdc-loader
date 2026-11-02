"""User compositions, stale time series point layers and chart Y bounds."""

from unittest.mock import MagicMock, patch

import pytest

from bdc_loader_plugin.tests.catalog_patch import patch_catalog


@pytest.fixture(autouse=True)
def _clean_settings():
    from qgis.core import QgsSettings

    QgsSettings._reset()
    yield
    QgsSettings._reset()


class TestCustomCompositions:
    def test_save_list_and_delete_per_collection(self):
        from bdc_loader_plugin.config import ConfigManager

        ConfigManager.save_custom_composition("S2-16D-2", "Vegetation", ["B08", "B11", "B04"])
        ConfigManager.save_custom_composition("LANDSAT-16D-1", "Vegetation", ["nir08", "swir16", "red"])

        assert ConfigManager.get_custom_compositions("S2-16D-2") == {"Vegetation": ["B08", "B11", "B04"]}
        assert ConfigManager.delete_custom_composition("S2-16D-2", "Vegetation") is True
        assert ConfigManager.get_custom_compositions("S2-16D-2") == {}
        assert ConfigManager.get_custom_compositions("LANDSAT-16D-1") == {"Vegetation": ["nir08", "swir16", "red"]}

    def test_deleting_unknown_name_reports_false(self):
        from bdc_loader_plugin.config import ConfigManager

        assert ConfigManager.delete_custom_composition("S2-16D-2", "missing") is False

    def test_unreadable_setting_is_ignored(self):
        from qgis.core import QgsSettings

        from bdc_loader_plugin.config import ConfigManager

        QgsSettings().setValue(ConfigManager._COMPOSITIONS_KEY, "{not json")

        assert ConfigManager.get_custom_compositions("S2-16D-2") == {}


class TestStaleTimeSeriesLayers:
    @staticmethod
    def _layer(layer_id, name, provider, tagged):
        layer = MagicMock()
        layer.id.return_value = layer_id
        layer.name.return_value = name
        layer.providerType.return_value = provider
        layer.customProperty.side_effect = lambda key, default=None: tagged
        return layer

    def test_point_layers_from_earlier_instances_are_removed(self):
        import bdc_loader_plugin.core.ts_layer as module

        layers = {
            "a": self._layer("a", "BDC TS Points", "memory", False),
            "b": self._layer("b", "renamed by user", "memory", True),
            "c": self._layer("c", "BDC TS Points", "ogr", False),
            "d": self._layer("d", "S2 mosaic", "gdal", False),
        }
        project = MagicMock()
        project.mapLayers.return_value = layers
        with patch.object(module.QgsProject, "instance", return_value=project):
            module.TSLayerManager._remove_stale_temp_layers()

        project.removeMapLayers.assert_called_once_with(["a", "b"])


class TestChartViewBounds:
    def test_declared_ranges_bound_the_view(self):
        from bdc_loader_plugin.chart.plot import _clamp_values, _view_bounds

        entry = {"valid_range": {"red": (0.0, 10000.0), "NDVI": (-10000.0, 10000.0)}}
        bounds = _view_bounds(entry, ["red"])

        assert bounds == (0.0, 10000.0)
        assert _clamp_values([287.0, 16022.0, 1152.0], bounds) == [287.0, 1152.0]
        assert _view_bounds(entry, ["red", "NDVI"]) == (-10000.0, 10000.0)

    def test_default_bounds_without_declared_ranges(self):
        from bdc_loader_plugin.chart.plot import _view_bounds

        assert _view_bounds({}, ["B04"]) == (-10000.0, 10000.0)

    def test_all_values_outside_bounds_are_kept_for_the_view(self):
        from bdc_loader_plugin.chart.plot import _clamp_values

        assert _clamp_values([16022.0, 15000.0], (0.0, 10000.0)) == [16022.0, 15000.0]


class TestCompositionValidation:
    def test_valid_rgb_and_single_band(self):
        from bdc_loader_plugin.widgets.dialogs import composition_problem

        assert composition_problem("Vegetation", ["B08", "B11", "B04"], ["True Color"]) == ""
        assert composition_problem("NIR", ["B08"], ["True Color"]) == ""

    @pytest.mark.parametrize(
        ("name", "bands", "fragment"),
        [
            ("  ", ["B08", "B11", "B04"], "Enter a name"),
            ("-- Select --", ["B08", "B11", "B04"], '"--"'),
            ("true color", ["B08", "B11", "B04"], "built-in"),
            ("Mixed", ["B08", "B08", "B04"], "three different bands"),
            ("Two", ["B08", "B04"], "every channel"),
            ("Empty", ["B08", None, "B04"], "every channel"),
        ],
    )
    def test_problems_are_reported(self, name, bands, fragment):
        from bdc_loader_plugin.widgets.dialogs import composition_problem

        assert fragment in composition_problem(name, bands, ["True Color"])

    def test_saved_name_match_ignores_case_and_spaces(self):
        from bdc_loader_plugin.widgets.dialogs import saved_name_match

        saved = {"Vegetation": ["B08", "B11", "B04"]}
        assert saved_name_match(" vegetation ", saved) == "Vegetation"
        assert saved_name_match("Urban", saved) is None


class TestSaveCompositionFlow:
    @staticmethod
    def _manager(selected=("B04", "B03", "B02")):
        from bdc_loader_plugin.core.catalog import CatalogManager

        manager = CatalogManager.__new__(CatalogManager)
        manager._current_collection_name = MagicMock(return_value="S2-16D-2")
        manager._enabled_bands = MagicMock(return_value=[("B04", "B04 (red)"), ("B08", "B08 (nir)")])
        manager._selected_band_names = MagicMock(return_value=list(selected))
        manager._collection_presets = MagicMock(return_value=({"True Color": ["B04", "B03", "B02"]}, {}))
        manager._sync_bands_with_selected_items = MagicMock()
        manager._set_status = MagicMock()
        manager.apply_preset = MagicMock()
        manager.preset_combo = MagicMock()
        manager.preset_combo.findText.return_value = 3
        return manager

    @staticmethod
    def _dialog(accepted, name="Vegetation", bands=("B08", "B11", "B04"), replaced=None):
        from bdc_loader_plugin.core.catalog import QDialog

        dialog = MagicMock()
        dialog.exec.return_value = QDialog.DialogCode.Accepted if accepted else QDialog.DialogCode.Rejected
        dialog.name.return_value = name
        dialog.bands.return_value = list(bands)
        dialog.replaced_name.return_value = replaced
        return dialog

    def _run(self, manager, dialog):
        globals_ = ({"S2-16D-2": {"id": "S2-16D-2", "bands": ["B04", "B08"]}}, {}, {})
        with (
            patch_catalog(*globals_),
            patch("bdc_loader_plugin.core.catalog.CompositionDialog", return_value=dialog) as factory,
        ):
            manager._save_composition()
        return factory

    def test_dialog_gets_available_bands_and_saves_choice(self):
        from bdc_loader_plugin.config import ConfigManager

        manager = self._manager()
        factory = self._run(manager, self._dialog(True))

        args, kwargs = factory.call_args
        assert args[0] == [("B04", "B04 (red)"), ("B08", "B08 (nir)")]
        assert args[1] == {"True Color": ["B04", "B03", "B02"]}
        assert kwargs["initial"] == ["B04", "B03", "B02"]
        assert ConfigManager.get_custom_compositions("S2-16D-2") == {"Vegetation": ["B08", "B11", "B04"]}
        manager.preset_combo.setCurrentIndex.assert_called_once_with(3)
        manager.apply_preset.assert_called_once_with("Vegetation")

    def test_cancel_saves_nothing(self):
        from bdc_loader_plugin.config import ConfigManager

        manager = self._manager()
        self._run(manager, self._dialog(False))

        assert ConfigManager.get_custom_compositions("S2-16D-2") == {}
        manager.apply_preset.assert_not_called()

    def test_replacing_with_other_case_keeps_one_entry(self):
        from bdc_loader_plugin.config import ConfigManager

        ConfigManager.save_custom_composition("S2-16D-2", "Vegetation", ["B04"])
        manager = self._manager()
        self._run(manager, self._dialog(True, name="VEGETATION", bands=("B08",), replaced="Vegetation"))

        assert ConfigManager.get_custom_compositions("S2-16D-2") == {"VEGETATION": ["B08"]}
