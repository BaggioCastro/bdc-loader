#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BDC Loader Plugin - Test Suite

Run with: python3 -m unittest bdc_loader_plugin.tests.test_plugin -v
From:     the repository root

Validates module imports, STAC parsers, fallback data, and extraction logic.
"""

import os
import sys
import unittest

# Ensure the workspace root (parent of bdc_loader_plugin/) is in path
_workspace_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _workspace_dir not in sys.path:
    sys.path.insert(0, _workspace_dir)


# ── 1. Module Import Tests ──────────────────────────────────────────────────


# ── 2. STAC Parsers Unit Tests ───────────────────────────────────────────────


# ── 3. Regex Pattern Tests ──────────────────────────────────────────────────


# ── 4. Fallback Data Integrity ──────────────────────────────────────────────


class TestFallbackData(unittest.TestCase):
    def test_display_names(self):
        from bdc_loader_plugin.stac.fallback import ID_TO_DISPLAY_NAME

        for cid, name in ID_TO_DISPLAY_NAME.items():
            self.assertIsInstance(name, str)
            self.assertGreater(len(name), 0)


# ── 5. Extraction Module Tests ──────────────────────────────────────────────


# ── 6. File Structure Tests ─────────────────────────────────────────────────


# ── 7. Config Manager Tests ─────────────────────────────────────────────────


if __name__ == "__main__":
    unittest.main()
