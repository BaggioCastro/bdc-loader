# -*- coding: utf-8 -*-
"""
Integration Tests for Query Specification, Export & Import Components.
"""

import unittest
from unittest.mock import MagicMock

from bdc_loader_plugin.core.query_spec import (
    HAS_YAML,
    _apply_spatial,
    query_to_curl,
    query_to_json,
    query_to_python,
    query_to_r_rstac,
    query_to_r_sits,
    query_to_yaml,
    sits_collection_for,
    validate_query_spec,
)


class TestQuerySpecIntegration(unittest.TestCase):
    def setUp(self):
        self.sample_spec = {
            "version": "1.0",
            "stac_url": "https://data.inpe.br/bdc/stac/v1",
            "collection": "S2-16D-2",
            "temporal": {"start": "2024-01-01", "end": "2024-12-31"},
            "spatial": {"type": "tiles", "tiles": ["044058", "044059"]},
            "filters": {"cloud_cover_max": 20, "limit": 100},
            "bands": ["B04", "B03", "B02"],
        }

    def test_validation_success(self):
        ok, msg = validate_query_spec(self.sample_spec)
        self.assertTrue(ok)
        self.assertIn("S2-16D-2", msg)

    def test_validation_failures(self):
        # Invalid collection type
        ok, msg = validate_query_spec({"collection": 123})
        self.assertFalse(ok)

        # Invalid date order
        bad_dates = {"collection": "S2-16D-2", "temporal": {"start": "2024-12-31", "end": "2024-01-01"}}
        ok, msg = validate_query_spec(bad_dates)
        self.assertFalse(ok)

        # Invalid BBOX bounds
        bad_bbox = {"collection": "S2-16D-2", "spatial": {"type": "bbox", "bbox": [200, -15, -47, -15]}}
        ok, msg = validate_query_spec(bad_bbox)
        self.assertFalse(ok)

    def test_code_generators(self):
        json_str = query_to_json(self.sample_spec)
        self.assertIn('"collection": "S2-16D-2"', json_str)

        yaml_str = query_to_yaml(self.sample_spec)
        # query_to_yaml falls back to JSON when PyYAML is unavailable; assert the
        # native YAML form only where PyYAML is present.
        if HAS_YAML:
            self.assertIn("collection: S2-16D-2", yaml_str)
        else:
            self.assertIn('"collection": "S2-16D-2"', yaml_str)

        r_sits = query_to_r_sits(self.sample_spec)
        self.assertIn("sits_cube", r_sits)
        self.assertIn('collection = "SENTINEL-2-16D"', r_sits)

        r_rstac = query_to_r_rstac(self.sample_spec)
        self.assertIn("stac_search", r_rstac)
        self.assertIn("eo:cloud_cover", r_rstac)

        python_str = query_to_python(self.sample_spec)
        self.assertIn("Client.open", python_str)
        self.assertIn("eo:cloud_cover", python_str)

        curl_str = query_to_curl(self.sample_spec)
        self.assertIn("curl -X POST", curl_str)
        self.assertIn("eo:cloud_cover", curl_str)


class TestSitsAvailability(unittest.TestCase):
    """sits exposes only a subset of BDC collections; unsupported ones must be flagged."""

    def test_supported_collection_maps_case_insensitively(self):
        self.assertEqual(sits_collection_for("S2-16D-2"), "SENTINEL-2-16D")
        self.assertEqual(sits_collection_for("s2-16d-2"), "SENTINEL-2-16D")

    def test_unsupported_collection_returns_none(self):
        self.assertIsNone(sits_collection_for("landsat-tsirf-bimonthly-1"))
        self.assertIsNone(sits_collection_for("S2_L2A-1"))
        self.assertIsNone(sits_collection_for(""))

    def test_r_sits_warns_for_unsupported_collection(self):
        spec = {"collection": "landsat-tsirf-bimonthly-1", "temporal": {"start": "1997-01-01", "end": "2024-12-31"}}
        out = query_to_r_sits(spec)
        self.assertIn("WARNING", out)
        self.assertIn("not available in the sits BDC source", out)

    def test_r_sits_no_warning_for_supported_collection(self):
        spec = {"collection": "S2-16D-2", "temporal": {"start": "2024-01-01", "end": "2024-12-31"}}
        out = query_to_r_sits(spec)
        self.assertNotIn("WARNING", out)
        self.assertIn('collection = "SENTINEL-2-16D"', out)


class TestApplySpatialRoundTrip(unittest.TestCase):
    """Guards that spatial reapply routes to the dialog's real entry points
    (tiles_input, _apply_manual_bbox, _load_shapefile)."""

    def _fake_dialog(self):
        return MagicMock()

    def test_tiles_reapply_sets_tiles_input(self):
        d = self._fake_dialog()
        _apply_spatial(d, {"type": "tiles", "tiles": ["044058", "044059"]})
        d.clear_tiles.assert_called_once()
        d.tiles_input.setText.assert_called_once_with("044058, 044059")

    def test_bbox_reapply_uses_manual_bbox_entry(self):
        d = self._fake_dialog()
        _apply_spatial(d, {"type": "bbox", "bbox": [-65.3, -11.9, -62.9, -9.7], "is_extent_crop": True})
        d._extent_bbox_edit.setText.assert_called_once_with("-65.3,-11.9,-62.9,-9.7")
        d._apply_manual_bbox.assert_called_once()
        d._extent_mode_crop.setChecked.assert_called_once_with(True)

    def test_vector_reapply_loads_shapefile(self):
        d = self._fake_dialog()
        _apply_spatial(d, {"type": "vector", "file": __file__})
        d._load_shapefile.assert_called_once_with(__file__)

    def test_vector_missing_file_is_ignored(self):
        d = self._fake_dialog()
        _apply_spatial(d, {"type": "vector", "file": "/nonexistent/path.shp"})
        d._load_shapefile.assert_not_called()


class TestGeneratorValidity(unittest.TestCase):
    """Validates the shape of the generated code, not just substrings (for example,
    a single post_request in the rstac code)."""

    def _specs(self):
        base = {
            "collection": "S2-16D-2",
            "temporal": {"start": "2024-01-01", "end": "2024-12-31"},
            "filters": {"cloud_cover_max": 10, "limit": 50},
            "bands": ["B04", "B03", "B02"],
        }
        return [
            {**base, "spatial": {"type": "tiles", "tiles": ["044058"]}},
            {**base, "spatial": {"type": "bbox", "bbox": [-60, -13, -59, -12]}},
            {
                **base,
                "spatial": {
                    "type": "vector",
                    "file": "/x.gpkg",
                    "attribute": "name",
                    "merged": False,
                    "selected_features": ["A1"],
                    "bbox": [-60, -13, -59, -12],
                },
            },
        ]

    def test_python_is_syntactically_valid(self):
        import ast

        for spec in self._specs():
            self.assertIsInstance(ast.parse(query_to_python(spec)), ast.Module)

    def test_rstac_issues_a_single_request(self):
        for spec in self._specs():
            out = query_to_r_rstac(spec)
            self.assertEqual(out.count("post_request"), 1, out)
            self.assertIn("items <- post_request(query)", out)

    def test_rstac_uses_expression_query_form(self):
        out = query_to_r_rstac(
            {
                "collection": "S2-16D-2",
                "temporal": {"start": "2024-01-01", "end": "2024-12-31"},
                "spatial": {"type": "tiles", "tiles": ["044058"]},
                "filters": {"cloud_cover_max": 20, "limit": 50},
            }
        )
        self.assertIn('"bdc:tiles" %in% c(', out)
        self.assertIn('"eo:cloud_cover" <= 20', out)
        self.assertNotIn('list("in"', out)


class _Combo:
    def __init__(self, data=None, visible=True):
        self._data, self.index, self._visible = data or {}, None, visible

    def isVisible(self):
        return self._visible

    def findData(self, d):
        return self._data.get(d, -1)

    def setCurrentIndex(self, i):
        self.index = i


class _Check:
    def __init__(self):
        self.checked = None

    def setChecked(self, v):
        self.checked = v


class _Item:
    def __init__(self, text):
        self._text, self.state = text, None

    def text(self):
        return self._text

    def setCheckState(self, s):
        self.state = s


class _FeatList:
    def __init__(self, texts):
        self._items = [_Item(t) for t in texts]

    def count(self):
        return len(self._items)

    def item(self, i):
        return self._items[i]


class _VecDialog:
    def __init__(self):
        self.shape_layer_combo = _Combo({"lots": 1})
        self.shape_attr_combo = _Combo({"name": 2})
        self.shape_merge_check = _Check()
        self.shape_feature_list = _FeatList(["A1", "A2", "A3"])


class TestVectorRoundTrip(unittest.TestCase):
    """The vector ROI must round-trip its layer, attribute, merge mode and
    per-feature selection on import."""

    def test_restore_applies_full_substate(self):
        from PyQt5.QtCore import Qt

        from bdc_loader_plugin.core.query_spec import _restore_vector_state

        d = _VecDialog()
        _restore_vector_state(
            d,
            {
                "type": "vector",
                "layer": "lots",
                "attribute": "name",
                "merged": False,
                "selected_features": ["A1", "A3"],
            },
        )
        self.assertEqual(d.shape_layer_combo.index, 1)
        self.assertEqual(d.shape_attr_combo.index, 2)
        self.assertFalse(d.shape_merge_check.checked)
        states = [d.shape_feature_list.item(i).state for i in range(3)]
        self.assertEqual(states, [Qt.Checked, Qt.Unchecked, Qt.Checked])

    def test_restore_merged_skips_feature_selection(self):
        from bdc_loader_plugin.core.query_spec import _restore_vector_state

        d = _VecDialog()
        _restore_vector_state(d, {"type": "vector", "merged": True, "selected_features": ["A1"]})
        self.assertTrue(d.shape_merge_check.checked)
        self.assertTrue(all(d.shape_feature_list.item(i).state is None for i in range(3)))


if __name__ == "__main__":
    unittest.main()
