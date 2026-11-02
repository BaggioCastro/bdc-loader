"""Freshness of the local overview (.ovr) cached next to a VRT.

An overview is current when it carries this plugin's version stamp and the
digest of the VRT it was built from.
"""

import hashlib
import os

from osgeo import gdal

from .gdal_env import uses_gdal

_OVERVIEW_METADATA_KEY = "BDC_LOADER_OVERVIEW_VERSION"


_OVERVIEW_VERSION = "4"


_OVERVIEW_SOURCE_KEY = "BDC_LOADER_OVERVIEW_SOURCE"


def _file_digest(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha1(f.read(), usedforsecurity=False).hexdigest()
    except OSError:
        return ""


@uses_gdal
def _overview_is_current(overview_path, vrt_path=None):
    """Return whether an overview was produced by the current implementation
    and, when ``vrt_path`` is given, from that VRT as it is now on disk.

    A VRT rebuilt with other sources (another tile set for the same date, a
    mask band added) gets a new overview instead of the old one's pixels.
    """
    if not os.path.isfile(overview_path):
        return False

    dataset = None
    try:
        dataset = gdal.Open(overview_path, gdal.GA_ReadOnly)
        if not dataset or dataset.GetMetadataItem(_OVERVIEW_METADATA_KEY) != _OVERVIEW_VERSION:
            return False
        return vrt_path is None or dataset.GetMetadataItem(_OVERVIEW_SOURCE_KEY) == _file_digest(vrt_path)
    except Exception:
        return False
    finally:
        dataset = None


@uses_gdal
def _stamp_overview(tmp_ovr_path, vrt_path):
    """Record the overview version and the VRT digest that _overview_is_current compares."""
    ds = gdal.Open(tmp_ovr_path, gdal.GA_Update)
    if not ds:
        return False
    ds.SetMetadataItem(_OVERVIEW_METADATA_KEY, _OVERVIEW_VERSION)
    ds.SetMetadataItem(_OVERVIEW_SOURCE_KEY, _file_digest(vrt_path))
    ds.FlushCache()
    ds = None
    return True
