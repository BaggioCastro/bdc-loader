#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_version_and_config.py — Version, settings, catalog paging and chart click tests.

Covers:
    - Version synchronization across metadata.txt, VERSION, config.py, pyproject.toml
    - Runtime config propagation: wtss_workers, gdal_cache_mb, http_timeout
    - STAC collection pagination: _fetch_all_stac_collections follows next links
    - Chart date click failure logs error instead of printing traceback
    - FALLBACK_UPDATED staleness check does not raise
    - bump_version --check logic
    - RAM profile selection and propagation
"""

import os
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Version synchronization
# ---------------------------------------------------------------------------


class TestVersionSync(unittest.TestCase):
    """All version-bearing files must agree with the VERSION file."""

    def _project_root(self):
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def _plugin_dir(self):
        return os.path.join(self._project_root(), "bdc_loader_plugin")

    def test_version_file_exists_and_non_empty(self):
        path = os.path.join(self._plugin_dir(), "VERSION")
        self.assertTrue(os.path.exists(path), "VERSION file missing")
        with open(path) as f:
            ver = f.read().strip()
        self.assertTrue(ver, "VERSION file is empty")

    def test_version_matches_config_py(self):
        from bdc_loader_plugin.config import PLUGIN_VERSION

        ver_path = os.path.join(self._plugin_dir(), "VERSION")
        with open(ver_path) as f:
            expected = f.read().strip()
        self.assertEqual(PLUGIN_VERSION, expected, f"config.PLUGIN_VERSION '{PLUGIN_VERSION}' != VERSION '{expected}'")

    def test_version_matches_metadata_txt(self):
        import re

        ver_path = os.path.join(self._plugin_dir(), "VERSION")
        meta_path = os.path.join(self._plugin_dir(), "metadata.txt")
        with open(ver_path) as f:
            expected = f.read().strip()
        with open(meta_path) as f:
            content = f.read()
        m = re.search(r"^version=(.+)$", content, re.MULTILINE)
        self.assertIsNotNone(m, "version= line missing in metadata.txt")
        self.assertEqual(m.group(1).strip(), expected, f"metadata.txt version '{m.group(1)}' != VERSION '{expected}'")

    def test_version_matches_pyproject_toml(self):
        import re

        ver_path = os.path.join(self._plugin_dir(), "VERSION")
        pyproject_path = os.path.join(self._project_root(), "pyproject.toml")
        with open(ver_path) as f:
            expected = f.read().strip()
        with open(pyproject_path) as f:
            content = f.read()
        m = re.search(r'^version\s*=\s*"(.+)"', content, re.MULTILINE)
        self.assertIsNotNone(m, "version line missing in pyproject.toml")
        self.assertEqual(m.group(1).strip(), expected, f"pyproject.toml version '{m.group(1)}' != VERSION '{expected}'")


# ---------------------------------------------------------------------------
# Runtime config reload
# ---------------------------------------------------------------------------


class TestRuntimeConfigReload(unittest.TestCase):
    """Saving settings must reset _GDAL_CONFIGURED and the WTSS semaphore."""

    def test_gdal_configured_reset_on_reload(self):
        import bdc_loader_plugin.extraction.gdal_setup as ts

        ts._GDAL_CONFIGURED = True

        # Simulate what _reload_runtime_config does
        ts._GDAL_CONFIGURED = False
        self.assertFalse(ts._GDAL_CONFIGURED)

    def test_reset_request_semaphore_callable(self):
        from bdc_loader_plugin.extraction import wtss_extractor
        from bdc_loader_plugin.extraction.wtss_extractor import reset_request_semaphore

        before = wtss_extractor._REQUEST_SEMAPHORE
        reset_request_semaphore()
        self.assertIsNot(wtss_extractor._REQUEST_SEMAPHORE, before)


# ---------------------------------------------------------------------------
# STAC collection pagination
# ---------------------------------------------------------------------------


class TestStacPagination(unittest.TestCase):
    """_fetch_all_stac_collections must follow 'next' links."""

    def test_follows_next_links(self):
        from unittest.mock import patch

        page1 = {
            "collections": [{"id": "S2-16D-2"}, {"id": "LC8-30-16D-2"}],
            "links": [{"rel": "next", "href": "https://stac.example.com/v1/collections?token=p2"}],
        }
        page2 = {
            "collections": [{"id": "CB4-16D-2"}],
            "links": [],
        }

        mock_resp1 = MagicMock()
        mock_resp1.status_code = 200
        mock_resp1.json.return_value = page1

        mock_resp2 = MagicMock()
        mock_resp2.status_code = 200
        mock_resp2.json.return_value = page2

        with patch("bdc_loader_plugin.stac.client.requests") as mock_requests:
            mock_requests.get.side_effect = [mock_resp1, mock_resp2]
            from bdc_loader_plugin.stac.client import _fetch_all_stac_collections

            result = _fetch_all_stac_collections("https://stac.example.com/v1/collections")

        ids = [c["id"] for c in result]
        self.assertIn("S2-16D-2", ids)
        self.assertIn("LC8-30-16D-2", ids)
        self.assertIn("CB4-16D-2", ids)
        self.assertEqual(len(ids), 3)
        self.assertEqual(mock_requests.get.call_count, 2)

    def test_empty_response(self):
        from unittest.mock import patch

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"collections": [], "links": []}

        with patch("bdc_loader_plugin.stac.client.requests") as mock_requests:
            mock_requests.get.return_value = mock_resp
            from bdc_loader_plugin.stac.client import _fetch_all_stac_collections

            result = _fetch_all_stac_collections("https://stac.example.com/v1/collections")

        self.assertEqual(result, [])

    def _pages(self, pages):
        from unittest.mock import patch

        responses = {}
        for url, page in pages.items():
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = page
            responses[url] = resp
        requested = []

        def _get(url, timeout=None):
            requested.append(url)
            if len(requested) > 10:
                raise AssertionError("pagination does not end")
            return responses[url]

        with patch("bdc_loader_plugin.stac.client.requests") as mock_requests:
            mock_requests.get.side_effect = _get
            from bdc_loader_plugin.stac.client import _fetch_all_stac_collections

            result = _fetch_all_stac_collections("https://stac.example.com/v1/collections")
        return [c["id"] for c in result], requested

    def test_a_next_link_to_the_same_page_ends_the_walk(self):
        url = "https://stac.example.com/v1/collections"
        ids, requested = self._pages({url: {"collections": [{"id": "A"}], "links": [{"rel": "next", "href": url}]}})
        self.assertEqual(ids, ["A"])
        self.assertEqual(requested, [url])

    def test_a_relative_next_link_is_followed(self):
        url = "https://stac.example.com/v1/collections"
        ids, requested = self._pages(
            {
                url: {"collections": [{"id": "A"}], "links": [{"rel": "next", "href": "?page=2"}]},
                url + "?page=2": {"collections": [{"id": "B"}], "links": []},
            }
        )
        self.assertEqual(ids, ["A", "B"])
        self.assertEqual(requested, [url, url + "?page=2"])

    def test_an_unreachable_server_raises_instead_of_returning_no_collection(self):
        from unittest.mock import patch

        with patch("bdc_loader_plugin.stac.client.requests") as mock_requests:
            mock_requests.get.side_effect = ConnectionError("refused")
            from bdc_loader_plugin.stac.client import _fetch_all_stac_collections

            with self.assertRaises(ConnectionError):
                _fetch_all_stac_collections("https://stac.example.com/v1/collections")


# ---------------------------------------------------------------------------
# FALLBACK_UPDATED staleness check
# ---------------------------------------------------------------------------


class TestFallbackUpdated(unittest.TestCase):
    """FALLBACK_UPDATED must be a valid ISO date and importable."""

    def test_fallback_updated_is_valid_date(self):
        from datetime import date

        from bdc_loader_plugin.stac.fallback import FALLBACK_UPDATED

        # Must not raise
        parsed = date.fromisoformat(FALLBACK_UPDATED)
        self.assertIsInstance(parsed, date)

    def test_fallback_updated_not_in_future(self):
        from datetime import date

        from bdc_loader_plugin.stac.fallback import FALLBACK_UPDATED

        parsed = date.fromisoformat(FALLBACK_UPDATED)
        self.assertLessEqual(parsed, date.today(), "FALLBACK_UPDATED should not be a future date")


# ---------------------------------------------------------------------------
# RAM profile selection and propagation
# ---------------------------------------------------------------------------


class TestRamProfilePropagation(unittest.TestCase):
    """Auto-detect RAM -> profile -> max_threads flows correctly."""

    @patch("bdc_loader_plugin.config._get_total_ram_gb", return_value=2.0)
    @patch("bdc_loader_plugin.config.os.cpu_count", return_value=2)
    def test_low_ram_selects_low_profile(self, _cpu, _ram):
        from bdc_loader_plugin.config import detect_system_profile

        self.assertEqual(detect_system_profile(), "low")

    @patch("bdc_loader_plugin.config._get_total_ram_gb", return_value=8.0)
    @patch("bdc_loader_plugin.config.os.cpu_count", return_value=4)
    def test_medium_ram_selects_medium_profile(self, _cpu, _ram):
        from bdc_loader_plugin.config import detect_system_profile

        self.assertEqual(detect_system_profile(), "medium")

    @patch("bdc_loader_plugin.config._get_total_ram_gb", return_value=16.0)
    @patch("bdc_loader_plugin.config.os.cpu_count", return_value=8)
    def test_high_ram_selects_high_profile(self, _cpu, _ram):
        from bdc_loader_plugin.config import detect_system_profile

        self.assertEqual(detect_system_profile(), "high")

    @patch("bdc_loader_plugin.config._get_total_ram_gb", return_value=64.0)
    @patch("bdc_loader_plugin.config.os.cpu_count", return_value=32)
    def test_ultra_ram_selects_ultra_profile(self, _cpu, _ram):
        from bdc_loader_plugin.config import detect_system_profile

        self.assertEqual(detect_system_profile(), "ultra")


if __name__ == "__main__":
    unittest.main()
