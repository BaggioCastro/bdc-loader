"""Point the plugin modules at the real osgeo bindings inside tests that run real GDAL."""

import sys
from unittest.mock import patch


def patch_plugin_osgeo(stack, real_gdal, real_ogr, real_osr):
    """Swap gdal, ogr and osr in every loaded plugin module that imported them, for the life of ``stack``."""
    import bdc_loader_plugin.core.vrt_builder  # noqa: F401  (loads the raster modules it imports)

    for name, module in list(sys.modules.items()):
        if module is None or not name.startswith("bdc_loader_plugin.") or ".tests" in name:
            continue
        for attr, real in (("gdal", real_gdal), ("ogr", real_ogr), ("osr", real_osr)):
            if attr in vars(module):
                stack.enter_context(patch.object(module, attr, real))
