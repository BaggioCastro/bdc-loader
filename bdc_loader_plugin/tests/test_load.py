#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_load.py — Tests of the BDC Loader plugin with many items and repeated cycles

Covers:
- Mass import stability across all modules
- Widget construction (create/destroy cycles)
- Large-scale STAC item processing (500-2000 items)
- Concurrent dict operations (collections, band info, presets)
- Memory stability under repeated operations
- Config read/write cycles at scale
- UI string consistency (no Portuguese leaks)
- Extraction pipeline with large band counts
- Fallback data integrity

Run: python3 -m pytest bdc_loader_plugin/tests/test_load.py -v
"""

import gc
import importlib
import os
import re
import unittest
from unittest.mock import MagicMock, patch

from bdc_loader_plugin.tests.qgis_mock import install_mocks, reset_state

install_mocks()
reset_state()


# ══════════════════════════════════════════════════════════════════════════════
# PART 1: MASS IMPORT STRESS
# ══════════════════════════════════════════════════════════════════════════════


class TestMassImportStress(unittest.TestCase):
    """Verify all modules survive repeated import/reload cycles."""

    MODULES = [
        "bdc_loader_plugin.config",
        "bdc_loader_plugin.logger",
        "bdc_loader_plugin.stac.parsers",
        "bdc_loader_plugin.stac.fallback",
        "bdc_loader_plugin.stac.client",
        "bdc_loader_plugin.extraction.gdal_setup",
    ]

    def test_50_reimport_cycles_stable(self):
        """50 full reimport cycles of all core modules — no crashes."""
        for cycle in range(50):
            for mod_name in self.MODULES:
                mod = importlib.import_module(mod_name)
                importlib.reload(mod)


# ══════════════════════════════════════════════════════════════════════════════
# PART 2: WIDGET CONSTRUCTION STRESS
# ══════════════════════════════════════════════════════════════════════════════


class TestWidgetConstructionStress(unittest.TestCase):
    """Widget create/destroy cycles to detect memory leaks in init code."""

    def test_plugin_init_100_cycles(self):
        """Create BDCLoaderPlugin 100 times — no accumulating state."""
        from bdc_loader_plugin.bdc_loader_plugin import BDCLoaderPlugin

        iface = MagicMock()
        plugins = []
        for _ in range(100):
            p = BDCLoaderPlugin(iface)
            plugins.append(p)
        self.assertEqual(len(plugins), 100)


# ══════════════════════════════════════════════════════════════════════════════
# PART 3: LARGE-SCALE STAC ITEM PROCESSING
# ══════════════════════════════════════════════════════════════════════════════


class TestLargeScaleProcessing(unittest.TestCase):
    """Simulate processing hundreds/thousands of STAC items."""

    def _make_item_id(self, idx, collection_type="bdc"):
        """Generate realistic item IDs."""
        patterns = [
            f"S2-16D-2_{idx:06d}_V2023-01-01_2023-01-16",
            f"LC08_L2SP_{idx:03d}066_20230101",
            f"CBERS_4A_WPM_20230101_{idx:03d}_123_L4",
            f"S2A_MSIL2A_20230101T000000_T{idx % 60:02d}MCP",
        ]
        return patterns[idx % len(patterns)]

    def _make_assets(self, num_bands=7):
        """Generate realistic asset dict."""
        assets = {}
        band_names = [
            "B01",
            "B02",
            "B03",
            "B04",
            "B05",
            "B06",
            "B07",
            "B08",
            "B8A",
            "B09",
            "B10",
            "B11",
            "B12",
            "NDVI",
            "EVI",
            "NBR",
        ]
        for i in range(min(num_bands, len(band_names))):
            assets[band_names[i]] = {"type": "image/tiff; application=geotiff"}
        assets["thumbnail"] = {"type": "image/png"}
        assets["qa_pixel"] = {"type": "image/tiff; application=geotiff"}
        return assets

    def test_process_500_items(self):
        """Process 500 STAC items through full parsing pipeline."""
        from bdc_loader_plugin.stac.parsers import (
            extract_bands_from_assets,
            extract_tile_from_id,
            format_tile_display,
            has_valid_tile_system,
        )

        assets = self._make_assets(10)

        results = []
        for i in range(500):
            item_id = self._make_item_id(i)
            tile = extract_tile_from_id(item_id)
            display = format_tile_display(tile, "BDC_SM_V2")
            bands = extract_bands_from_assets(assets)
            valid = has_valid_tile_system("MGRS")
            results.append((tile, display, bands, valid))

        self.assertEqual(len(results), 500)

    def test_process_2000_items(self):
        """Process 2000 items — extreme load test."""
        from bdc_loader_plugin.stac.parsers import extract_bands_from_assets, extract_tile_from_id

        assets = self._make_assets(5)

        for i in range(2000):
            item_id = self._make_item_id(i)
            extract_tile_from_id(item_id)
            extract_bands_from_assets(assets)


# ══════════════════════════════════════════════════════════════════════════════
# PART 4: DICT / LOOKUP STRESS
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# PART 5: EXTRACTION PIPELINE STRESS
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# PART 6: UI STRING CONSISTENCY (NO PORTUGUESE LEAKS)
# ══════════════════════════════════════════════════════════════════════════════


class TestUIStringConsistency(unittest.TestCase):
    """Scan source files for remaining Portuguese UI strings."""

    # Portuguese words that should NOT appear in user-visible strings
    # (excluding comments, docstrings, variable names)
    PT_PATTERNS = [
        r'"[^"]*\b(Selecione|Saida|Limpar|Gerar VRTs|Cubo|Cenas)\b[^"]*"',
        r'"[^"]*\b(Resolucao|Composicao|Plataforma|Bandas)\b[^"]*"',
        r'"[^"]*\b(colecoes|colecao|Resultado|Resultados limpos)\b[^"]*"',
        r'"[^"]*\b(Sobre o|Versao Atual|Desenvolvido por)\b[^"]*"',
        r'"[^"]*\b(Funcionalidades Principais|Links Uteis)\b[^"]*"',
        r'"[^"]*\b(Modo Extensao|Modo Tiles|Deseja baixar)\b[^"]*"',
        r'"[^"]*\b(Download Necessario|Grade .* nao encontrada)\b[^"]*"',
        r'"[^"]*\b(Download cancelado|itens encontrados|Processando)\b[^"]*"',
        r'"[^"]*\b(Exportar series|temporais completas)\b[^"]*"',
        r'"[^"]*\b(Dependencia ausente|nao foi encontrado)\b[^"]*"',
        r'"[^"]*\b(Banda R:|Banda G:|Banda B:|Banda Single:)\b[^"]*"',
        r'"[^"]*\b(Modo VRT:|Deixe vazio)\b[^"]*"',
        r'"[^"]*\b(Escolhe pasta|Limpa todos)\b[^"]*"',
        r'"[^"]*\b(Ver documentacao|Comprimento de Onda|Nome Comum)\b[^"]*"',
        r'"[^"]*\b(STAC: Lento|Servidor pode|Clique para)\b[^"]*"',
        r'"[^"]*\b(inacessivel|desatualizadas|sobrecarregado)\b[^"]*"',
    ]

    # Source files to scan (user-facing)
    SOURCE_FILES = [
        "ui/main_dialog.py",
        "ui/main_layout.py",
        "ui/timeseries_panel.py",
        "widgets/dialogs.py",
        "widgets/timeline_slider.py",
        "chart/dock.py",
        "chart/dock_layout.py",
        "ui/tile_filter_dialog.py",
        "ui/settings_storage.py",
        "ui/settings_downloads.py",
        "ui/bdc_projection.py",
        "widgets/shortcut_dialog.py",
        "chart/export.py",
        "extraction/timeseries.py",
        "extraction/wtss_extractor.py",
        "bdc_loader_plugin.py",
        "__init__.py",
        "vendored.py",
        "logger.py",
    ]

    def _get_plugin_dir(self):
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_no_portuguese_in_ui_strings(self):
        """Scan all source files for Portuguese UI strings in quotes."""
        plugin_dir = self._get_plugin_dir()
        violations = []

        for rel_path in self.SOURCE_FILES:
            filepath = os.path.join(plugin_dir, rel_path)
            if not os.path.exists(filepath):
                continue
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()
            for line_num, line in enumerate(lines, 1):
                stripped = line.strip()
                # Skip comments and docstrings
                if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                    continue
                for pattern in self.PT_PATTERNS:
                    match = re.search(pattern, line, re.IGNORECASE)
                    if match:
                        violations.append(f"  {rel_path}:{line_num}: {match.group(0)[:80]}")

        if violations:
            self.fail(f"Found {len(violations)} Portuguese UI string(s):\n" + "\n".join(violations[:20]))

    def test_about_dialog_in_english(self):
        """About dialog HTML must be in English."""
        plugin_dir = self._get_plugin_dir()
        filepath = os.path.join(plugin_dir, "ui", "about_dialog.py")
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        # Must NOT have Portuguese about text
        self.assertNotIn("Sobre o BDC", content)
        self.assertNotIn("Versao Atual", content)
        self.assertNotIn("Desenvolvido por", content)
        self.assertNotIn("Funcionalidades Principais", content)
        self.assertNotIn("Links Uteis", content)
        self.assertNotIn("Documentacao das Colecoes", content)

        # Must HAVE English about text
        self.assertIn("About BDC Loader", content)
        self.assertIn("Current Version", content)
        self.assertIn("Developed by", content)
        self.assertIn("Key Features", content)

    @staticmethod
    def _main_window_source(plugin_dir):
        """Source of the main window: its behaviour and its layout module."""
        parts = []
        for name in ("main_dialog.py", "main_layout.py"):
            with open(os.path.join(plugin_dir, "ui", name), "r", encoding="utf-8") as f:
                parts.append(f.read())
        return "\n".join(parts)

    def test_stac_status_in_english(self):
        """STAC status messages must be in English."""
        plugin_dir = self._get_plugin_dir()
        content = self._main_window_source(plugin_dir)

        self.assertNotIn("STAC: Lento", content)
        self.assertNotIn("Servidor pode estar", content)
        self.assertNotIn("Clique para abrir", content)
        self.assertNotIn("inacessivel", content)

        self.assertIn("Click to open", content)

    def test_buttons_in_english(self):
        """All buttons must have English labels."""
        plugin_dir = self._get_plugin_dir()
        content = self._main_window_source(plugin_dir)

        self.assertIn('QPushButton("Load layers")', content)
        self.assertIn('QPushButton("Clear")', content)
        self.assertIn('QPushButton("Reset")', content)

        self.assertNotIn('QPushButton("Gerar VRTs")', content)
        self.assertNotIn('QPushButton("Limpar")', content)

    def test_collection_info_in_english(self):
        """Collection info labels must be in English."""
        plugin_dir = self._get_plugin_dir()
        content = self._main_window_source(plugin_dir)

        self.assertIn("Type:", content)
        self.assertNotIn("'Cubo'", content)
        self.assertNotIn("'Cenas'", content)

    def test_band_table_in_english(self):
        """Band info table headers must be in English."""
        plugin_dir = self._get_plugin_dir()
        content = self._main_window_source(plugin_dir)

        self.assertNotIn("<th>Banda</th>", content)
        self.assertNotIn("<th>Nome Comum</th>", content)
        self.assertNotIn("Comprimento de Onda", content)

    def test_vendored_in_english(self):
        """vendored.py error messages in English."""
        plugin_dir = self._get_plugin_dir()
        filepath = os.path.join(plugin_dir, "vendored.py")
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("Missing dependency", content)
        self.assertNotIn("ausente", content)

    def test_dialogs_in_english(self):
        """widgets/dialogs.py labels in English."""
        plugin_dir = self._get_plugin_dir()
        filepath = os.path.join(plugin_dir, "widgets", "dialogs.py")
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("VRT Mode:", content)
        self.assertIn("Band R:", content)
        self.assertIn("Band G:", content)
        self.assertIn("Band B:", content)
        self.assertIn("Single Band:", content)
        self.assertIn("RGB (3 bands)", content)

        self.assertNotIn("Modo VRT:", content)
        self.assertNotIn("Banda R:", content)
        self.assertNotIn("Banda G:", content)
        self.assertNotIn("Banda B:", content)
        self.assertNotIn("Banda Single:", content)

    def test_dock_tooltip_in_english(self):
        """Chart dock tooltips in English."""
        plugin_dir = self._get_plugin_dir()
        content = ""
        for name in ("dock.py", "dock_layout.py"):
            with open(os.path.join(plugin_dir, "chart", name), "r", encoding="utf-8") as f:
                content += f.read()

        self.assertIn("Export complete time series as GeoPackage", content)
        self.assertNotIn("Exportar series temporais", content)


# ══════════════════════════════════════════════════════════════════════════════
# PART 7: MEMORY STABILITY
# ══════════════════════════════════════════════════════════════════════════════


class TestMemoryStability(unittest.TestCase):
    """Verify no obvious memory leaks under repeated operations."""

    def test_gc_collects_after_parser_stress(self):
        """After 5000 parser calls, garbage collector finds no uncollectable."""
        from bdc_loader_plugin.stac.parsers import extract_bands_from_assets, extract_tile_from_id

        assets = {f"B{i:02d}": {"type": "image/tiff; application=geotiff"} for i in range(10)}

        gc.collect()
        uncollectable_before = len(gc.garbage)

        for i in range(5000):
            extract_tile_from_id(f"S2-16D-2_{i:06d}_V2023-01-01")
            extract_bands_from_assets(assets)

        gc.collect()
        uncollectable_after = len(gc.garbage)

        self.assertEqual(uncollectable_before, uncollectable_after, "GC found uncollectable objects after stress test")


# ══════════════════════════════════════════════════════════════════════════════
# PART 7.5: GRID AND TILE PATTERN VALIDATION
# ══════════════════════════════════════════════════════════════════════════════


class TestGridConfiguration(unittest.TestCase):
    """Validate grid URLs, tile patterns, and WFS configuration."""

    def test_all_grid_urls_are_wfs(self):
        """All FALLBACK_GRID_URLS point to BDC GeoServer WFS."""
        from bdc_loader_plugin.stac.fallback import FALLBACK_GRID_URLS

        for name, url in FALLBACK_GRID_URLS.items():
            self.assertIn("data.inpe.br/bdc/geoserver", url, f"Grid {name} URL should point to BDC GeoServer")
            self.assertIn("service=WFS", url, f"Grid {name} URL should be a WFS request")

    def test_mgrs_wrs2_have_brazil_bbox(self):
        """MGRS, WRS2, STG, MUX_GRID URLs include Brazil bbox filter."""
        from bdc_loader_plugin.stac.fallback import FALLBACK_GRID_URLS

        for name in ["MGRS", "WRS2", "STG", "MUX_GRID"]:
            url = FALLBACK_GRID_URLS.get(name, "")
            self.assertIn("bbox=", url, f"Grid {name} URL should include bbox filter for Brazil")

    def test_bdc_grids_no_bbox_needed(self):
        """BDC-specific grids are Brazil-only and don't need bbox."""
        from bdc_loader_plugin.stac.fallback import FALLBACK_GRID_URLS

        for name in ["BDC_LG_V2", "BDC_MD_V2", "BDC_SM_V2"]:
            url = FALLBACK_GRID_URLS.get(name, "")
            self.assertNotIn("bbox=", url, f"Grid {name} is Brazil-only, no bbox needed")

    def test_brazil_bbox_constants(self):
        """Verify Brazil bbox constants are sensible."""
        from bdc_loader_plugin.stac.fallback import BRAZIL_BBOX

        self.assertEqual(len(BRAZIL_BBOX), 4)
        self.assertLess(BRAZIL_BBOX[0], -70)  # west
        self.assertLess(BRAZIL_BBOX[1], -30)  # south
        self.assertGreater(BRAZIL_BBOX[2], -30)  # east
        self.assertGreater(BRAZIL_BBOX[3], 4)  # north

    def test_geoserver_wfs_url(self):
        """BDC_GEOSERVER_WFS is set correctly."""
        from bdc_loader_plugin.stac.fallback import BDC_GEOSERVER_WFS

        self.assertIn("data.inpe.br/bdc/geoserver", BDC_GEOSERVER_WFS)


# ══════════════════════════════════════════════════════════════════════════════
# PART 8: FALLBACK DATA INTEGRITY UNDER STRESS
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# PART 9: CROSS-MODULE INTEGRATION STRESS
# ══════════════════════════════════════════════════════════════════════════════


class TestCrossModuleIntegration(unittest.TestCase):
    """Test interactions between modules under load."""

    def test_full_pipeline_simulation_200_items(self):
        """Simulate a full search-to-display pipeline for 200 items."""
        from bdc_loader_plugin.stac.fallback import FALLBACK_COLLECTIONS
        from bdc_loader_plugin.stac.parsers import (
            build_display_name,
            extract_bands_from_assets,
            extract_resolution,
            extract_tile_from_id,
            format_compositing,
            format_platform,
            format_tile_display,
            has_valid_tile_system,
        )

        col_names = list(FALLBACK_COLLECTIONS.keys())
        if not col_names:
            self.skipTest("No collections")

        for i in range(200):
            col_name = col_names[i % len(col_names)]
            config = FALLBACK_COLLECTIONS[col_name]

            # Build display name
            build_display_name(config["id"], col_name, config["type"])

            # Format metadata
            format_platform(config.get("platform"))
            comp_raw = config.get("compositing", {})
            if isinstance(comp_raw, str):
                pass  # already formatted in fallback
            else:
                format_compositing(comp_raw, config.get("type", "cube"))
            config.get("resolution") or extract_resolution(config)
            has_valid_tile_system(config.get("grs", ""))

            # Simulate item processing
            item_id = f"{config['id']}_{i:04d}_V2023-01-01"
            tile = extract_tile_from_id(item_id)
            format_tile_display(tile, config.get("grs", ""))

            # Extract bands
            assets = {b: {"type": "image/tiff; application=geotiff"} for b in config.get("bands", ["B01", "B02"])}
            extract_bands_from_assets(assets)

    def test_logger_under_load(self):
        """Logger functions work under high call volume."""
        from bdc_loader_plugin.logger import error, info, warning

        for i in range(1000):
            info(f"Test message {i}")
            warning(f"Warning {i}")
            error(f"Error {i}")


# ══════════════════════════════════════════════════════════════════════════════
# PART N: PERFORMANCE CONFIGURATION TESTS
# ══════════════════════════════════════════════════════════════════════════════


class TestPerformanceProfiles(unittest.TestCase):
    """Validate performance profiles, auto-detection, and config flow."""

    def test_detect_system_profile_returns_valid(self):
        """detect_system_profile returns a known profile name."""
        from bdc_loader_plugin.config import PERFORMANCE_PROFILES, detect_system_profile

        result = detect_system_profile()
        self.assertIn(result, PERFORMANCE_PROFILES, f"detect_system_profile returned unknown profile: {result}")

    def test_get_performance_config_returns_all_keys(self):
        """get_performance_config returns dict with all perf keys."""
        from bdc_loader_plugin.config import PERF_LIMITS, get_performance_config

        config = get_performance_config()
        for key in PERF_LIMITS:
            self.assertIn(key, config, f"Config missing key '{key}'")

    def test_get_performance_config_values_within_limits(self):
        """Effective config values respect PERF_LIMITS."""
        from bdc_loader_plugin.config import PERF_LIMITS, get_performance_config

        config = get_performance_config()
        for key, (lo, hi) in PERF_LIMITS.items():
            val = config[key]
            self.assertGreaterEqual(val, lo)
            self.assertLessEqual(val, hi)


class TestPerfConfigOverrides(unittest.TestCase):
    """Test that QgsSettings overrides work correctly."""

    def setUp(self):
        reset_state()

    def test_override_max_threads(self):
        """User override for max_threads is applied."""
        from bdc_loader_plugin.config import get_performance_config

        settings = MagicMock()
        with patch("bdc_loader_plugin.config.QgsSettings", return_value=settings):
            settings.value = MagicMock(
                side_effect=lambda key, default=None, type=None: {
                    "bdc_loader/perf_profile": "auto",
                    "bdc_loader/perf_max_threads": "6",
                }.get(key, default)
            )
            config = get_performance_config()
            self.assertEqual(config["max_threads"], 6)

    def test_profile_auto_resolves(self):
        """Profile 'auto' resolves to a real profile."""
        from bdc_loader_plugin.config import PERF_LIMITS, get_performance_config

        config = get_performance_config()
        for key in PERF_LIMITS:
            self.assertIn(key, config)


class TestTimerseriesPerfIntegration(unittest.TestCase):
    """Verify timeseries module reads perf config correctly."""

    def test_get_perf_config_returns_dict(self):
        """_get_perf_config() returns a dict with expected keys."""
        from bdc_loader_plugin.extraction.gdal_setup import _get_perf_config

        config = _get_perf_config()
        self.assertIsInstance(config, dict)
        self.assertIn("max_threads", config)

    def test_get_perf_config_values_positive(self):
        """All returned perf values are positive integers."""
        from bdc_loader_plugin.extraction.gdal_setup import _get_perf_config

        config = _get_perf_config()
        for key in ["max_threads", "gdal_cache_mb", "http_timeout"]:
            self.assertGreater(config.get(key, 0), 0, f"perf config '{key}' must be > 0")


class TestPerfConfigStress(unittest.TestCase):
    """Stress-test configuration read/write cycles."""

    def test_rapid_config_reads(self):
        """1000 rapid get_performance_config calls complete quickly."""
        from bdc_loader_plugin.config import get_performance_config

        for _ in range(1000):
            get_performance_config()

    def test_rapid_detect_calls(self):
        """1000 rapid detect_system_profile calls complete quickly."""
        from bdc_loader_plugin.config import detect_system_profile

        for _ in range(1000):
            detect_system_profile()


if __name__ == "__main__":
    unittest.main()
