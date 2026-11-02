"""Results against the search parameters, the result filters, and searches that find nothing."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from bdc_loader_plugin import i18n
from bdc_loader_plugin.core.filters import ResultFilter
from bdc_loader_plugin.core.search import SearchEngine, _no_results_message
from bdc_loader_plugin.tests.catalog_patch import patch_catalog

PARAMS = {
    "collection": "S2-16D-2",
    "bands": ("B04", "B03", "B02"),
    "period": ("2022-08-01", "2022-09-30"),
    "area": ((-45.3, -13.9, -45.1, -13.7), True, (), None),
    "limit": 50,
}


def _owner(current=None, cards=2):
    owner = SimpleNamespace(
        _PARAM_LABELS=SearchEngine._PARAM_LABELS,
        _search_in_progress=False,
        _searched_params=dict(PARAMS),
        _results_fresh=True,
        result_widgets=[MagicMock() for _ in range(cards)],
        load_btn=MagicMock(),
        download_selected_btn=MagicMock(),
        search_btn=MagicMock(),
        _set_status=MagicMock(),
    )
    owner.current = dict(current or PARAMS)
    owner._search_params = lambda: owner.current
    for name in ("_changed_search_params", "_check_search_params", "_show_results_fresh", "_results_match_panel"):
        setattr(owner, name, getattr(SearchEngine, name).__get__(owner))
    return owner


def test_changing_the_bands_locks_load_and_download_and_lights_search():
    from bdc_loader_plugin.ui.main_styles import _SEARCH_BTN_STALE_STYLE

    owner = _owner({**PARAMS, "bands": ("B08", "B04", "B03")})
    owner._check_search_params()

    owner.load_btn.setEnabled.assert_called_with(False)
    owner.download_selected_btn.setEnabled.assert_called_with(False)
    for card in owner.result_widgets:
        card.download_btn.setEnabled.assert_called_with(False)
    owner.search_btn.setStyleSheet.assert_called_with(_SEARCH_BTN_STALE_STYLE)
    owner._set_status.assert_called_with("Search parameters changed (bands). Click Search STAC again.", "warning")
    assert owner._results_match_panel() is False


def test_every_changed_parameter_is_named():
    owner = _owner({**PARAMS, "period": ("2022-07-01", "2022-09-30"), "area": (None, False, ("031020",), None)})
    assert owner._changed_search_params() == ["period", "area"]


def test_going_back_to_the_searched_values_unlocks_the_results():
    from bdc_loader_plugin.ui.main_styles import _SEARCH_BTN_STYLE

    owner = _owner({**PARAMS, "limit": 10})
    owner._check_search_params()
    owner.current = dict(PARAMS)
    owner._check_search_params()

    owner.load_btn.setEnabled.assert_called_with(True)
    owner.search_btn.setStyleSheet.assert_called_with(_SEARCH_BTN_STYLE)
    owner._set_status.assert_called_with("The parameters are back to those of the search.", "info")
    assert owner._results_match_panel() is True


def test_without_results_nothing_is_stale():
    owner = _owner({**PARAMS, "bands": ("B08",)}, cards=0)
    owner._check_search_params()
    owner._set_status.assert_not_called()
    owner.load_btn.setEnabled.assert_called_with(False)


def test_search_params_read_the_panel():
    owner = SimpleNamespace(
        _current_collection_name=lambda: "S2",
        _selected_band_names=lambda: ["B04", "B03", "B02"],
        range_slider=MagicMock(),
        get_bbox_from_extent=lambda: [-45.12345678, -13.9, -45.1, -13.7],
        is_extent_crop_mode=lambda: True,
        get_tiles_list=lambda: [],
        _shape_search_signature=lambda: None,
        limit_spin=MagicMock(),
    )
    owner.range_slider.get_start_date.return_value.toString.return_value = "2022-08-01"
    owner.range_slider.get_end_date.return_value.toString.return_value = "2022-09-30"
    owner.limit_spin.value.return_value = 50
    with patch_catalog({"S2": {"id": "S2-16D-2"}}):
        params = SearchEngine._search_params(owner)
    assert params == {
        "collection": "S2-16D-2",
        "bands": ("B04", "B03", "B02"),
        "period": ("2022-08-01", "2022-09-30"),
        "area": ((-45.123457, -13.9, -45.1, -13.7), True, (), None),
        "limit": 50,
    }


def test_load_and_download_stop_when_the_results_no_longer_match():
    from bdc_loader_plugin.core.download import DownloadManager
    from bdc_loader_plugin.core.vrt_generator import VrtGenerator

    owner = MagicMock()
    owner._results_match_panel.return_value = False
    VrtGenerator.generate_and_load(owner)
    owner.get_selected_items.assert_not_called()
    DownloadManager._download_widgets_unguarded(owner, [MagicMock()])
    owner._selected_band_list.assert_not_called()


# ── Result filters ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("visible", "text", "kind"),
    [
        (3, "3 images found.", "info"),
        (1, "1 of 3 images shown by the filters.", "info"),
        (0, "The filters hide all 3 images found. Click Reset to show them.", "warning"),
    ],
)
def test_result_count_says_what_the_filters_hide(visible, text, kind):
    owner = SimpleNamespace(result_widgets=[1, 2, 3], _set_status=MagicMock())
    ResultFilter._show_result_count(owner, visible)
    owner._set_status.assert_called_once_with(text, kind)


def test_cloud_and_date_filters_keep_results_without_a_value():
    from datetime import datetime

    from qgis.PyQt.QtCore import QDate

    def card(cloud, when):
        widget = MagicMock()
        widget.item = SimpleNamespace(properties={"eo:cloud_cover": cloud}, datetime=when)
        widget._filtered_out = False
        return widget

    cards = [card("n/a", None), card(80, datetime(2022, 8, 5)), card(5, datetime(1, 1, 1)), card(None, None)]
    owner = MagicMock()
    owner.result_widgets = cards
    owner._tile_filter_dict = {}
    owner._show_downloaded_only = False
    owner.filter_cloud_spin.value.return_value = 20
    owner.filter_range_slider.range_bar.is_dragging = False
    owner.filter_range_slider.get_start_date.return_value = QDate(2022, 8, 1)
    owner.filter_range_slider.get_end_date.return_value = QDate(2022, 9, 30)

    ResultFilter._apply_result_filters(owner)

    # Only the card that changes is touched.
    assert [c.setVisible.call_args[0][0] if c.setVisible.called else None for c in cards] == [None, False, None, None]
    owner._show_result_count.assert_called_once_with(3)
    owner._sync_bands_with_selected_items.assert_called_once_with()


def test_filters_that_change_no_card_leave_the_bands_alone():
    owner = MagicMock()
    card = MagicMock()
    card.item = SimpleNamespace(properties={"eo:cloud_cover": 5}, datetime=None)
    card._filtered_out = False
    owner.result_widgets = [card]
    owner._tile_filter_dict = {}
    owner._show_downloaded_only = False
    owner.filter_cloud_spin.value.return_value = 50
    owner.filter_range_slider.range_bar.is_dragging = False

    ResultFilter._apply_result_filters(owner)
    card.setVisible.assert_not_called()
    owner._sync_bands_with_selected_items.assert_not_called()
    ResultFilter._apply_result_filters(owner, refresh=True)
    owner._sync_bands_with_selected_items.assert_called_once_with()


def test_the_cloud_slider_filters_live_but_at_most_every_40_ms():
    from bdc_loader_plugin.core import filters

    owner = MagicMock()
    owner._last_filter_apply = 0.0
    timer = MagicMock()
    timer.isActive.return_value = False
    owner._filter_debounce_timer = timer

    with patch.object(filters.time, "monotonic", return_value=100.0):
        ResultFilter._schedule_filter_update(owner)
    owner._apply_result_filters.assert_called_once_with()

    owner._last_filter_apply = 100.0
    with patch.object(filters.time, "monotonic", return_value=100.01):
        ResultFilter._schedule_filter_update(owner)
    timer.start.assert_called_once_with(30)
    assert owner._apply_result_filters.call_count == 1


def test_a_typed_cloud_value_waits_for_the_typing_to_stop():
    owner = MagicMock()
    owner._filter_debounce_timer = MagicMock()
    ResultFilter._on_cloud_spin_changed(owner, 2)
    owner._schedule_filter_update.assert_called_once_with(wait_ms=400)


# ── Searches that find nothing ──────────────────────────────────────────────


CONFIG = {"id": "S2-16D-2", "temporal": ("2017-01-01", "2027-04-14"), "grid": "BDC_SM_V2"}


@pytest.mark.parametrize(
    ("args", "english", "portuguese"),
    [
        (
            ("2010-01-01", "2010-12-31", [], [1, 2, 3, 4], False, 0),
            "No images found. S2-16D-2 has images from 2017-01-01 to 2027-04-14; choose a period inside it.",
            "Nenhuma imagem encontrada. S2-16D-2 tem imagens de 2017-01-01 a 2027-04-14; escolha um período dentro dele.",
        ),
        (
            ("2022-08-01", "2022-09-30", [], [1, 2, 3, 4], True, 7),
            "No images found. 7 scenes cover the box around the vector features, but none crosses the checked "
            "features.",
            "Nenhuma imagem encontrada. 7 cenas cobrem o retângulo em volta das feições, mas nenhuma cruza as feições "
            "marcadas.",
        ),
        (
            ("2022-08-01", "2022-09-30", ["999999"], None, False, 0),
            "No images found in tiles 999999 from 2022-08-01 to 2022-09-30. Check that they belong to the BDC_SM_V2 "
            "grid of S2-16D-2.",
            "Nenhuma imagem encontrada nos tiles 999999 de 2022-08-01 a 2022-09-30. Confira se eles são da grade "
            "BDC_SM_V2 de S2-16D-2.",
        ),
        (
            ("2022-08-01", "2022-09-30", [], [1, 2, 3, 4], False, 0),
            "No images found over this area from 2022-08-01 to 2022-09-30. It may be outside the coverage of S2-16D-2; "
            "try a longer period or another area.",
            "Nenhuma imagem encontrada nesta área de 2022-08-01 a 2022-09-30. Ela pode estar fora da cobertura de "
            "S2-16D-2; tente um período maior ou outra área.",
        ),
    ],
)
def test_an_empty_search_says_why_in_both_languages(args, english, portuguese):
    text = _no_results_message(CONFIG, *args)
    assert text == english
    assert i18n.tr(text, "pt") == portuguese


def test_the_changed_parameters_are_named_in_portuguese():
    text = "Search parameters changed (bands, period, area). Click Search STAC again."
    assert (
        i18n.tr(text, "pt") == "Os parâmetros da busca mudaram (bandas, período, área). Clique em Buscar STAC de novo."
    )


def _validation_owner(bbox=None, shape_layer=None, fids=(), merged=False):
    owner = MagicMock()
    owner._current_collection_name.return_value = "S2"
    owner.get_tiles_list.return_value = []
    owner.get_bbox_from_extent.return_value = bbox
    owner._get_shape_bbox.return_value = None
    owner._shape_vector_layer = shape_layer
    owner.shape_merge_check.isChecked.return_value = merged
    owner._get_selected_shape_fids.return_value = list(fids)
    owner.tiles_input.text.return_value = ""
    owner.selected_bands.count.return_value = 3
    owner.range_slider.get_start_date.return_value = 1
    owner.range_slider.get_end_date.return_value = 2
    return owner


@pytest.mark.parametrize(
    ("kwargs", "problem"),
    [
        ({"bbox": [-45.0, -13.0, -45.0, -12.0]}, "The extent has no area."),
        ({"bbox": [-200.0, -13.0, -45.0, -12.0]}, "The extent is outside longitude -180 to 180"),
        ({"shape_layer": object()}, "No feature of the vector file is checked."),
    ],
)
def test_validation_names_the_area_problem(kwargs, problem):
    with patch_catalog({"S2": {"id": "S2-16D-2"}}), patch.object(i18n, "language", return_value="en"):
        ok, message = SearchEngine._validate_search_params(_validation_owner(**kwargs))
    assert not ok
    assert problem in message


def test_a_result_with_a_cloud_value_that_is_not_a_number_builds_its_card():
    from bdc_loader_plugin.stac.parsers import cloud_cover

    assert cloud_cover(SimpleNamespace(properties={"eo:cloud_cover": "n/a"})) is None
    assert cloud_cover(SimpleNamespace(properties={"eo:cloud_cover": "12.5"})) == 12.5
    assert cloud_cover(SimpleNamespace(properties=None)) is None


@pytest.mark.parametrize(
    ("filters", "problem"),
    [
        ({"cloud_cover_max": "abc"}, "cloud_cover_max"),
        ({"cloud_cover_max": 150}, "cloud_cover_max"),
        ({"limit": 0}, "'limit'"),
        ({"limit": "10"}, "'limit'"),
        ([], "'filters'"),
    ],
)
def test_query_filters_out_of_range_are_refused(filters, problem):
    from bdc_loader_plugin.core.query_spec import validate_query_spec

    ok, message = validate_query_spec({"collection": "S2-16D-2", "filters": filters})
    assert not ok and problem in message


def test_query_filters_in_range_are_accepted():
    from bdc_loader_plugin.core.query_spec import validate_query_spec

    assert validate_query_spec({"collection": "S2-16D-2", "filters": {"cloud_cover_max": 20.5, "limit": 30}})[0]


def test_a_query_period_outside_the_collection_is_reported():
    from bdc_loader_plugin.core.query_spec import apply_ui_query_spec

    dialog = MagicMock()
    dialog.collection_combo.count.return_value = 0
    dialog.range_slider.set_start_date.return_value = False
    dialog.range_slider.set_end_date.return_value = True
    dialog.range_slider.get_start_date.return_value.toString.return_value = "2017-01-01"
    dialog.range_slider.get_end_date.return_value.toString.return_value = "2017-03-01"
    from qgis.PyQt.QtCore import QDate

    valid = MagicMock()
    valid.isValid.return_value = True
    with patch.object(QDate, "fromString", create=True, return_value=valid):
        apply_ui_query_spec(
            dialog, {"collection": "S2-16D-2", "temporal": {"start": "2010-01-01", "end": "2017-03-01"}}
        )
    text, kind = dialog._set_status.call_args[0]
    assert kind == "warning"
    assert i18n.tr(text, "pt") == (
        "O período da consulta, 2010-01-01 a 2017-03-01, passa das datas desta coleção; ele ficou de 2017-01-01 a "
        "2017-03-01."
    )


def test_a_new_card_is_hidden_explicitly_even_before_it_is_shown():
    owner = MagicMock()
    card = MagicMock(spec=["item", "setVisible", "isHidden"])
    card.item = SimpleNamespace(properties={"eo:cloud_cover": 90}, datetime=None)
    card.isHidden.return_value = True  # not shown yet
    owner.result_widgets = [card]
    owner._tile_filter_dict = {}
    owner._show_downloaded_only = False
    owner.filter_cloud_spin.value.return_value = 20

    assert ResultFilter._apply_result_filters(owner) == 0
    card.setVisible.assert_called_once_with(False)
    assert card._filtered_out is True


def test_a_filter_update_keeps_the_stale_parameters_message():
    owner = MagicMock()
    owner.result_widgets = []
    owner._tile_filter_dict = {}
    owner._show_downloaded_only = False
    owner.filter_cloud_spin.value.return_value = 100
    owner._results_fresh = False
    ResultFilter._apply_result_filters(owner)
    owner._show_result_count.assert_not_called()
