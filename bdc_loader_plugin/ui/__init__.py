"""
UI Package

Provides the main visual interfaces for the BDC Loader QGIS Plugin:
1. BDCLoaderDialog: The STAC search and layer loading window.
2. BDCTimeSeriesPanel: The QDockWidget for interactive time-series extraction.
"""


def __getattr__(name):
    if name == "BDCLoaderDialog":
        from .main_dialog import BDCLoaderDialog

        return BDCLoaderDialog
    if name == "BDCTimeSeriesPanel":
        from .timeseries_panel import BDCTimeSeriesPanel

        return BDCTimeSeriesPanel
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["BDCLoaderDialog", "BDCTimeSeriesPanel"]
