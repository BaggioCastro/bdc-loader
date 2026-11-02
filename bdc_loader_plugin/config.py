"""
config.py

Persistent configuration manager for the BDC Loader Plugin.
Handles saving and retrieving user settings using QgsSettings.

Developed by Baggio Luiz de Castro e Silva
INPE - Sao Jose dos Campos, 2026
"""

import functools
import json
import logging
import os
import sys

_logger = logging.getLogger("bdc_loader")

from qgis.core import QgsSettings

# ── Plugin Version (single source: VERSION file, propagated by bump_version.py)
PLUGIN_VERSION = "1.0.0"

# ── Performance Profiles ──────────────────────────────────────────────────────
# Each profile defines safe defaults for machines of different capabilities.
#
# All parallel COG reads share a single ThreadPoolExecutor.
#
#   max_threads     — single pool size for all parallel COG reads (STAC)
#   wtss_workers    — parallel points for WTSS server-side extraction
#   gdal_cache_mb   — GDAL VSI cache size in MB
#   http_timeout    — GDAL HTTP connection timeout (seconds)

PERFORMANCE_PROFILES = {
    "low": {
        "label": "Low (2-4 cores, ≤4 GB RAM)",
        "max_threads": 6,
        "wtss_workers": 2,
        "gdal_cache_mb": 5,
        "http_timeout": 15,
    },
    "medium": {
        "label": "Medium (4-8 cores, 4-8 GB RAM)",
        "max_threads": 10,
        "wtss_workers": 3,
        "gdal_cache_mb": 10,
        "http_timeout": 10,
    },
    "high": {
        "label": "High (8-16 cores, 8-32 GB RAM)",
        "max_threads": 16,
        "wtss_workers": 4,
        "gdal_cache_mb": 20,
        "http_timeout": 10,
    },
    "ultra": {
        "label": "Ultra (16+ cores, 32+ GB RAM)",
        "max_threads": 24,
        "wtss_workers": 5,
        "gdal_cache_mb": 40,
        "http_timeout": 8,
    },
}

# Absolute safety limits (user cannot exceed these)
PERF_LIMITS = {
    "max_threads": (2, 32),
    "wtss_workers": (1, 8),
    "gdal_cache_mb": (2, 100),
    "http_timeout": (5, 60),
}


def detect_system_profile() -> str:
    """Auto-detect the best performance profile based on CPU cores and RAM."""
    cpu_count = os.cpu_count() or 2
    ram_gb = _get_total_ram_gb()

    if cpu_count >= 16 and ram_gb >= 32:
        return "ultra"
    elif cpu_count >= 8 and ram_gb >= 8:
        return "high"
    elif cpu_count >= 4 and ram_gb >= 4:
        return "medium"
    else:
        return "low"


def _windows_ram_bytes():
    import ctypes

    class _MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = _MemoryStatus()
    status.dwLength = ctypes.sizeof(_MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise OSError("GlobalMemoryStatusEx failed")
    return status.ullTotalPhys


def _read_total_ram_gb() -> float:
    """Total system RAM in GB: psutil when QGIS ships it, else the OS's own source."""
    try:
        import psutil

        return psutil.virtual_memory().total / (1024**3)
    except ImportError:
        pass
    try:
        if sys.platform == "win32":
            return _windows_ram_bytes() / (1024**3)
        if sys.platform == "darwin":
            import subprocess

            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], timeout=5, text=True)
            return int(out.strip()) / (1024**3)
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal"):
                    return int(line.split()[1]) / (1024 * 1024)
    except Exception as exc:
        _logger.debug("RAM detection failed: %s", exc)
    return 4.0  # conservative default


@functools.lru_cache(maxsize=1)
def _get_total_ram_gb() -> float:
    """Total system RAM in GB, read once per session (the macOS source starts a process)."""
    return _read_total_ram_gb()


def get_performance_config() -> dict:
    """Get the effective performance configuration.

    Priority: user overrides > saved profile > auto-detected profile.
    Returns dict with all performance keys.
    """
    settings = QgsSettings()
    profile_name = settings.value("bdc_loader/perf_profile", "auto", type=str)

    if profile_name == "auto":
        profile_name = detect_system_profile()

    base = dict(PERFORMANCE_PROFILES.get(profile_name, PERFORMANCE_PROFILES["medium"]))
    base.pop("label", None)

    # Apply user overrides (only if explicitly set)
    for key, (lo, hi) in PERF_LIMITS.items():
        user_val = settings.value(f"bdc_loader/perf_{key}", None)
        if user_val is not None:
            val = max(lo, min(hi, int(user_val)))
            base[key] = val

    return base


class ConfigManager:
    """
    Manages persistent configuration settings for the plugin.
    """

    # ── User band compositions ────────────────────────────────────────────

    _COMPOSITIONS_KEY = "bdc_loader/custom_compositions"

    @staticmethod
    def _read_compositions() -> dict:
        settings = QgsSettings()
        raw = settings.value(ConfigManager._COMPOSITIONS_KEY, "", type=str)
        try:
            data = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            _logger.warning("Ignoring unreadable custom compositions setting")
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def get_custom_compositions(collection_id: str) -> dict:
        """Return {name: [bands]} saved by the user for ``collection_id``."""
        entries = ConfigManager._read_compositions().get(collection_id, {})
        if not isinstance(entries, dict):
            return {}
        return {
            str(name): [str(b) for b in bands] for name, bands in entries.items() if isinstance(bands, list) and bands
        }

    @staticmethod
    def save_custom_composition(collection_id: str, name: str, bands: list):
        data = ConfigManager._read_compositions()
        data.setdefault(collection_id, {})[name] = list(bands)
        QgsSettings().setValue(ConfigManager._COMPOSITIONS_KEY, json.dumps(data))

    @staticmethod
    def delete_custom_composition(collection_id: str, name: str) -> bool:
        data = ConfigManager._read_compositions()
        entries = data.get(collection_id, {})
        if name not in entries:
            return False
        del entries[name]
        if not entries:
            data.pop(collection_id, None)
        QgsSettings().setValue(ConfigManager._COMPOSITIONS_KEY, json.dumps(data))
        return True

    # ── Performance settings ──────────────────────────────────────────────

    @staticmethod
    def get_performance_config() -> dict:
        return get_performance_config()
