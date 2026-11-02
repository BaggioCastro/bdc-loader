#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""package_plugin.py — Build the distributable QGIS plugin ZIP.

Produces ``bdc_loader_plugin_v<VERSION>.zip`` containing a single top-level
``bdc_loader_plugin/`` folder, as QGIS's "Install from ZIP" expects. Only the
runtime plugin ships; the repository-root ``LICENSE`` is copied into it.

Excluded from the package:
  - ``tests/`` (unit suite) and ``__pycache__/`` directories;
  - ``logs/`` (runtime JSONL logs, regenerated per install) and any ``.jsonl``;
  - compiled Python (``.pyc``/``.pyo``/``.pyd``), archives and editor backups;
  - every file or folder whose name starts with a dot (``.gitignore``, ``.vscode/``).

Usage:
    python package_plugin.py            # write ZIP to the repo root
    python package_plugin.py -o DIR     # write ZIP into DIR
    python package_plugin.py --list     # print what would be packaged, no ZIP
"""

import argparse
import os
import re
import sys
import zipfile

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_NAME = "bdc_loader_plugin"
PLUGIN_DIR = os.path.join(REPO_DIR, PLUGIN_NAME)
VERSION_FILE = os.path.join(PLUGIN_DIR, "VERSION")
LICENSE_FILE = os.path.join(REPO_DIR, "LICENSE")
CHANGELOG_FILE = os.path.join(REPO_DIR, "docs", "CHANGELOG.md")

# Directory names excluded wherever they appear in the plugin tree, as are names starting with a dot.
EXCLUDE_DIRS = frozenset({"__pycache__", "tests", "logs"})
# Plugin-relative files the plugin never reads: the version source of bump_version.py
# and the command-line entry point of the bundled pystac-client.
EXCLUDE_FILES = frozenset({"VERSION", "lib/pystac_client/cli.py"})
# File suffixes excluded wherever they appear.
EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".pyd", ".jsonl", ".zip", ".swp", ".swo", ".bak")
CHANGELOG_BLOCK_RE = re.compile(
    r"^changelog=[^\r\n]*(?:(?:\r?\n[ \t]+[^\r\n]*)|(?:\r?\n(?=\r?$)))*",
    re.MULTILINE,
)
SECTION_HEADER_RE = re.compile(r"^\[[^\]\r\n]+\][ \t]*$", re.MULTILINE)


def should_include(rel_path):
    """Return whether a plugin-relative path belongs in the distributed package.

    rel_path is POSIX-style and relative to the plugin folder root (e.g.
    ``core/download.py`` or ``tests/test_download.py``). Directory components,
    the basename, and the suffix are each checked against the exclusion rules.
    """
    if rel_path in EXCLUDE_FILES:
        return False
    parts = rel_path.split("/")
    if any(part in EXCLUDE_DIRS or part.startswith(".") for part in parts[:-1]):
        return False
    name = parts[-1]
    if name.startswith("."):
        return False
    if os.path.splitext(name)[1].lower() in EXCLUDE_SUFFIXES:
        return False
    return True


def iter_package_files(plugin_dir=PLUGIN_DIR):
    """Yield (abs_path, arcname) for every file that ships, arcname prefixed with
    the plugin folder name so the ZIP extracts to ``bdc_loader_plugin/...``.

    Excluded directories are pruned during the walk, so their contents are never
    visited, and the output is sorted for a deterministic archive.
    """
    plugin_dir = os.path.abspath(plugin_dir)
    base = os.path.basename(plugin_dir.rstrip(os.sep))
    collected = []
    for dirpath, dirnames, filenames in os.walk(plugin_dir):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS and not d.startswith("."))
        for filename in filenames:
            abs_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(abs_path, plugin_dir).replace(os.sep, "/")
            if should_include(rel_path):
                collected.append((abs_path, f"{base}/{rel_path}"))
    if not os.path.isfile(LICENSE_FILE):
        raise FileNotFoundError(f"Required repository license not found: {LICENSE_FILE}")

    license_arc = f"{base}/LICENSE"
    collected = [(path, arc) for path, arc in collected if arc != license_arc]
    collected.append((LICENSE_FILE, license_arc))
    collected.sort(key=lambda pair: pair[1])
    yield from collected


def read_version():
    with open(VERSION_FILE, encoding="utf-8") as f:
        return f.read().strip()


def build_zip(output_dir=REPO_DIR, plugin_dir=PLUGIN_DIR, version=None):
    """Write the plugin ZIP into output_dir and return its path.

    metadata.txt inside the archive gets the changelog of ``version`` from
    docs/CHANGELOG.md; the source file is not modified.
    """
    version = version or read_version()
    output_path = os.path.join(output_dir, f"{PLUGIN_NAME}_v{version}.zip")
    metadata_arcname = f"{os.path.basename(os.path.abspath(plugin_dir))}/metadata.txt"
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for abs_path, arcname in iter_package_files(plugin_dir):
            if arcname == metadata_arcname:
                content = _get_clean_metadata(abs_path, version)
                zf.writestr(arcname, content)
            else:
                zf.write(abs_path, arcname)
    return output_path


# Ticket codes and source file names in parentheses, which mean nothing to a user.
_INTERNAL_CODE_RE = re.compile(r"\s*\((?:[A-Z]{2,5}-\d+|[^()]*\.py\b[^()]*)\)")
_MARKUP_RE = re.compile(r"\*\*|`|\[([^\]]+)\]\([^)]+\)")


def _section_entries(lines, heading):
    """The top-level bullets under ``heading`` (a ``## [...]`` line), each joined into one line."""
    try:
        start = next(i for i, line in enumerate(lines) if line.startswith(heading)) + 1
    except StopIteration:
        return None
    entries, subsection = [], None
    for line in lines[start:]:
        if line.startswith("## "):
            break
        if line.startswith("### "):
            subsection = line[4:].strip()
        elif line.startswith("- "):
            entries.append([subsection, line[2:].strip()])
        elif line.startswith("  ") and entries and line.strip():
            entries[-1][1] += " " + line.strip()
    return entries


def public_changelog(version, changelog_path=CHANGELOG_FILE):
    """The ``changelog=`` block of the ZIP: what the CHANGELOG adds in ``version``.

    It lists the first sentence of each "Added" entry of the section of
    ``version``, or of [Unreleased] while the version has none, and points to
    the CHANGELOG for the fixes and changes. Ticket codes and file names are dropped.
    """
    with open(changelog_path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    entries = _section_entries(lines, f"## [{version}]")
    if entries is None:
        entries = _section_entries(lines, "## [Unreleased]") or []
    block = ["changelog=", f"    {version}:"]
    for subsection, text in entries:
        if subsection != "Added":
            continue
        text = _INTERNAL_CODE_RE.sub("", _MARKUP_RE.sub(lambda m: m.group(1) or "", text))
        first = re.split(r"(?<=\.)\s", text, maxsplit=1)[0].rstrip(".")
        block.append(f"    - {first}.")
    block.append("    - Fixes and other changes: docs/CHANGELOG.md in the repository.")
    return "\n".join(block)


def _get_clean_metadata(abs_path, version, changelog_path=CHANGELOG_FILE):
    """Return metadata.txt content for the ZIP, with the changelog taken from docs/CHANGELOG.md."""
    with open(abs_path, encoding="utf-8") as f:
        content = f.read()

    clean_changelog = public_changelog(version, changelog_path)

    cleaned, replacements = CHANGELOG_BLOCK_RE.subn(clean_changelog, content, count=1)
    if replacements:
        return cleaned

    general_header = re.search(r"^\[general\][ \t]*$", content, re.MULTILINE)
    if general_header is None:
        raise ValueError("metadata.txt is missing the required [general] section")

    next_section = SECTION_HEADER_RE.search(content, general_header.end())
    insert_at = next_section.start() if next_section else len(content)
    prefix = content[:insert_at]
    separator = "" if not prefix or prefix.endswith(("\n", "\r")) else "\n"
    return prefix + separator + clean_changelog + "\n" + content[insert_at:]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the distributable BDC Loader plugin ZIP.")
    releases_dir = os.path.join(REPO_DIR, "releases")
    default_out = releases_dir if os.path.isdir(releases_dir) else REPO_DIR
    parser.add_argument("-o", "--output", default=default_out, help="directory for the ZIP (default: releases/)")
    parser.add_argument("--list", action="store_true", help="list packaged files instead of building the ZIP")
    args = parser.parse_args(argv)

    if args.list:
        for _abs, arcname in iter_package_files():
            print(arcname)
        return 0

    output_path = build_zip(args.output)
    count = sum(1 for _ in iter_package_files())
    print(f"Packaged {count} files -> {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
