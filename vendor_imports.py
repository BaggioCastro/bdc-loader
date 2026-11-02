#!/usr/bin/env python3
"""Rewrite the absolute imports of the vendored packages in lib/ as relative ones.

The plugin imports its copies of pystac and pystac_client as
``bdc_loader_plugin.lib.pystac`` and ``bdc_loader_plugin.lib.pystac_client``,
without touching ``sys.path``, so another plugin's pystac and this one never
replace each other in ``sys.modules``. Run it after copying a new release of a
vendored package into lib/; running it again changes nothing.

Usage:
    python vendor_imports.py            # rewrite in place
    python vendor_imports.py --check    # exit 1 if a file still needs it
"""

import argparse
import ast
import os
import re
import sys

LIB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bdc_loader_plugin", "lib")
VENDORED = ("pystac", "pystac_client")
NOTICE = "# Modified for BDC Loader: imports of pystac and pystac_client made relative (vendor_imports.py)."

_NAMES = "|".join(VENDORED)
_IMPORT_TOP = re.compile(rf"^(\s*)import ({_NAMES})\s*$")
_IMPORT_SUB = re.compile(rf"^(\s*)import ({_NAMES})\.([\w.]+)\s*$")
_FROM = re.compile(rf"^(\s*)from ({_NAMES})(\.[\w.]+)?( import .*)$")


def _rewrite_line(line, dots):
    m = _IMPORT_TOP.match(line)
    if m:
        indent, name = m.groups()
        return [f"{indent}from {dots} import {name}"]
    m = _IMPORT_SUB.match(line)
    if m:
        indent, name, sub = m.groups()
        parent, _, leaf = f"{name}.{sub}".rpartition(".")
        # Loading the submodule sets it as an attribute of its parent, which
        # is how the vendored code reads it (``pystac.validation.validate``).
        return [
            f"{indent}from {dots} import {name}",
            f"{indent}from {dots}{parent} import {leaf} as _vendored_{leaf}  # noqa: F401",
        ]
    m = _FROM.match(line)
    if m:
        indent, name, sub, rest = m.groups()
        return [f"{indent}from {dots}{name}{sub or ''}{rest}"]
    return [line]


def rewrite_file(path, lib_dir=LIB_DIR):
    """Return the rewritten source of ``path``, a module under ``lib_dir``.

    A file whose imports change gets ``NOTICE`` as its first line, as the
    Apache License 2.0 of the vendored packages asks of modified files.
    """
    depth = len(os.path.relpath(os.path.dirname(path), lib_dir).split(os.sep))
    dots = "." * (depth + 1)
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    out = []
    for line in lines:
        out.extend(_rewrite_line(line, dots))
    if out != lines and out[0] != NOTICE:
        out.insert(0, NOTICE)
    source = "\n".join(out)
    ast.parse(source, path)
    return source


def vendored_files(lib_dir=LIB_DIR):
    for name in VENDORED:
        for root, dirs, files in os.walk(os.path.join(lib_dir, name)):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in sorted(files):
                if f.endswith(".py"):
                    yield os.path.join(root, f)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="only report files that still need rewriting")
    args = parser.parse_args()
    pending = []
    for path in vendored_files():
        with open(path, encoding="utf-8") as f:
            before = f.read()
        after = rewrite_file(path)
        if after != before:
            pending.append(os.path.relpath(path, LIB_DIR))
            if not args.check:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(after)
    verb = "need rewriting" if args.check else "rewritten"
    print(f"{len(pending)} files {verb}")
    for rel in pending:
        print(f"  {rel}")
    return 1 if args.check and pending else 0


if __name__ == "__main__":
    sys.exit(main())
