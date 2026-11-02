"""The plugin's GDAL settings, kept apart from the rest of QGIS.

GDAL's configuration is shared by every layer and plugin of the QGIS process,
so the plugin sets each option at the narrowest scope GDAL reads it from:

* ``GDAL_DISABLE_READDIR_ON_OPEN`` applies to BDC URLs only (GDAL 3.6 or
  later): opening a BDC file asks the server for no directory listing, while
  local files keep finding their .ovr, .aux.xml and world files.
* Cache options, and GDAL exceptions, apply on the thread
  that runs a plugin function, while it runs (``plugin_gdal``). GDAL older than
  3.7 has no per-thread exception switch; there exceptions are turned on for
  the process, as QGIS Processing does on newer versions.
* The HTTP retry options are the only process-wide ones: /vsicurl/ reads them
  from the process configuration only, and QGIS's renderer needs them when it
  reads BDC files on pan and zoom. They change only what happens after an HTTP
  429 or 5xx answer, which is retried instead of failing.
"""

import functools
import threading
from contextlib import contextmanager

from osgeo import gdal

BDC_URL_PREFIX = "/vsicurl/https://data.inpe.br/"

URL_OPTIONS = {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR"}

# GDAL's HTTP retry backoff is exponential on RETRY_DELAY; 3 retries bound the
# worst-case wait of a canvas read under sustained HTTP 429 to a few seconds,
# and a transient rate limit clears on the first retry.
PROCESS_OPTIONS = {"GDAL_HTTP_MAX_RETRY": "3", "GDAL_HTTP_RETRY_DELAY": "1"}

THREAD_OPTIONS = {
    "VSI_CACHE": "YES",
    "VSI_CACHE_SIZE": "100000000",
    # Generic block caching can make gdal.Warp silently emit zero-filled output
    # for remote Float32 VRTs. Keep the driver-optimized RasterIO path enabled.
    "GDAL_FORCE_CACHING": "NO",
}

_session_lock = threading.Lock()
_session_ready = False
_thread_state = threading.local()


def url_options_supported():
    return hasattr(gdal, "SetPathSpecificOption")


def apply_session_options():
    """Set the URL-scoped and process-wide options once per QGIS session."""
    global _session_ready
    with _session_lock:
        if _session_ready:
            return
        if url_options_supported():
            for key, value in URL_OPTIONS.items():
                gdal.SetPathSpecificOption(BDC_URL_PREFIX, key, value)
        for key, value in PROCESS_OPTIONS.items():
            gdal.SetConfigOption(key, value)
        _session_ready = True


def thread_options(extra=None):
    """The options a plugin function runs with on its thread."""
    options = dict(THREAD_OPTIONS)
    if not url_options_supported():
        options.update(URL_OPTIONS)
    options.update(extra or {})
    return options


def _exceptions_on():
    manager = getattr(gdal, "ExceptionMgr", None)
    if manager is not None:
        return manager(useExceptions=True)
    gdal.UseExceptions()
    return None


@contextmanager
def plugin_gdal(extra=None):
    """Run the block with the plugin's GDAL options and exceptions on this thread.

    Nested blocks keep the outermost block's options, so a helper called from
    a block with ``extra`` options does not reset them.
    """
    if getattr(_thread_state, "depth", 0):
        _thread_state.depth += 1
        try:
            yield
        finally:
            _thread_state.depth -= 1
        return
    apply_session_options()
    options = thread_options(extra)
    previous = {key: gdal.GetThreadLocalConfigOption(key, None) for key in options}
    exceptions = _exceptions_on()
    if exceptions is not None:
        exceptions.__enter__()
    for key, value in options.items():
        gdal.SetThreadLocalConfigOption(key, value)
    _thread_state.depth = 1
    try:
        yield
    finally:
        _thread_state.depth = 0
        for key, value in previous.items():
            gdal.SetThreadLocalConfigOption(key, value)
        if exceptions is not None:
            exceptions.__exit__(None, None, None)


def uses_gdal(func):
    """Decorator: ``func`` runs inside ``plugin_gdal()``."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with plugin_gdal():
            return func(*args, **kwargs)

    return wrapper
