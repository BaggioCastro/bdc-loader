# -*- coding: utf-8 -*-
"""
band_scaling.py

Scale, offset and valid range of a collection's bands, as the BDC declares
them in the collection's ``eo:bands`` (``scale``, ``scale_add``, ``min``,
``max``, ``nodata``).

Pixel values are stored as integers: Landsat Collection 2 Level-2 surface
reflectance is ``DN * 2.75e-05 - 0.2`` (valid 7273-43636), Sentinel-2 cubes
``DN * 1e-4``. Spectral indices must be computed on reflectance; computed on
the stored integers, the Landsat offset pulls NDVI far down (median 0.19
against 0.56 at the same point). Scenes carry none of this, so it is read
from the collection, once per collection and process.

No Qt: safe from worker threads.
"""

import threading

import requests

from ..net import METADATA_S
from ..stac.client import STAC_URL as BDC_STAC_URL

_cache = {}
_lock = threading.Lock()


def _parse(collection):
    bands = (collection.get("properties") or {}).get("eo:bands") or (collection.get("summaries") or {}).get("eo:bands")
    entries = []
    for band in bands or []:
        if not isinstance(band, dict):
            continue
        entry = {
            "scale": band.get("scale"),
            "offset": band.get("scale_add", band.get("offset")),
            "min": band.get("min"),
            "max": band.get("max"),
            "nodata": band.get("nodata"),
        }
        entries.append((band, entry))
    info = {}
    # Band names first, so a common name never hides a band of that name;
    # several sensors share a common name (TM/ETM+/OLI red) and declare the
    # same scale for it, so the first one is kept.
    for field in ("name", "common_name"):
        for band, entry in entries:
            key = band.get(field)
            if key:
                info.setdefault(str(key).lower(), entry)
    return info


def collection_band_info(collection_id, timeout=METADATA_S):
    """{band name or common name (lower case): {scale, offset, min, max, nodata}}.

    Empty when the collection declares nothing or cannot be read; the
    result (empty included) is cached for the process.
    """
    with _lock:
        if collection_id in _cache:
            return _cache[collection_id]
    info = {}
    try:
        url = f"{BDC_STAC_URL.rstrip('/')}/collections/{collection_id}"
        response = requests.get(url, timeout=timeout)
        if response.ok:
            info = _parse(response.json())
    except Exception:
        info = {}
    with _lock:
        _cache[collection_id] = info
    return info


def band_entry(info, band):
    return (info or {}).get(str(band).lower())


def to_reflectance(series, entry):
    """``series`` [(date, stored value)] converted with the band's scale and offset.

    Returned unchanged when the band declares no scale.
    """
    if not entry or entry.get("scale") in (None, 0):
        return list(series)
    scale = float(entry["scale"])
    offset = float(entry.get("offset") or 0.0)
    return [(date, value * scale + offset) for date, value in series]


def declared_valid_range(info, band):
    """(min, max) in stored units declared for ``band``, or None."""
    entry = band_entry(info, band)
    if not entry or entry.get("min") is None or entry.get("max") is None:
        return None
    return float(entry["min"]), float(entry["max"])


def display_scaling(entry):
    """(a, b) so that ``a * stored + b`` is reflectance x 10^4, or None.

    Applies to reflectance-like bands only: a declared scale below 0.001 and
    an offset within +/-1 (Landsat Collection 2 2.75e-05 and -0.2; the
    Sentinel-2, CBERS and MODIS cubes 1e-04, whose stored values already are
    reflectance x 10^4). Temperature, angles and aerosol bands keep their
    stored values.
    """
    if not entry or not entry.get("scale"):
        return None
    scale = float(entry["scale"])
    offset = float(entry.get("offset") or 0.0)
    if not 0 < scale < 0.001 or abs(offset) > 1:
        return None
    return scale * 10000.0, offset * 10000.0
