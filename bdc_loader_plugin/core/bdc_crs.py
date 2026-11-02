"""The BDC Albers Equal-Area Conic CRS (SIRGAS 2000 / Brazil Albers) and how to recognise it."""

import logging
import math
import re

from qgis.core import (
    QgsCoordinateReferenceSystem,
)

_BDC_PROJ = (
    "+proj=aea +lat_0=-12 +lon_0=-54 +lat_1=-2 +lat_2=-22 +x_0=5000000 +y_0=10000000 +ellps=GRS80 +units=m +no_defs"
)


_BDC_EPSG_AUTHID = "EPSG:10857"


_BDC_PROJ_PARAMETERS = {
    "lat_0": -12.0,
    "lon_0": -54.0,
    "lat_1": -2.0,
    "lat_2": -22.0,
    "x_0": 5000000.0,
    "y_0": 10000000.0,
}


_PROJ_PARAMETER_RE = re.compile(r"(?:^|\s)\+?([A-Za-z][A-Za-z0-9_]*)=([^\s]+)")


def _is_bdc_crs(crs, bdc_crs):
    """Return True if crs matches the exact BDC Albers Equal-Area Conic CRS parameters."""
    try:
        if not crs or not bdc_crs or not crs.isValid() or not bdc_crs.isValid():
            return False
    except (AttributeError, RuntimeError):
        return False

    try:
        auth1 = str(crs.authid() or "") if hasattr(crs, "authid") else ""
        auth2 = str(bdc_crs.authid() or "") if hasattr(bdc_crs, "authid") else ""
    except (AttributeError, RuntimeError):
        auth1 = auth2 = ""
    if auth1 and auth2 and auth1 == auth2:
        return True

    try:
        proj = str(crs.toProj() or "") if hasattr(crs, "toProj") else ""
    except (AttributeError, RuntimeError):
        return False
    parameters = {key: value for key, value in _PROJ_PARAMETER_RE.findall(proj)}
    if parameters.get("proj", "").lower() != "aea":
        return False

    for key, expected in _BDC_PROJ_PARAMETERS.items():
        try:
            actual = float(parameters[key])
        except (KeyError, TypeError, ValueError):
            return False
        if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-9):
            return False

    return True


def _resolve_bdc_crs():
    """Return the preferred BDC CRS and whether it came from the EPSG registry.

    EPSG:10857 is the authoritative SIRGAS 2000 / Brazil Albers definition, but
    it is absent from the older EPSG databases bundled with supported QGIS
    releases. Keep the equivalent PROJ definition as a compatibility fallback.
    """
    try:
        epsg_crs = QgsCoordinateReferenceSystem(_BDC_EPSG_AUTHID)
        if epsg_crs.isValid():
            return epsg_crs, True
    except (AttributeError, RuntimeError):
        logging.getLogger("bdc_loader").debug("EPSG:10857 is unavailable", exc_info=True)

    try:
        return QgsCoordinateReferenceSystem.fromProj(_BDC_PROJ), False
    except (AttributeError, RuntimeError):
        logging.getLogger("bdc_loader").debug("Failed to create the BDC CRS fallback", exc_info=True)
        return None, False
