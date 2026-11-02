#!/usr/bin/env python3
"""
bump_version.py — Single-source version bumper for BDC Loader Plugin.

Reads VERSION file and propagates the version string to:
  - bdc_loader_plugin/metadata.txt  (version=...)
  - bdc_loader_plugin/config.py     (PLUGIN_VERSION = ...)
  - pyproject.toml                  (version = ...)

Usage:
    python bump_version.py              # show current version
    python bump_version.py 1.1.0        # set version to 1.1.0
    python bump_version.py --patch      # 1.0.0 -> 1.0.1
    python bump_version.py --minor      # 1.0.0 -> 1.1.0
    python bump_version.py --major      # 1.0.0 -> 2.0.0
    python bump_version.py --check      # verify all targets match VERSION
"""

import os
import re
import sys

PLUGIN_DIR = os.path.join(os.path.dirname(__file__), "bdc_loader_plugin")
VERSION_FILE = os.path.join(PLUGIN_DIR, "VERSION")
METADATA_FILE = os.path.join(PLUGIN_DIR, "metadata.txt")
CONFIG_FILE = os.path.join(PLUGIN_DIR, "config.py")
PYPROJECT_FILE = os.path.join(os.path.dirname(__file__), "pyproject.toml")

# README.md is not a target: it documents the ZIP name as the literal
# placeholder bdc_loader_plugin_v<VERSION>.zip, which stays correct on its own.
# Double quotes in the config.py replacement are required — CI runs
# `ruff format --check`, which rewrites single-quoted strings.
TARGETS = {
    METADATA_FILE: (
        re.compile(r"^version=.*$", re.MULTILINE),
        lambda v: f"version={v}",
    ),
    CONFIG_FILE: (
        re.compile(r"^PLUGIN_VERSION\s*=\s*['\"].*['\"]", re.MULTILINE),
        lambda v: f'PLUGIN_VERSION = "{v}"',
    ),
    PYPROJECT_FILE: (
        re.compile(r'^version\s*=\s*".*"', re.MULTILINE),
        lambda v: f'version = "{v}"',
    ),
}


def read_version():
    with open(VERSION_FILE) as f:
        return f.read().strip()


def write_version(ver):
    with open(VERSION_FILE, "w") as f:
        f.write(ver + "\n")


def bump(current, part):
    parts = current.split(".")
    while len(parts) < 3:
        parts.append("0")
    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
    if part == "--major":
        return f"{major + 1}.0.0"
    elif part == "--minor":
        return f"{major}.{minor + 1}.0"
    elif part == "--patch":
        return f"{major}.{minor}.{patch + 1}"
    return current


def propagate(ver):
    updated = []
    for filepath, (pattern, replacement_fn) in TARGETS.items():
        if not os.path.exists(filepath):
            print(f"  SKIP (not found): {filepath}")
            continue
        with open(filepath, encoding="utf-8") as f:
            content = f.read()
        new_content, n = pattern.subn(replacement_fn(ver), content, count=1)
        if n > 0:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(new_content)
            updated.append(os.path.relpath(filepath))
            print(f"  OK: {os.path.relpath(filepath)}")
        else:
            print(f"  SKIP (pattern not found): {os.path.relpath(filepath)}")
    return updated


def main():
    current = read_version()

    if len(sys.argv) < 2:
        print(f"Current version: {current}")
        print("\nUsage:")
        print(f"  python {sys.argv[0]} 1.1.0        # set explicit version")
        print(f"  python {sys.argv[0]} --patch      # {current} -> patch bump")
        print(f"  python {sys.argv[0]} --minor      # {current} -> minor bump")
        print(f"  python {sys.argv[0]} --major      # {current} -> major bump")
        print(f"  python {sys.argv[0]} --check      # verify all targets match VERSION")
        return

    arg = sys.argv[1]
    if arg == "--check":
        _check_consistency(current)
        return
    if arg.startswith("--"):
        new_ver = bump(current, arg)
    else:
        new_ver = arg

    print(f"Bumping version: {current} -> {new_ver}\n")
    write_version(new_ver)
    propagate(new_ver)
    print(f"\nVersion {new_ver} set. Now commit and tag:")
    print(f'  git add -A && git commit -m "Release v{new_ver}"')
    print(f"  git tag v{new_ver} && git push origin main --tags")


def _check_consistency(expected):
    """Verify all target files contain the expected version string."""
    ok = True
    for filepath, (pattern, replacement_fn) in TARGETS.items():
        if not os.path.exists(filepath):
            print(f"  MISSING: {filepath}")
            ok = False
            continue
        with open(filepath, encoding="utf-8") as f:
            content = f.read()
        match = pattern.search(content)
        if match:
            found = match.group(0)
            expected_str = replacement_fn(expected)
            if found == expected_str:
                print(f"  OK: {os.path.relpath(filepath)} — {found}")
            else:
                print(f"  MISMATCH: {os.path.relpath(filepath)}")
                print(f"    expected: {expected_str}")
                print(f"    found:    {found}")
                ok = False
        else:
            print(f"  NOT FOUND: version pattern missing in {os.path.relpath(filepath)}")
            ok = False
    if ok:
        print(f"\nAll targets consistent at version {expected}.")
    else:
        print(f"\nVersion inconsistency detected! Run: python {sys.argv[0]} {expected}")
        sys.exit(1)


if __name__ == "__main__":
    main()
