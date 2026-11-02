"""GDAL options for reading time-series pixels from remote COGs.

The cache size and HTTP timeout come from the user's performance profile; the
options shared with the rest of the plugin are in core.gdal_env.
"""

import logging

_logger = logging.getLogger("bdc_loader")

# Fallback defaults (used when QgsSettings not available, e.g. tests)
_DEFAULT_MAX_THREADS = 16
_DEFAULT_GDAL_CACHE_MB = 10
_DEFAULT_HTTP_TIMEOUT = 10


def _get_perf_config():
    """Get performance config from QgsSettings or fallback defaults."""
    try:
        from ..config import get_performance_config

        return get_performance_config()
    except Exception:
        return {
            "max_threads": _DEFAULT_MAX_THREADS,
            "gdal_cache_mb": _DEFAULT_GDAL_CACHE_MB,
            "http_timeout": _DEFAULT_HTTP_TIMEOUT,
        }


def point_read_options(perf=None):
    """GDAL options for reading time-series pixels, from the performance profile.

    They apply on the extraction threads only (``core.gdal_env.plugin_gdal``).
    """
    if perf is None:
        perf = _get_perf_config()
    return {
        "GDAL_HTTP_UNSAFESSL": "NO",
        "VSI_CACHE_SIZE": str(perf.get("gdal_cache_mb", _DEFAULT_GDAL_CACHE_MB) * 1024 * 1024),
        "GDAL_BAND_BLOCK_CACHE": "HASHSET",
        "GDAL_HTTP_CONNECTTIMEOUT": str(perf.get("http_timeout", _DEFAULT_HTTP_TIMEOUT)),
        # Whole-request limit: a server that accepts the connection and sends
        # nothing would otherwise hold the read for good.
        "GDAL_HTTP_TIMEOUT": str(perf.get("http_timeout", _DEFAULT_HTTP_TIMEOUT)),
    }
