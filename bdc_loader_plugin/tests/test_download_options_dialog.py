#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_download_options_dialog.py — Tests for widgets/dialogs.DownloadOptionsDialog.

The suite-wide PyQt5 mock returns MagicMocks for widgets, which answer every
call and therefore cannot show whether the dialog wires itself correctly. These
tests swap in small fakes for just the widgets this dialog reads back — radio
buttons that really emit `toggled`, a checkbox that really remembers its state,
and a label that really stores its text — so the selection, the destination
preview, and the answers the download flow reads are exercised for real.

Run: python3 -m pytest bdc_loader_plugin/tests/test_download_options_dialog.py -v
"""

import unittest
from unittest.mock import patch

from bdc_loader_plugin.core import output_crs
from bdc_loader_plugin.widgets import dialogs


class _FakeSignal:
    def __init__(self):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def emit(self, *args):
        for slot in self._slots:
            slot(*args)


class _FakeRadio:
    """A radio button that emits `toggled` the way Qt does, including the
    emission triggered while the dialog is still being built."""

    def __init__(self, text=""):
        self.text = text
        self.tooltip = ""
        self._enabled = True
        self._checked = False
        self._group = None
        self.toggled = _FakeSignal()

    def setEnabled(self, enabled):
        self._enabled = bool(enabled)

    def isEnabled(self):
        return self._enabled

    def setToolTip(self, tooltip):
        self.tooltip = tooltip

    def setChecked(self, checked):
        if self._checked == bool(checked):
            return
        self._checked = bool(checked)
        if self._checked and self._group is not None:
            self._group.exclusive(self)
        self.toggled.emit(self._checked)

    def isChecked(self):
        return self._checked


class _FakeButtonGroup:
    def __init__(self, *_args):
        self.buttons = []

    def addButton(self, button):
        self.buttons.append(button)
        button._group = self

    def exclusive(self, checked_button):
        for button in self.buttons:
            if button is not checked_button:
                button.setChecked(False)


class _FakeCheckBox:
    def __init__(self, text=""):
        self.text = text
        self._checked = False
        self._enabled = True
        self.tooltip = ""
        self.toggled = _FakeSignal()

    def setChecked(self, checked):
        if self._checked == bool(checked):
            return
        self._checked = bool(checked)
        self.toggled.emit(self._checked)

    def isChecked(self):
        return self._checked

    def setEnabled(self, enabled):
        self._enabled = bool(enabled)

    def isEnabled(self):
        return self._enabled

    def setToolTip(self, tooltip):
        self.tooltip = tooltip


class _FakeLabel:
    def __init__(self, text=""):
        self._text = text

    def setText(self, text):
        self._text = text

    def text(self):
        return self._text

    def setWordWrap(self, _wrap):
        pass

    def setProperty(self, _name, _value):
        pass

    def setStyleSheet(self, _style):
        pass


def _build(options, selected_key, destination_for=None, **kwargs):
    with (
        patch.object(dialogs, "QRadioButton", _FakeRadio),
        patch.object(dialogs, "QButtonGroup", _FakeButtonGroup),
        patch.object(dialogs, "QCheckBox", _FakeCheckBox),
        patch.object(dialogs, "QLabel", _FakeLabel),
    ):
        return dialogs.DownloadOptionsDialog(
            "Download 1 band(s) for mosaic_1?",
            options,
            selected_key,
            destination_for=destination_for,
            **kwargs,
        )


def _options(project_authid="EPSG:31983"):
    from qgis.core import QgsCoordinateReferenceSystem

    crs = QgsCoordinateReferenceSystem(project_authid)
    crs._authid = project_authid
    crs._description = "SIRGAS 2000 / UTM zone 23S"
    return output_crs.build_options(crs)


class TestSelection(unittest.TestCase):
    def test_opens_on_the_requested_projection(self):
        dialog = _build(_options(), output_crs.WGS84)

        self.assertEqual(dialog.selected_option().key, output_crs.WGS84)

    def test_exactly_one_projection_is_checked(self):
        dialog = _build(_options(), output_crs.PROJECT)

        checked = [key for key, radio in dialog._buttons.items() if radio.isChecked()]
        self.assertEqual(checked, [output_crs.PROJECT])

    def test_unavailable_projection_falls_back_to_the_first_enabled_one(self):
        """A stored "project CRS" choice must not leave the dialog with a
        disabled option selected and nothing to download into."""
        dialog = _build(output_crs.build_options(None), output_crs.PROJECT)

        self.assertEqual(dialog.selected_option().key, output_crs.NATIVE)
        self.assertFalse(dialog._buttons[output_crs.PROJECT].isEnabled())

    def test_unknown_key_falls_back_instead_of_selecting_nothing(self):
        dialog = _build(_options(), "no-such-projection")

        self.assertIsNotNone(dialog.selected_option())

    def test_disabled_option_is_shown_not_hidden(self):
        dialog = _build(output_crs.build_options(None), output_crs.NATIVE)

        self.assertEqual(len(dialog._buttons), 3)

    def test_hints_reach_the_radio_tooltips(self):
        dialog = _build(_options(), output_crs.NATIVE)

        for option in dialog._options:
            self.assertEqual(dialog._buttons[option.key].tooltip, option.hint)


class TestDestinationPreview(unittest.TestCase):
    """Each projection is written to its own file, so the dialog has to say
    which one it is about to write."""

    @staticmethod
    def _destination_for(option, fmt, sits, folder):
        suffix = f"_{option.tag}" if option.tag else ""
        return f"{folder}/mosaic_1_B04_masked{suffix}.tif [{fmt}{' sits' if sits else ''}]"

    def test_destination_is_filled_in_during_construction(self):
        """The radio buttons emit `toggled` while the dialog is still being
        built; the label they write into has to exist by then."""
        dialog = _build(_options(), output_crs.WGS84, destination_for=self._destination_for)

        self.assertIn("_masked_epsg4326.tif", dialog.destination_label.text())

    def test_destination_follows_a_change_of_projection(self):
        dialog = _build(_options(), output_crs.NATIVE, destination_for=self._destination_for)
        self.assertIn("_masked.tif", dialog.destination_label.text())

        dialog._buttons[output_crs.PROJECT].setChecked(True)

        self.assertIn("_masked_epsg31983.tif", dialog.destination_label.text())

    def test_no_destination_callback_leaves_the_label_empty(self):
        dialog = _build(_options(), output_crs.NATIVE)

        self.assertEqual(dialog.destination_label.text(), "")


class TestFormat(unittest.TestCase):
    """How the files are delivered: per band, per band + VRT, or one multiband file."""

    def test_opens_on_the_stored_format(self):
        dialog = _build(_options(), output_crs.NATIVE, selected_format="multiband")

        self.assertEqual(dialog.selected_format(), "multiband")

    def test_unknown_format_falls_back_to_per_band(self):
        dialog = _build(_options(), output_crs.NATIVE, selected_format="zip")

        self.assertEqual(dialog.selected_format(), "per_band")

    def test_one_band_offers_only_per_band(self):
        dialog = _build(_options(), output_crs.NATIVE, selected_format="multiband", band_count=1)

        self.assertEqual(dialog.selected_format(), "per_band")
        self.assertFalse(dialog._format_buttons["multiband"].isEnabled())
        self.assertFalse(dialog._format_buttons["per_band_vrt"].isEnabled())

    def test_sits_names_only_apply_to_per_band(self):
        dialog = _build(_options(), output_crs.NATIVE, selected_format="per_band", sits_names=True)
        self.assertTrue(dialog.sits_names())
        self.assertTrue(dialog.sits_check.isEnabled())

        dialog._format_buttons["per_band_vrt"].setChecked(True)

        self.assertFalse(dialog.sits_names())
        self.assertFalse(dialog.sits_check.isEnabled())

    def test_destination_follows_format_and_sits(self):
        dialog = _build(
            _options(),
            output_crs.NATIVE,
            destination_for=TestDestinationPreview._destination_for,
            folder="/data",
        )
        self.assertIn("[per_band]", dialog.destination_label.text())
        self.assertIn("/data/", dialog.destination_label.text())

        dialog.sits_check.setChecked(True)
        self.assertIn("[per_band sits]", dialog.destination_label.text())

        dialog._format_buttons["multiband"].setChecked(True)
        self.assertIn("[multiband]", dialog.destination_label.text())


class TestAnswers(unittest.TestCase):
    """What _download_masked_mosaic reads back off the dialog."""

    def test_remember_starts_off(self):
        dialog = _build(_options(), output_crs.NATIVE)

        self.assertFalse(dialog.remember_choice())

    def test_remember_reflects_the_checkbox(self):
        dialog = _build(_options(), output_crs.NATIVE)
        dialog.remember_check.setChecked(True)

        self.assertTrue(dialog.remember_choice())


if __name__ == "__main__":
    unittest.main()
