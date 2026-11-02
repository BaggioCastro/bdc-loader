"""Changing the collection drops results searched in another collection."""

from unittest.mock import MagicMock

from bdc_loader_plugin.tests.catalog_patch import patch_catalog


def _owner(results):
    owner = MagicMock()
    owner.result_widgets = results
    owner.collection_combo.itemData.return_value = "Sentinel-2 Cube 16D (S2-16D-2)"
    return owner


def test_results_are_cleared_when_the_collection_changes():
    from bdc_loader_plugin.core import catalog

    owner = _owner([object()])
    with patch_catalog({}):
        try:
            catalog.CatalogManager.on_collection_changed(owner, "Sentinel-2 Cube 16D (S2-16D-2)")
        except Exception:
            pass  # later steps need real widgets; only the clearing is checked here
    owner.clear_results.assert_called_once_with()


def test_nothing_to_clear_without_results():
    from bdc_loader_plugin.core import catalog

    owner = _owner([])
    with patch_catalog({}):
        try:
            catalog.CatalogManager.on_collection_changed(owner, "Sentinel-2 Cube 16D (S2-16D-2)")
        except Exception:
            pass
    owner.clear_results.assert_not_called()


class _Combo:
    def __init__(self, texts=(), current=0):
        self.items = [[t, {}] for t in texts]
        self.current = current

    def blockSignals(self, _flag):
        return False

    def clear(self):
        self.items = []
        self.current = -1

    def addItem(self, text):
        self.items.append([text, {}])
        if self.current < 0:
            self.current = 0

    def count(self):
        return len(self.items)

    def setItemData(self, row, value, role):
        self.items[row][1][role] = value

    def findText(self, text):
        return next((i for i, (t, _d) in enumerate(self.items) if t == text), -1)

    def setCurrentIndex(self, index):
        self.current = index

    def currentText(self):
        return self.items[self.current][0] if 0 <= self.current < len(self.items) else ""


def _preset_owner(selected_count):
    from types import SimpleNamespace

    owner = SimpleNamespace(
        preset_combo=_Combo(["-- Select --", "False Color (B08,B04,B03)"], current=1),
        selected_bands=SimpleNamespace(count=lambda: selected_count),
        apply_preset=MagicMock(),
        _update_composition_buttons=MagicMock(),
        _collection_presets=lambda name, bands: ({"False Color (B08,B04,B03)": ["BAND8", "BAND7", "BAND6"]}, {}),
    )
    return owner


def test_preset_kept_across_collections_is_applied_to_the_new_bands():
    from bdc_loader_plugin.core import catalog

    owner = _preset_owner(selected_count=0)
    catalog.CatalogManager._update_preset_list(owner, "CB4-MUX-L4-SR-1", ["BAND8"], collection_changed=True)
    assert owner.preset_combo.currentText() == "False Color (B08,B04,B03)"
    owner.apply_preset.assert_called_once_with("False Color (B08,B04,B03)")


def test_availability_refresh_does_not_reapply_a_preset():
    from bdc_loader_plugin.core import catalog

    owner = _preset_owner(selected_count=0)
    catalog.CatalogManager._update_preset_list(owner, "CB4-MUX-L4-SR-1", ["BAND8"])
    owner.apply_preset.assert_not_called()


def test_html_error_page_is_reduced_to_its_title():
    from bdc_loader_plugin.core.search import _readable_error

    page = "<html>\r\n<head><title>502 Bad Gateway</title></head>\r\n<body>nginx</body></html>"
    message = _readable_error(RuntimeError(page))
    assert "502 Bad Gateway" in message
    assert "<" not in message
    assert _readable_error(ValueError("plain")) == "plain"


def test_cleared_cards_leave_the_layout_at_once():
    from bdc_loader_plugin.core.filters import ResultFilter

    cards = [MagicMock(), MagicMock()]
    owner = MagicMock()
    owner.result_widgets = list(cards)
    ResultFilter.clear_results(owner)
    for card in cards:
        card.hide.assert_called_once_with()
        card.setParent.assert_called_once_with(None)
        card.deleteLater.assert_called_once_with()
    assert owner.result_widgets == []


def test_range_bar_drops_old_year_labels():
    from bdc_loader_plugin.widgets.range_slider import RangeBar

    bar = RangeBar.__new__(RangeBar)
    bar.update = lambda: None
    bar._year_positions = [(0, 2017), (365, 2018)]
    RangeBar.set_range(bar, 0, 88, [])
    assert bar._year_positions == []
    RangeBar.set_range(bar, 0, 88)  # no labels given: keep the current ones
    assert bar._year_positions == []


def test_search_ignores_a_second_click_and_holds_the_collection():
    from bdc_loader_plugin.core.search import SearchEngine

    owner = MagicMock()
    owner._search_in_progress = False
    seen = {}

    def _run():
        seen["button"] = owner.search_btn.setEnabled.call_args_list[-1]
        seen["combo"] = owner.collection_combo.setEnabled.call_args_list[-1]
        SearchEngine.search_stac(owner)  # re-entered while running: ignored

    owner._search_stac_unguarded.side_effect = _run
    SearchEngine.search_stac(owner)
    owner._search_stac_unguarded.assert_called_once_with()
    assert seen["button"].args == (False,) and seen["combo"].args == (False,)
    assert owner.search_btn.setEnabled.call_args.args == (True,)
    assert owner.collection_combo.setEnabled.call_args.args == (True,)
    assert owner._search_in_progress is False


def test_tile_query_for_mgrs_and_path_row_ids():
    from bdc_loader_plugin.core.search import _tile_query

    assert _tile_query(["22KHA", "23LLD"]) == {"bdc:tiles": {"in": ["22KHA", "23LLD"]}}
    assert _tile_query(["221/71"]) == {"path": {"eq": "221"}, "row": {"eq": "071"}}
    assert _tile_query(["221/71", "221_72", "221/71"]) == {"path": {"in": ["221"]}, "row": {"in": ["071", "072"]}}


def _presets(common_names):
    from bdc_loader_plugin.core.catalog import dynamic_presets

    return dynamic_presets(list(common_names), {band: {"common_name": cn} for band, cn in common_names.items()})


def test_sentinel2_bands_form_every_reflectance_composite_in_catalogue_order():
    presets = _presets(
        {
            "B01": "coastal", "B02": "blue", "B03": "green", "B04": "red", "B05": "rededge", "B06": "rededge",
            "B07": "rededge", "B08": "nir", "B11": "swir16", "B12": "swir22",
        }
    )  # fmt: skip

    assert list(presets) == [
        "True Color (B04,B03,B02)",
        "False Color (B08,B04,B03)",
        "SWIR (B12,B08,B04)",
        "Agriculture (B11,B08,B02)",
        "Geology (B12,B11,B02)",
        "Bathimetric (B04,B03,B01)",
        "Vegetation Analysis (B08,B06,B04)",
        "Healthy Vegetation (B08,B05,B04)",
        "Vegetation/Built-up (B08,B11,B04)",
        "Urban/Moisture (B08,B11,B12)",
        "Land/Water (B11,B08,B03)",
    ]
    assert presets["Vegetation Analysis (B08,B06,B04)"] == ["B08", "B06", "B04"]
    assert presets["Healthy Vegetation (B08,B05,B04)"] == ["B08", "B05", "B04"]


def test_landsat_names_fill_the_nir_and_swir_roles():
    presets = _presets(
        {"blue": "BLUE", "green": "green", "red": "red", "nir08": "nir08", "swir1": "swir1", "swir2": "swir2"}
    )

    assert presets["SWIR (B12,B08,B04)"] == ["swir2", "nir08", "red"]
    assert presets["Agriculture (B11,B08,B02)"] == ["swir1", "nir08", "blue"]
    assert "Healthy Vegetation (B08,B05,B04)" not in presets


def test_sensor_without_blue_keeps_only_the_composites_it_can_form():
    presets = _presets({"BAND13": "green", "BAND14": "red", "BAND16": "nir", "NDVI": "ndvi", "EVI": "evi"})

    assert list(presets) == ["False Color (B08,B04,B03)", "NDVI+NIR+Red", "EVI+NIR+Red", "NDVI+EVI+NIR"]
    assert presets["NDVI+EVI+NIR"] == ["NDVI", "EVI", "BAND16"]
