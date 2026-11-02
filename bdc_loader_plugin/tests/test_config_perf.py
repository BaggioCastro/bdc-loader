#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_config_perf.py — Tests for config.py performance detection and configuration.

Covers: detect_system_profile, _get_total_ram_gb, get_performance_config,
        PERFORMANCE_PROFILES, PERF_LIMITS, ConfigManager performance methods.

Run: python3 -m pytest bdc_loader_plugin/tests/test_config_perf.py -v
"""

import unittest
from unittest.mock import MagicMock, patch


class TestDetectSystemProfile(unittest.TestCase):
    """Tests for detect_system_profile based on CPU/RAM detection."""

    def test_ultra_profile(self):
        from bdc_loader_plugin.config import detect_system_profile

        with (
            patch("bdc_loader_plugin.config.os.cpu_count", return_value=32),
            patch("bdc_loader_plugin.config._get_total_ram_gb", return_value=64.0),
        ):
            self.assertEqual(detect_system_profile(), "ultra")

    def test_high_profile(self):
        from bdc_loader_plugin.config import detect_system_profile

        with (
            patch("bdc_loader_plugin.config.os.cpu_count", return_value=8),
            patch("bdc_loader_plugin.config._get_total_ram_gb", return_value=16.0),
        ):
            self.assertEqual(detect_system_profile(), "high")

    def test_medium_profile(self):
        from bdc_loader_plugin.config import detect_system_profile

        with (
            patch("bdc_loader_plugin.config.os.cpu_count", return_value=4),
            patch("bdc_loader_plugin.config._get_total_ram_gb", return_value=4.0),
        ):
            self.assertEqual(detect_system_profile(), "medium")

    def test_low_profile(self):
        from bdc_loader_plugin.config import detect_system_profile

        with (
            patch("bdc_loader_plugin.config.os.cpu_count", return_value=2),
            patch("bdc_loader_plugin.config._get_total_ram_gb", return_value=2.0),
        ):
            self.assertEqual(detect_system_profile(), "low")

    def test_none_cpu_defaults_low(self):
        from bdc_loader_plugin.config import detect_system_profile

        with (
            patch("bdc_loader_plugin.config.os.cpu_count", return_value=None),
            patch("bdc_loader_plugin.config._get_total_ram_gb", return_value=2.0),
        ):
            self.assertEqual(detect_system_profile(), "low")

    def test_boundary_16_cores_32gb_is_ultra(self):
        from bdc_loader_plugin.config import detect_system_profile

        with (
            patch("bdc_loader_plugin.config.os.cpu_count", return_value=16),
            patch("bdc_loader_plugin.config._get_total_ram_gb", return_value=32.0),
        ):
            self.assertEqual(detect_system_profile(), "ultra")

    def test_boundary_high_cpu_low_ram(self):
        """16 cores but only 4GB RAM -> medium (RAM is the bottleneck)."""
        from bdc_loader_plugin.config import detect_system_profile

        with (
            patch("bdc_loader_plugin.config.os.cpu_count", return_value=16),
            patch("bdc_loader_plugin.config._get_total_ram_gb", return_value=4.0),
        ):
            self.assertEqual(detect_system_profile(), "medium")


class TestGetTotalRamGb(unittest.TestCase):
    """Tests for _get_total_ram_gb with various fallback paths."""

    def test_psutil_path(self):
        from bdc_loader_plugin.config import _read_total_ram_gb

        mock_psutil = MagicMock()
        mock_psutil.virtual_memory.return_value.total = 16 * (1024**3)
        with patch.dict("sys.modules", {"psutil": mock_psutil}):
            result = _read_total_ram_gb()
        self.assertAlmostEqual(result, 16.0, places=0)

    def _ram_on(self, platform, **patches):
        import bdc_loader_plugin.config as config

        with patch.dict("sys.modules", {"psutil": None}), patch.object(config.sys, "platform", platform):
            with patch.multiple(config, **patches) if patches else patch.dict({}):
                return config._read_total_ram_gb()

    def test_linux_reads_proc_meminfo(self):
        from unittest.mock import mock_open

        meminfo = "MemTotal:       8388608 kB\nMemFree:        1234567 kB\n"
        with patch("builtins.open", mock_open(read_data=meminfo)):
            self.assertEqual(self._ram_on("linux"), 8.0)

    def test_windows_asks_the_kernel(self):
        self.assertEqual(self._ram_on("win32", _windows_ram_bytes=lambda: 16 * 1024**3), 16.0)

    def test_macos_asks_sysctl(self):
        with patch("subprocess.check_output", return_value=str(32 * 1024**3)):
            self.assertEqual(self._ram_on("darwin"), 32.0)

    def test_all_sources_failing_gives_the_conservative_default(self):
        with patch("builtins.open", side_effect=OSError("no /proc")):
            self.assertEqual(self._ram_on("linux"), 4.0)

    def test_ram_is_read_once_per_session(self):
        import bdc_loader_plugin.config as config

        config._get_total_ram_gb.cache_clear()
        self.addCleanup(config._get_total_ram_gb.cache_clear)
        with patch.object(config, "_read_total_ram_gb", return_value=32.0) as read:
            for _ in range(100):
                config.get_performance_config()
        self.assertEqual(read.call_count, 1)


class TestPerformanceProfiles(unittest.TestCase):
    """Tests for PERFORMANCE_PROFILES and PERF_LIMITS constants."""

    def test_all_profiles_exist(self):
        from bdc_loader_plugin.config import PERFORMANCE_PROFILES

        self.assertIn("low", PERFORMANCE_PROFILES)
        self.assertIn("medium", PERFORMANCE_PROFILES)
        self.assertIn("high", PERFORMANCE_PROFILES)
        self.assertIn("ultra", PERFORMANCE_PROFILES)

    def test_all_profiles_have_required_keys(self):
        from bdc_loader_plugin.config import PERFORMANCE_PROFILES

        required_keys = {"label", "max_threads", "wtss_workers", "gdal_cache_mb", "http_timeout"}
        for profile_name, profile in PERFORMANCE_PROFILES.items():
            self.assertTrue(required_keys.issubset(profile.keys()), f"Profile '{profile_name}' is missing keys")

    def test_profiles_monotonically_increase(self):
        from bdc_loader_plugin.config import PERFORMANCE_PROFILES

        order = ["low", "medium", "high", "ultra"]
        for i in range(len(order) - 1):
            p1 = PERFORMANCE_PROFILES[order[i]]
            p2 = PERFORMANCE_PROFILES[order[i + 1]]
            self.assertLessEqual(
                p1["max_threads"], p2["max_threads"], f"max_threads should increase from {order[i]} to {order[i + 1]}"
            )
            self.assertLessEqual(p1["wtss_workers"], p2["wtss_workers"])

    def test_perf_limits_keys_match_profiles(self):
        from bdc_loader_plugin.config import PERF_LIMITS, PERFORMANCE_PROFILES

        profile = PERFORMANCE_PROFILES["medium"]
        for key in PERF_LIMITS:
            self.assertIn(key, profile, f"PERF_LIMITS key '{key}' not in profile")

    def test_profile_values_within_limits(self):
        from bdc_loader_plugin.config import PERF_LIMITS, PERFORMANCE_PROFILES

        for pname, profile in PERFORMANCE_PROFILES.items():
            for key, (lo, hi) in PERF_LIMITS.items():
                val = profile[key]
                self.assertGreaterEqual(val, lo, f"{pname}.{key}={val} below limit {lo}")
                self.assertLessEqual(val, hi, f"{pname}.{key}={val} above limit {hi}")


class TestGetPerformanceConfig(unittest.TestCase):
    """Tests for get_performance_config with mocked QgsSettings."""

    def test_auto_profile(self):
        from bdc_loader_plugin.config import get_performance_config

        settings = MagicMock()
        settings.value = MagicMock(
            side_effect=lambda key, default=None, type=None: {
                "bdc_loader/perf_profile": "auto",
            }.get(key, default if default is not None else None)
        )

        with (
            patch("bdc_loader_plugin.config.QgsSettings", return_value=settings),
            patch("bdc_loader_plugin.config.detect_system_profile", return_value="medium"),
        ):
            result = get_performance_config()

        self.assertEqual(result["max_threads"], 10)
        self.assertEqual(result["wtss_workers"], 3)
        self.assertNotIn("label", result)

    def test_explicit_profile(self):
        from bdc_loader_plugin.config import get_performance_config

        settings = MagicMock()
        settings.value = MagicMock(
            side_effect=lambda key, default=None, type=None: {
                "bdc_loader/perf_profile": "ultra",
            }.get(key, default if default is not None else None)
        )

        with patch("bdc_loader_plugin.config.QgsSettings", return_value=settings):
            result = get_performance_config()

        self.assertEqual(result["max_threads"], 24)
        self.assertEqual(result["wtss_workers"], 5)

    def test_user_overrides_clamped(self):
        from bdc_loader_plugin.config import get_performance_config

        def mock_settings_value(key, default=None, type=None):
            vals = {
                "bdc_loader/perf_profile": "low",
                "bdc_loader/perf_max_threads": 999,  # Above limit
                "bdc_loader/perf_wtss_workers": 0,  # Below limit
            }
            return vals.get(key, default if default is not None else None)

        settings = MagicMock()
        settings.value = MagicMock(side_effect=mock_settings_value)

        with patch("bdc_loader_plugin.config.QgsSettings", return_value=settings):
            result = get_performance_config()

        self.assertEqual(result["max_threads"], 32)  # clamped to max
        self.assertEqual(result["wtss_workers"], 1)  # clamped to min

    def test_unknown_profile_falls_back_to_medium(self):
        from bdc_loader_plugin.config import get_performance_config

        settings = MagicMock()
        settings.value = MagicMock(
            side_effect=lambda key, default=None, type=None: {
                "bdc_loader/perf_profile": "nonexistent",
            }.get(key, default if default is not None else None)
        )

        with patch("bdc_loader_plugin.config.QgsSettings", return_value=settings):
            result = get_performance_config()

        self.assertEqual(result["max_threads"], 10)  # medium defaults


if __name__ == "__main__":
    unittest.main()
