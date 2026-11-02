#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_stac_browser_link.py — Tests for ResultItemWidget._open_browser.

A shape_mosaic/extent_crop result's own id is synthetic (e.g.
"crop_Crop_..._2026-06-10") and was never a real STAC item, so opening it
in STAC Browser must link to one of its real source items (or the
collection page, if none are available) instead of 404ing on the synthetic
id.

Run: python3 -m pytest bdc_loader_plugin/tests/test_stac_browser_link.py -v
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch


def _widget(item, collection_id="S2-16D-2"):
    from bdc_loader_plugin.ui.result_widgets import ResultItemWidget

    widget = ResultItemWidget.__new__(ResultItemWidget)
    widget.collection_id = collection_id
    widget.item = item
    return widget


class TestOpenBrowser(unittest.TestCase):
    def test_regular_item_links_to_its_own_id(self):
        from bdc_loader_plugin.ui.result_widgets import ResultItemWidget

        item = SimpleNamespace(id="S2-16D_V2_002011_20260626", properties={})
        widget = _widget(item)

        with patch("bdc_loader_plugin.ui.result_widgets.webbrowser") as wb:
            ResultItemWidget._open_browser(widget)

        wb.open.assert_called_once_with(
            "https://data.inpe.br/stac/browser/collections/S2-16D-2/items/S2-16D_V2_002011_20260626"
        )

    def test_shape_mosaic_links_to_a_real_source_item_not_the_synthetic_id(self):
        from bdc_loader_plugin.ui.result_widgets import ResultItemWidget

        source = SimpleNamespace(id="S2-16D_V2_002011_20260610")
        item = SimpleNamespace(
            id="shape_mosaic_Sao_Paulo_2026-06-10",
            properties={"bdc:is_shape_mosaic": True, "bdc:is_extent_crop": False},
            _source_items=[source],
        )
        widget = _widget(item)

        with patch("bdc_loader_plugin.ui.result_widgets.webbrowser") as wb:
            ResultItemWidget._open_browser(widget)

        wb.open.assert_called_once_with(
            "https://data.inpe.br/stac/browser/collections/S2-16D-2/items/S2-16D_V2_002011_20260610"
        )

    def test_extent_crop_links_to_a_real_source_item_not_the_synthetic_id(self):
        """_is_shape_mosaic() is deliberately False for crop
        results (it's mutually exclusive with _is_extent_crop() for label
        display), so _open_browser must not gate on it directly, or a crop
        result falls through to its own non-existent synthetic item id."""
        from bdc_loader_plugin.ui.result_widgets import ResultItemWidget

        source = SimpleNamespace(id="S2-16D_V2_002011_20260610")
        item = SimpleNamespace(
            id="crop_Crop_18_7S_53_1W_to_18_5S_52_8W_2026-06-10",
            properties={"bdc:is_shape_mosaic": True, "bdc:is_extent_crop": True},
            _source_items=[source],
        )
        widget = _widget(item)

        with patch("bdc_loader_plugin.ui.result_widgets.webbrowser") as wb:
            ResultItemWidget._open_browser(widget)

        wb.open.assert_called_once_with(
            "https://data.inpe.br/stac/browser/collections/S2-16D-2/items/S2-16D_V2_002011_20260610"
        )

    def test_mosaic_without_source_items_falls_back_to_collection_page(self):
        from bdc_loader_plugin.ui.result_widgets import ResultItemWidget

        item = SimpleNamespace(
            id="crop_Crop_18_7S_53_1W_to_18_5S_52_8W_2026-06-10",
            properties={"bdc:is_shape_mosaic": True, "bdc:is_extent_crop": True},
            _source_items=[],
        )
        widget = _widget(item)

        with patch("bdc_loader_plugin.ui.result_widgets.webbrowser") as wb:
            ResultItemWidget._open_browser(widget)

        wb.open.assert_called_once_with("https://data.inpe.br/stac/browser/collections/S2-16D-2")

    def test_missing_collection_id_does_nothing(self):
        from bdc_loader_plugin.ui.result_widgets import ResultItemWidget

        item = SimpleNamespace(id="x", properties={})
        widget = _widget(item, collection_id=None)

        with patch("bdc_loader_plugin.ui.result_widgets.webbrowser") as wb:
            ResultItemWidget._open_browser(widget)

        wb.open.assert_not_called()


if __name__ == "__main__":
    unittest.main()
