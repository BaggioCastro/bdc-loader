"""STAC item iteration across pystac_client versions, and timers that outlive their widgets."""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def test_search_items_prefers_items():
    from bdc_loader_plugin.stac.client import search_items

    search = MagicMock()
    search.items.return_value = iter(["a"])
    assert list(search_items(search)) == ["a"]
    search.get_items.assert_not_called()


def test_search_items_falls_back_to_get_items():
    from bdc_loader_plugin.stac.client import search_items

    search = SimpleNamespace(get_items=lambda: iter(["b"]))  # pystac_client before 0.5
    assert list(search_items(search)) == ["b"]


def _panel(label_text):
    panel = MagicMock()
    panel.status_label.text.return_value = label_text
    return panel


def _fake_sip(deleted):
    return SimpleNamespace(isdeleted=lambda obj: obj in deleted)


def test_status_reset_skipped_when_label_was_deleted():
    import qgis.PyQt

    from bdc_loader_plugin.core.ts_visualization import TSVisualization

    panel = _panel("done")
    with patch.object(sys.modules["qgis.PyQt"], "sip", _fake_sip({panel.status_label}), create=True):
        assert qgis.PyQt.sip.isdeleted(panel.status_label)
        TSVisualization._clear_status_if_unchanged(panel, "done")
    panel._reset_status_style.assert_not_called()
    panel.status_label.text.assert_not_called()


def test_status_reset_only_for_the_same_message():
    from bdc_loader_plugin.core.ts_visualization import TSVisualization

    with patch.object(sys.modules["qgis.PyQt"], "sip", _fake_sip(set()), create=True):
        same = _panel("done")
        TSVisualization._clear_status_if_unchanged(same, "done")
        newer = _panel("a newer message")
        TSVisualization._clear_status_if_unchanged(newer, "done")
    same._reset_status_style.assert_called_once_with()
    newer._reset_status_style.assert_not_called()
