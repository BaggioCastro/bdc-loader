"""Every interface text written in the code has a Portuguese version, and texts set
while a window is open go through ``set_text`` so they follow the language."""

import ast
import os
import re

import pytest

from bdc_loader_plugin import i18n

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_SETTERS = {
    "_set_status",
    "setText",
    "setToolTip",
    "setTitle",
    "setWindowTitle",
    "setPlaceholderText",
    "addItem",
    "addAction",
    "_show_message",
}
_CONSTRUCTORS = {"QLabel", "QPushButton", "QCheckBox", "QGroupBox", "QRadioButton", "QToolButton", "QAction"}
_MESSAGE_BOX = {"information", "warning", "critical", "question"}
_WORD = re.compile(r"\b[A-Za-z][a-z]{2,}\b")

# Texts that read the same in Portuguese.
_SAME = {
    "xmin,ymin,xmax,ymax",
    "Python (pystac-client)",
    "BDC Loader",
    "BDC VRT Loader",
    "BDC Proj",
    "Download",
    "Tiles",
    "Docs",
    "Tour",
    "Multi",
    "Lon",
    "Lat",
    "Auto",
    " Min:",
    "Max:",
    "Pts:",
}
_SAME_PATTERNS = [
    re.compile(r"\(\d+(/\d+)? tiles\)"),
    re.compile(r"BDC Loader v.+"),
    re.compile(r"Total: .+"),
    re.compile(r"<span[^>]*><b>Brazil Data Cube</b> - Loader v.+</span>"),
]


def _sources():
    for folder, _dirs, files in os.walk(ROOT):
        if any(part in folder for part in ("tests", "lib", "__pycache__")):
            continue
        for name in sorted(files):
            if name.endswith(".py") and not name.startswith("i18n"):
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8") as f:
                    yield os.path.relpath(path, ROOT).replace(os.sep, "/"), ast.parse(f.read())


def _counted(value, filler):
    """A ``count_label(n, one, many)`` field: the singular for the filler "1", else the plural with 2."""
    call = value.value if isinstance(value, ast.FormattedValue) else None
    if not (isinstance(call, ast.Call) and getattr(call.func, "id", "") == "count_label" and len(call.args) == 3):
        return None
    one, many = (arg.value if isinstance(arg, ast.Constant) else None for arg in call.args[1:])
    if not (isinstance(one, str) and isinstance(many, str)):
        return None
    return f"1 {one}" if filler == "1" else f"2 {many}"


def _render(node, filler):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            counted = _counted(v, filler)
            parts.append(v.value if isinstance(v, ast.Constant) else counted if counted is not None else filler)
        return "".join(parts)
    return None


def _text_arguments(call):
    func = call.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    if name in _SETTERS or name in _CONSTRUCTORS:
        return call.args[:1]
    if name == "set_text":
        return call.args[1:2]
    # Validation problems are listed in a message box.
    if name == "append" and isinstance(func, ast.Attribute) and getattr(func.value, "id", "") == "problems":
        return call.args[:1]
    if name in _MESSAGE_BOX and isinstance(func, ast.Attribute) and ast.unparse(func.value).endswith("QMessageBox"):
        return call.args[1:3]
    if name == "addItems" and call.args and isinstance(call.args[0], (ast.List, ast.Tuple)):
        return list(call.args[0].elts)
    return []


def _untranslated():
    missing = []
    for path, tree in _sources():
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            for arg in _text_arguments(call):
                texts = [_render(arg, filler) for filler in ("1", "x", "BDC_SM_V2", "S2-16D-2")]
                if texts[0] is None or not _WORD.search(re.sub(r"<[^>]+>|&\w+;", " ", texts[0])):
                    continue
                if texts[0] in _SAME or any(p.fullmatch(texts[0]) for p in _SAME_PATTERNS):
                    continue
                if all(i18n.tr(text, "pt") == text for text in texts):
                    missing.append(f"{path}:{call.lineno}: {texts[0][:70]!r}")
    return missing


def test_every_interface_text_in_the_code_has_a_portuguese_version():
    assert _untranslated() == []


# Functions that build a widget or a dialog before it shows; the language is
# applied to it when it shows.
_BUILDERS = re.compile(r"^(__init__|setup_ui|_setup|_build|_create|_make|_init|_add_|_show_)")
# Texts set on a message box or dialog before it opens, and texts without words.
_SET_BEFORE_SHOWING = {
    ("core/grid.py", "_show_grid_download_error"),
    ("core/shapefile.py", "_offer_reference_grid"),
    ("core/vrt_generator.py", "_confirm_non_cog_load"),
    ("widgets/dialogs.py", "_show_help_info"),
    ("bdc_loader_plugin.py", "initGui"),
}


def test_texts_set_while_a_window_is_open_follow_the_language():
    raw = []
    for path, tree in _sources():
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or _BUILDERS.match(fn.name):
                continue
            if (path, fn.name) in _SET_BEFORE_SHOWING:
                continue
            for call in ast.walk(fn):
                if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.args):
                    continue
                if call.func.attr not in {"setText", "setToolTip", "setTitle", "setPlaceholderText", "addAction"}:
                    continue
                text = _render(call.args[0], "1")
                if text is not None and _WORD.search(re.sub(r"<[^>]+>|&\w+;|\{.*?\}", " ", text)):
                    raw.append(f"{path}:{call.lineno} {fn.name}: {text[:60]!r}")
    assert raw == []


@pytest.mark.parametrize("missing_key", ["Download selected", "History cleared.", "Select at least one item."])
def test_removing_a_translation_is_noticed(missing_key, monkeypatch):
    monkeypatch.delitem(i18n.TEXTS, missing_key)
    assert any(repr(missing_key) in line for line in _untranslated())
