"""Replace the contents of the collection catalogue for one test."""

import contextlib
from unittest.mock import patch


@contextlib.contextmanager
def patch_catalog(collections=None, band_info=None, rgb_presets=None, grid_urls=None):
    """Swap the dicts of core/catalog_data.py that are given; the others stay."""
    from bdc_loader_plugin.core import catalog_data

    with contextlib.ExitStack() as stack:
        for target, value in (
            (catalog_data.COLLECTIONS, collections),
            (catalog_data.BAND_INFO, band_info),
            (catalog_data.RGB_PRESETS, rgb_presets),
            (catalog_data.GRID_URLS, grid_urls),
        ):
            if value is not None:
                stack.enter_context(patch.dict(target, value, clear=True))
        yield
