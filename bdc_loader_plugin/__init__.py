# -*- coding: utf-8 -*-
"""BDC Loader - QGIS plugin for Brazil Data Cube."""


def classFactory(iface):
    """QGIS plugin factory."""
    from .bdc_loader_plugin import BDCLoaderPlugin

    return BDCLoaderPlugin(iface)
