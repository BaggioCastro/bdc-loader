"""Area-filter hint text and the shared status Cancel button."""

from unittest.mock import MagicMock

import pytest

from bdc_loader_plugin.core.download import DownloadManager
from bdc_loader_plugin.core.shapefile import ShapefileHandler


def _handler(has_tiles=True, extent=False, tiles="", shape=None):
    handler = ShapefileHandler.__new__(ShapefileHandler)
    handler._spatial_hint = MagicMock()
    handler.extent_box = MagicMock()
    handler.extent_box.isActive.return_value = extent
    handler.extent_box.hasExtent.return_value = False
    handler.tiles_input = MagicMock()
    handler.tiles_input.text.return_value = tiles
    handler._shape_vector_layer = shape
    handler._collection_has_tiles = MagicMock(return_value=has_tiles)
    return handler


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({}, "Choose one area: Extent, Tiles or Vector File."),
        ({"extent": True}, "Using Extent. To use Tiles or Vector File, close it or clear it (\u2715) first."),
        ({"tiles": "031023"}, "Using Tiles. To use Extent or Vector File, close it or clear it (\u2715) first."),
        ({"shape": object()}, "Using Vector File. To use Extent or Tiles, close it or clear it (\u2715) first."),
        ({"has_tiles": False}, "Choose one area: Extent or Vector File. This collection has no tile grid."),
        (
            {"has_tiles": False, "shape": object()},
            "Using Vector File. To use Extent, close it or clear it (\u2715) first. This collection has no tile grid.",
        ),
    ],
)
def test_spatial_hint_names_the_active_filter(kwargs, expected):
    handler = _handler(**kwargs)
    handler._refresh_spatial_hint()
    handler._spatial_hint.setText.assert_called_once_with(expected)


@pytest.mark.parametrize(
    ("kwargs", "enabled"),
    [
        ({}, {"extent_box": True, "tiles_group": True, "shape_group": True}),
        ({"extent": True}, {"extent_box": True, "tiles_group": False, "shape_group": False}),
        ({"tiles": "031023"}, {"extent_box": False, "tiles_group": True, "shape_group": False}),
        ({"shape": object()}, {"extent_box": False, "tiles_group": False, "shape_group": True}),
        ({"has_tiles": False}, {"extent_box": True, "tiles_group": False, "shape_group": True}),
    ],
)
def test_locks_grey_out_every_filter_but_the_one_in_use(kwargs, enabled):
    handler = _handler(**kwargs)
    handler.tiles_group = MagicMock()
    handler.shape_group = MagicMock()

    handler._apply_spatial_locks()

    for attr, expected in enabled.items():
        group = getattr(handler, attr)
        group.setEnabled.assert_called_once_with(expected)
        if expected:
            group.setCollapsed.assert_not_called()
        else:
            group.setCollapsed.assert_called_once_with(True)


def test_vector_file_wins_over_stale_extent_state():
    handler = _handler(extent=True, tiles="031023", shape=object())
    assert handler._active_spatial_mode() == "Vector File"


def _cancel_owner():
    from bdc_loader_plugin.ui.main_layout import MainDialogLayout

    owner = MainDialogLayout.__new__(MainDialogLayout)
    owner._cancel_download_btn = MagicMock()
    return owner


def test_the_cancel_button_stops_the_operation_that_showed_it():
    owner = _cancel_owner()
    grid_cancel, download_cancel = MagicMock(), MagicMock()

    owner._show_cancel_button(grid_cancel)
    owner._cancel_active_operation()
    owner._cancel_active_operation()

    grid_cancel.assert_called_once_with()
    download_cancel.assert_not_called()
    owner._cancel_download_btn.setText.assert_called_with("Cancelling...")
    owner._cancel_download_btn.setEnabled.assert_called_with(False)


def test_a_hidden_cancel_button_stops_nothing():
    owner = _cancel_owner()
    on_cancel = MagicMock()
    owner._show_cancel_button(on_cancel)
    owner._hide_cancel_button()

    owner._cancel_active_operation()

    on_cancel.assert_not_called()


def test_cancelling_a_download_sets_its_flag():
    manager = DownloadManager.__new__(DownloadManager)
    manager._set_status = MagicMock()

    manager._cancel_download()

    assert manager._download_cancelled is True


@pytest.mark.parametrize(
    ("texts", "expected"),
    [
        (("-48.0", "-16", "-47,8", "-15.8"), (-48.0, -16.0, -47.8, -15.8)),
        (("-75,000000000", "-35,000000000", "-28,000000000", "6,000000000"), (-75.0, -35.0, -28.0, 6.0)),
        (("", "-16", "-47.8", "-15.8"), None),
        (("-47.8", "-16", "-48", "-15.8"), None),
        (("abc", "-16", "-47.8", "-15.8"), None),
    ],
)
def test_typed_rectangle(texts, expected):
    from bdc_loader_plugin.widgets.extent_group import typed_rectangle

    assert typed_rectangle(texts) == expected


class TestClosingAGroupPausesItsFilter:
    """Closing a group pauses its filter (others unlock) and keeps the choice;
    reopening resumes it; only the clear button forgets it."""

    def _handler(self, extent=False, tiles="", shape=None, has_extent=False):
        handler = _handler(extent=extent, tiles=tiles, shape=shape)
        handler.extent_box.hasExtent.return_value = has_extent
        handler._apply_spatial_locks = MagicMock()
        handler._offer_reference_grid = MagicMock()
        handler._clear_shapefile = MagicMock()
        handler.clear_tiles = MagicMock()
        return handler

    def test_closing_extent_pauses_it_and_reopening_resumes_it(self):
        handler = self._handler(extent=True, has_extent=True)
        handler._on_extent_expanded(True)
        handler.extent_box.suspend.assert_called_once_with()
        handler.extent_box.clear.assert_not_called()

        handler.extent_box.isActive.return_value = False
        handler._on_extent_expanded(False)
        handler.extent_box.setActive.assert_called_once_with(True)

    def test_closing_tiles_pauses_them_and_reopening_resumes_them(self):
        handler = self._handler(tiles="031023")
        handler._on_tiles_collapsed(True)
        assert handler._tiles_suspended is True
        assert handler._active_spatial_mode() is None
        assert handler._paused_spatial_modes() == ["Tiles"]
        handler.clear_tiles.assert_not_called()

        handler._on_tiles_collapsed(False)
        assert handler._tiles_suspended is False
        assert handler._active_spatial_mode() == "Tiles"

    def test_closing_vector_file_pauses_it_and_reopening_resumes_it(self):
        handler = self._handler(shape=object())
        handler._shape_features = [(1, "a", None)]
        handler._on_shape_collapsed(True)
        assert handler._shape_suspended is True
        assert handler._active_spatial_mode() is None
        assert handler._is_shape_search_active() is False
        assert handler._get_shape_bbox() is None
        handler._clear_shapefile.assert_not_called()

        handler._on_shape_collapsed(False)
        assert handler._active_spatial_mode() == "Vector File"

    def test_using_another_filter_keeps_the_paused_one(self):
        handler = self._handler(tiles="031023")
        handler._on_tiles_collapsed(True)
        handler._suspend_other_filters("Extent")
        assert handler._tiles_suspended is True
        assert handler.tiles_input.text() == "031023"

    def test_hint_says_a_closed_filter_is_kept(self):
        handler = self._handler(tiles="031023")
        handler._on_tiles_collapsed(True)
        handler._refresh_spatial_hint()
        text = handler._spatial_hint.setText.call_args.args[0]
        assert "Tiles is closed but kept: open to use again." in text


def test_clearing_tiles_forgets_a_paused_choice():
    from bdc_loader_plugin.core.grid import GridManager

    grid = GridManager.__new__(GridManager)
    grid._tiles_suspended = True
    grid.selected_tiles_list = MagicMock()
    grid.tiles_input = MagicMock()
    grid.clear_tiles()
    assert grid._tiles_suspended is False
    grid.tiles_input.clear.assert_called_once_with()


def test_paused_tiles_are_not_searched():
    from bdc_loader_plugin.core.grid import GridManager

    grid = GridManager.__new__(GridManager)
    grid._tiles_suspended = True
    assert grid.get_tiles_list() == []
