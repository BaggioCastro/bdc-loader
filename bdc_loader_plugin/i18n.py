"""Interface language: English or Brazilian Portuguese, switched at run time.

Texts are written in English in the code. ``tr`` gives the Portuguese text
from ``i18n_pt`` when Portuguese is chosen, and ``translate_tree`` swaps the
texts of widgets already built (labels, buttons, group titles, tool tips,
placeholders, window titles, and the items of combo boxes that ask for it).
Each widget keeps its English text in a property, so switching back and forth
never translates a translation. A text the code sets while the window is open
goes through ``set_text``, which records the English text the same way.
"""

import re

from qgis.core import QgsSettings
from qgis.PyQt.QtCore import QEvent, QObject, Qt
from qgis.PyQt.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QDockWidget,
    QGroupBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QTabWidget,
    QTextEdit,
    QWidget,
)

from .i18n_pt import PATTERNS, TEXTS

LANGUAGE_SETTING = "bdc_loader/language"
LANGUAGES = ("en", "pt")
# A combo box whose items are interface words, not data, sets this property to True.
TRANSLATE_ITEMS = "bdc_translate_items"
# While the BDC is unreachable the status line starts with this; it reads the same in Portuguese.
OFFLINE_PREFIX = "<b>Offline</b> \u00b7 "


def _unescape(replacement):
    """A replacement written as a raw string may hold \\uXXXX escapes, which re.sub refuses."""
    if not isinstance(replacement, str):
        return replacement
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), replacement)


_COMPILED = [(re.compile(pattern), _unescape(replacement)) for pattern, replacement in PATTERNS]
_current = []


def language():
    """The chosen language; the first time, Portuguese when QGIS runs in Portuguese."""
    if not _current:
        settings = QgsSettings()
        chosen = settings.value(LANGUAGE_SETTING, "", type=str)
        if chosen not in LANGUAGES:
            locale = settings.value("locale/userLocale", "", type=str) or ""
            chosen = "pt" if locale.lower().startswith("pt") else "en"
        _current.append(chosen)
    return _current[0]


def set_language(lang):
    lang = lang if lang in LANGUAGES else "en"
    QgsSettings().setValue(LANGUAGE_SETTING, lang)
    _current[:] = [lang]


def tr(text, lang=None):
    """``text`` in the interface language; unchanged when there is no translation."""
    if not text or (lang or language()) != "pt":
        return text
    if text.startswith(OFFLINE_PREFIX):
        return OFFLINE_PREFIX + tr(text[len(OFFLINE_PREFIX) :], lang)
    found = TEXTS.get(text)
    if found is not None:
        return found
    for pattern, replacement in _COMPILED:
        if pattern.fullmatch(text):
            return pattern.sub(replacement, text)
    return text


def count_label(n, one, many):
    """``n`` followed by the singular or the plural word: "1 image", "24 images"."""
    return f"{n} {one if n == 1 else many}"


def failure_text(process, reason):
    """The status of a failed process: "<process> failed: <reason>."."""
    return f"{process} failed: {str(reason).strip().rstrip('.')}."


def both(text):
    """The English text and its translation, to size a widget that shows either."""
    return list(dict.fromkeys((text, tr(text, "pt"))))


def _swap(widget, key, get, put, lang):
    """Show the translation of the widget's English text for ``key``."""
    current = get()
    stored = widget.property(f"bdc_en_{key}")
    shown = widget.property(f"bdc_shown_{key}")
    english = stored if stored is not None and current == shown else current
    text = tr(english, lang)
    if text != current:
        put(text)
    widget.setProperty(f"bdc_en_{key}", english)
    widget.setProperty(f"bdc_shown_{key}", text)


_SETTERS = {"text": "setText", "tip": "setToolTip", "placeholder": "setPlaceholderText", "title": "setTitle"}


def set_text(widget, english, key="text"):
    """Show ``english`` on ``widget`` in the interface language.

    ``key`` picks the text: "text", "tip" (tool tip), "placeholder" or "title"
    (group box). The English text is recorded, so a later language switch
    shows the right one.
    """
    shown = tr(english)
    getattr(widget, _SETTERS[key])(shown)
    widget.setProperty(f"bdc_en_{key}", english)
    widget.setProperty(f"bdc_shown_{key}", shown)


# Item data roles where a list item keeps its English text and the text last shown.
_ITEM_ENGLISH = Qt.ItemDataRole.UserRole + 101
_ITEM_SHOWN = Qt.ItemDataRole.UserRole + 102


def _swap_item(item, lang):
    current = item.text()
    stored = item.data(_ITEM_ENGLISH)
    english = stored if stored is not None and current == item.data(_ITEM_SHOWN) else current
    text = tr(english, lang)
    if text != current:
        item.setText(text)
    item.setData(_ITEM_ENGLISH, english)
    item.setData(_ITEM_SHOWN, text)


def _swap_combo_items(combo, lang):
    for i in range(combo.count()):
        current = combo.itemText(i)
        stored = combo.itemData(i, _ITEM_ENGLISH)
        english = stored if stored is not None and current == combo.itemData(i, _ITEM_SHOWN) else current
        text = tr(english, lang)
        if text != current:
            combo.setItemText(i, text)
        combo.setItemData(i, english, _ITEM_ENGLISH)
        combo.setItemData(i, text, _ITEM_SHOWN)


def english_text(combo):
    """The English text of the combo box's current item, whatever language it shows."""
    index = combo.currentIndex()
    stored = combo.itemData(index, _ITEM_ENGLISH) if index >= 0 else None
    return stored if stored is not None else combo.currentText()


def translate_widget(widget, lang=None):
    lang = lang or language()
    if isinstance(widget, (QAbstractButton, QLabel)):
        _swap(widget, "text", widget.text, widget.setText, lang)
    if isinstance(widget, QGroupBox):
        _swap(widget, "title", widget.title, widget.setTitle, lang)
    if isinstance(widget, QDockWidget):
        _swap(widget, "title", widget.windowTitle, widget.setWindowTitle, lang)
    if isinstance(widget, (QLineEdit, QPlainTextEdit, QTextEdit)):
        _swap(widget, "placeholder", widget.placeholderText, widget.setPlaceholderText, lang)
    if isinstance(widget, QListWidget):
        for row in range(widget.count()):
            _swap_item(widget.item(row), lang)
    if isinstance(widget, QComboBox) and widget.property(TRANSLATE_ITEMS):
        _swap_combo_items(widget, lang)
    if isinstance(widget, QTabWidget):
        for i in range(widget.count()):
            _swap(widget, f"tab{i}", lambda i=i: widget.tabText(i), lambda t, i=i: widget.setTabText(i, t), lang)
    if widget.isWindow() and not isinstance(widget, QDockWidget):
        _swap(widget, "window", widget.windowTitle, widget.setWindowTitle, lang)
    if widget.toolTip():
        _swap(widget, "tip", widget.toolTip, widget.setToolTip, lang)


def translate_tree(root, lang=None):
    """Translate ``root`` and every widget inside it."""
    if root is None:
        return
    lang = lang or language()
    translate_widget(root, lang)
    for child in root.findChildren(QWidget):
        translate_widget(child, lang)


class LanguageWatcher(QObject):
    """Translates the dialogs, message boxes and menus opened over the watched widgets as they show."""

    def watch(self, widget):
        if widget is not None:
            widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QEvent.Type.ChildAdded:
            child = event.child()
            if child is not None and child.isWidgetType() and child.isWindow():
                child.installEventFilter(self)
        elif kind == QEvent.Type.Show and obj.isWidgetType() and obj.isWindow() and language() == "pt":
            translate_tree(obj)
        return False
