#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_package.py — Check a release ZIP against the rules of plugins.qgis.org.

Checks the structure that the QGIS plugin repository validates on upload: one
top-level folder named with ASCII letters, digits, ``_`` or ``-``, not starting
with a digit; ``__init__.py``, ``metadata.txt`` and ``LICENSE`` in it; the
required metadata fields; links to the repository, tracker and home page; no
binaries, no hidden files or ``__pycache__``; at most 25 MB. Bandit and
detect-secrets, which the repository also runs, are run by the CI workflow.

Usage:
    python check_package.py releases/bdc_loader_plugin_v1.0.0.zip
"""

import configparser
import os
import re
import sys
import zipfile

MAX_BYTES = 25 * 1024 * 1024
FOLDER_RE = re.compile(r"^[A-Za-z_-][A-Za-z0-9_-]*$")
REQUIRED_FIELDS = (
    "name",
    "qgisMinimumVersion",
    "description",
    "about",
    "version",
    "author",
    "email",
    "repository",
    "tracker",
    "homepage",
)
LINK_FIELDS = ("repository", "tracker", "homepage")
BINARY_SUFFIXES = (".so", ".dll", ".dylib", ".exe", ".pyd", ".pyc", ".pyo", ".bin", ".zip", ".whl")


def check_zip(path):
    """Return the list of problems found in the ZIP at ``path`` (empty when it passes)."""
    problems = []
    if os.path.getsize(path) > MAX_BYTES:
        problems.append(f"the ZIP has {os.path.getsize(path)} bytes, above the 25 MB limit")
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        tops = {n.split("/", 1)[0] for n in names}
        if len(tops) != 1 or any("/" not in n for n in names):
            return problems + [f"the ZIP must hold one top-level folder, found {sorted(tops)}"]
        folder = tops.pop()
        if not FOLDER_RE.match(folder):
            problems.append(
                f"folder name {folder!r} must use ASCII letters, digits, '_' or '-' and not start with a digit"
            )
        for required in ("__init__.py", "metadata.txt", "LICENSE"):
            if f"{folder}/{required}" not in names:
                problems.append(f"{required} is missing from {folder}/")
        for name in names:
            parts = name.split("/")
            if any(p.startswith(".") or p == "__pycache__" for p in parts):
                problems.append(f"hidden or cache file: {name}")
            elif name.lower().endswith(BINARY_SUFFIXES):
                problems.append(f"binary file: {name}")
        if f"{folder}/metadata.txt" in names:
            problems += check_metadata(zf.read(f"{folder}/metadata.txt").decode("utf-8"))
    return problems


def check_metadata(text):
    """Return the problems of a metadata.txt content."""
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    try:
        parser.read_string(text)
    except configparser.Error as exc:
        return [f"metadata.txt cannot be read: {exc}"]
    if not parser.has_section("general"):
        return ["metadata.txt has no [general] section"]
    general = parser["general"]
    problems = [f"metadata.txt lacks {field}" for field in REQUIRED_FIELDS if not general.get(field, "").strip()]
    for field in LINK_FIELDS:
        value = general.get(field, "").strip()
        if value and not value.startswith("https://"):
            problems.append(f"metadata.txt {field} is not an https link: {value}")
    if "\n" in general.get("description", "").strip():
        problems.append("metadata.txt description must be one line")
    if not re.fullmatch(r"\d+\.\d+\.\d+", general.get("version", "").strip()):
        problems.append("metadata.txt version must be MAJOR.MINOR.PATCH")
    return problems


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__.strip().splitlines()[-1].strip())
        return 2
    problems = check_zip(argv[0])
    for problem in problems:
        print(f"FAIL {problem}")
    if not problems:
        print(f"OK   {argv[0]} follows the plugins.qgis.org package rules")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
