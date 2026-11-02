"""UI strings must not depend on emoji fonts.

Characters outside the Basic Multilingual Plane (U+1F4CB clipboard, U+1F50D
magnifier, ...) render as empty boxes on systems without an emoji font, such as
the official qgis/qgis Docker images. Icons for those buttons come from
widgets/icons.py instead.
"""

import ast
import pathlib

_PLUGIN_DIR = pathlib.Path(__file__).resolve().parent.parent


def test_plugin_strings_have_no_characters_outside_the_bmp():
    offenders = []
    for path in sorted(_PLUGIN_DIR.rglob("*.py")):
        rel = path.relative_to(_PLUGIN_DIR)
        if rel.parts[0] in ("tests", "lib"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                wide = sorted({f"U+{ord(ch):05X}" for ch in node.value if ord(ch) > 0xFFFF})
                if wide:
                    offenders.append(f"{rel}:{node.lineno} {' '.join(wide)}")

    assert offenders == []
