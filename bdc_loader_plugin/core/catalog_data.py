"""The collection catalogue the plugin reads: collections, their bands, RGB presets and grid URLs.

It starts from the offline fallback in ``stac/fallback.py``. When the STAC
answers, ``core/catalog.py`` replaces the contents of these dicts in place, so
every module that imported them sees the current catalogue.
"""

from ..stac.fallback import FALLBACK_BAND_INFO, FALLBACK_COLLECTIONS, FALLBACK_GRID_URLS, FALLBACK_RGB_PRESETS

BAND_INFO = dict(FALLBACK_BAND_INFO)
COLLECTIONS = dict(FALLBACK_COLLECTIONS)
GRID_URLS = dict(FALLBACK_GRID_URLS)
RGB_PRESETS = dict(FALLBACK_RGB_PRESETS)
