#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_log_panel.py — Tests for ui/log_panel.py's LogWindow.

Covers: Copy (selected lines, or all when nothing is selected) uses the
full untruncated message rather than the row's display text.

Run: python3 -m pytest bdc_loader_plugin/tests/test_log_panel.py -v
"""

import unittest
from unittest.mock import MagicMock, patch


class _FakeListWidgetItem:
    def __init__(self, text=""):
        self._text = text
        self._tooltip = ""
        self._data = {}

    def text(self):
        return self._text

    def setToolTip(self, tooltip):
        self._tooltip = tooltip

    def setForeground(self, *_a, **_kw):
        pass

    def setBackground(self, *_a, **_kw):
        pass

    def setData(self, role, value):
        self._data[role] = value

    def data(self, role):
        return self._data.get(role)


class _FakeListWidget:
    def __init__(self):
        self._items = []
        self._selected = []

    def setFont(self, *_a, **_kw):
        pass

    def setFixedHeight(self, *_a, **_kw):
        pass

    def setStyleSheet(self, *_a, **_kw):
        pass

    def setSelectionMode(self, *_a, **_kw):
        pass

    def setVerticalScrollBarPolicy(self, *_a, **_kw):
        pass

    def setHorizontalScrollBarPolicy(self, *_a, **_kw):
        pass

    def scrollToBottom(self):
        pass

    def count(self):
        return len(self._items)

    def item(self, i):
        return self._items[i]

    def addItem(self, item):
        self._items.append(item)

    def takeItem(self, i):
        return self._items.pop(i)

    def clear(self):
        self._items.clear()

    def selectedItems(self):
        return self._selected


def _make_window():
    """A LogWindow with a real (test-double) list but without running the
    real __init__ — that pulls in QDialog window-flag construction and other
    Qt setup unrelated to what Copy actually needs: a populated list."""
    import bdc_loader_plugin.ui.log_panel as module

    window = module.LogWindow.__new__(module.LogWindow)
    window._list = _FakeListWidget()
    return window, module


class TestLogWindowCopy(unittest.TestCase):
    def test_copy_with_no_selection_copies_every_line(self):
        window, module = _make_window()
        with patch.object(module, "QListWidgetItem", _FakeListWidgetItem):
            window.add_entry({"level": "INFO", "src": "download", "ts": "2026-07-23T10:00:00", "msg": "first"})
            window.add_entry({"level": "ERROR", "src": "download", "ts": "2026-07-23T10:00:05", "msg": "second"})

        clipboard = MagicMock()
        fake_app = MagicMock()
        fake_app.clipboard.return_value = clipboard
        with patch.object(module, "QApplication", fake_app):
            window._copy()

        copied = clipboard.setText.call_args.args[0]
        self.assertIn("first", copied)
        self.assertIn("second", copied)
        self.assertEqual(len(copied.splitlines()), 2)

    def test_copy_with_selection_copies_only_selected_lines(self):
        window, module = _make_window()
        with patch.object(module, "QListWidgetItem", _FakeListWidgetItem):
            window.add_entry({"level": "INFO", "src": "download", "ts": "2026-07-23T10:00:00", "msg": "first"})
            window.add_entry({"level": "INFO", "src": "download", "ts": "2026-07-23T10:00:05", "msg": "second"})
        window._list._selected = [window._list.item(1)]

        clipboard = MagicMock()
        fake_app = MagicMock()
        fake_app.clipboard.return_value = clipboard
        with patch.object(module, "QApplication", fake_app):
            window._copy()

        copied = clipboard.setText.call_args.args[0]
        self.assertNotIn("first", copied)
        self.assertIn("second", copied)

    def test_copy_uses_full_untruncated_message_not_display_text(self):
        window, module = _make_window()
        long_msg = "x" * 500  # display text truncates the message at 220 chars
        with patch.object(module, "QListWidgetItem", _FakeListWidgetItem):
            window.add_entry({"level": "INFO", "src": "download", "ts": "2026-07-23T10:00:00", "msg": long_msg})

        clipboard = MagicMock()
        fake_app = MagicMock()
        fake_app.clipboard.return_value = clipboard
        with patch.object(module, "QApplication", fake_app):
            window._copy()

        copied = clipboard.setText.call_args.args[0]
        self.assertIn(long_msg, copied)


if __name__ == "__main__":
    unittest.main()
