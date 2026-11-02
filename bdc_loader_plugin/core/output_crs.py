# -*- coding: utf-8 -*-
"""
Output projection choices for downloaded GeoTIFFs.

Provides:
- `OutputCrsOption` — one projection offered by the download confirmation
  dialog: the source's native grid, WGS 84, or the QGIS project's own CRS
- `build_options` / `default_key` — the offered list and the projection
  pre-selected from the current project CRS
- `stored_option` / `save_option` — persistence, so a download that skips the
  confirmation dialog still writes in the projection the user last picked
- `crs_tag` — the filename tag that keeps one projection's download from
  overwriting another's

Free of Qt widgets so the choice logic can be tested on its own; the only QGIS
dependencies are reading the project CRS and the settings store.
"""

import hashlib
import logging
import re
from dataclasses import dataclass
from typing import Optional

from qgis.core import QgsSettings

from .bdc_crs import _is_bdc_crs, _resolve_bdc_crs

_logger = logging.getLogger("bdc_loader")

NATIVE = "native"
WGS84 = "wgs84"
PROJECT = "project"

OUTPUT_CRS_SETTING = "bdc_loader/download_output_crs"

WGS84_AUTHID = "EPSG:4326"

_EPSG_AUTHID_RE = re.compile(r"^EPSG:\d+$", re.IGNORECASE)
_CRS_ERRORS = (AttributeError, RuntimeError, TypeError, ValueError, ImportError)

# Distinguishes "no CRS was supplied, go read the project" from an explicit
# None meaning "this project has no usable CRS".
_FROM_PROJECT = object()


@dataclass(frozen=True)
class OutputCrsOption:
    """One projection the download dialog can write in.

    key: stable identifier persisted in QgsSettings (NATIVE/WGS84/PROJECT).
    label: the text shown next to the radio button.
    warp_srs: what gdal.Warp receives as dstSRS; None means "leave the source
        grid untouched", which is also the only option that resamples nothing.
    tag: filename tag distinguishing this projection's output from the others;
        empty for the native option, which owns the untagged filename.
    enabled: False when the option cannot be offered (no valid project CRS).
    hint: one-line explanation shown under the label.
    """

    key: str
    label: str
    warp_srs: Optional[str]
    tag: str
    enabled: bool = True
    hint: str = ""


def _crs_call(crs, name, default=""):
    """Call a no-argument QgsCoordinateReferenceSystem accessor defensively.

    QGIS releases differ in which of these exist, and a CRS handed in from a
    closed project can raise instead of answering, so a missing or failing
    accessor degrades to *default* rather than breaking the download dialog.
    """
    if crs is None:
        return default
    try:
        value = getattr(crs, name)()
    except _CRS_ERRORS:
        return default
    return default if value is None else value


def current_project_crs():
    """Return the QGIS project CRS, or None when there isn't a valid one."""
    try:
        from qgis.core import QgsProject

        crs = QgsProject.instance().crs()
    except _CRS_ERRORS:
        _logger.debug("Project CRS is unavailable", exc_info=True)
        return None
    try:
        return crs if crs is not None and crs.isValid() else None
    except _CRS_ERRORS:
        return None


def is_wgs84(crs):
    """True when *crs* is plain geographic WGS 84."""
    if str(_crs_call(crs, "authid")).upper() == WGS84_AUTHID:
        return True
    proj = str(_crs_call(crs, "toProj"))
    return "+proj=longlat" in proj and ("+datum=WGS84" in proj or "+ellps=WGS84" in proj)


def is_bdc_albers(crs):
    """True when *crs* is the Albers grid the BDC cubes are stored in."""
    try:
        bdc_crs, _from_epsg = _resolve_bdc_crs()
        return bool(_is_bdc_crs(crs, bdc_crs))
    except _CRS_ERRORS:
        return False


def warp_srs_for(crs):
    """Return *crs* in a form gdal.Warp's dstSRS accepts, or None.

    An EPSG authid is preferred because it survives round-tripping and reads
    well in a filename tag. A QGIS custom CRS reports a "USER:100001" authid
    that means nothing to GDAL, so those fall back to WKT and then PROJ.
    """
    authid = str(_crs_call(crs, "authid")).strip()
    if _EPSG_AUTHID_RE.match(authid):
        return authid.upper()
    wkt = str(_crs_call(crs, "toWkt")).strip()
    if wkt:
        return wkt
    proj = str(_crs_call(crs, "toProj")).strip()
    return proj or None


def crs_tag(warp_srs):
    """Return the filename tag for an output projection.

    Native output carries no tag: an untagged masked GeoTIFF on disk is the
    source grid, and stays recognized as already downloaded.
    """
    text = str(warp_srs or "").strip()
    if not text:
        return ""
    if _EPSG_AUTHID_RE.match(text):
        return text.lower().replace(":", "")
    return "crs" + hashlib.sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]


def crs_display_name(crs):
    """Human-readable name for a CRS, for the project option's label.

    The name and the authority code are joined with a dash rather than nested
    parentheses, because the label already wraps this in parentheses.
    """
    description = str(_crs_call(crs, "description")).strip()
    authid = str(_crs_call(crs, "authid")).strip()
    if description and authid and authid.lower() not in description.lower():
        return f"{description} — {authid}"
    return description or authid or "unknown"


def build_options(crs=_FROM_PROJECT):
    """Return the three projections offered at download time, in dialog order.

    *crs* is the QGIS project CRS; it is read from the project when omitted,
    and an explicit None means the project has none. The project option comes
    back disabled when there is no usable project CRS to warp to, so the
    dialog can gray it out instead of hiding it.
    """
    if crs is _FROM_PROJECT:
        crs = current_project_crs()

    options = [
        OutputCrsOption(
            NATIVE,
            "Native (BDC Albers)",
            None,
            "",
            hint="Keeps the grid the cube is stored in — nothing is resampled.",
        ),
        OutputCrsOption(
            WGS84,
            "WGS 84 (EPSG:4326)",
            WGS84_AUTHID,
            crs_tag(WGS84_AUTHID),
            hint="Geographic latitude/longitude — the most portable output.",
        ),
    ]

    project_srs = warp_srs_for(crs)
    if project_srs:
        options.append(
            OutputCrsOption(
                PROJECT,
                f"Current QGIS project CRS ({crs_display_name(crs)})",
                project_srs,
                crs_tag(project_srs),
                hint="Lines the download up with the project without on-the-fly reprojection.",
            )
        )
    else:
        options.append(
            OutputCrsOption(
                PROJECT,
                "Current QGIS project CRS (unavailable)",
                None,
                "",
                enabled=False,
                hint="No valid project CRS to reproject to.",
            )
        )
    return options


def default_key(crs=_FROM_PROJECT):
    """Return the option pre-selected for a project in *crs*.

    A project already in WGS 84 or in BDC Albers gets that same projection
    back, so the default never introduces a reprojection the user did not ask
    for; any other project CRS (UTM/SIRGAS 2000 and friends) defaults to
    matching the project, which is what makes the download line up on the
    canvas without on-the-fly reprojection.
    """
    if crs is _FROM_PROJECT:
        crs = current_project_crs()
    if crs is None:
        return NATIVE
    if is_wgs84(crs):
        return WGS84
    if is_bdc_albers(crs):
        return NATIVE
    return PROJECT if warp_srs_for(crs) else NATIVE


def option_for_key(key, options):
    """Return the enabled option matching *key*, or None."""
    for option in options:
        if option.key == key and option.enabled:
            return option
    return None


def stored_option(options=None, crs=_FROM_PROJECT, settings=None):
    """Return the projection a download uses right now.

    This is what the confirmation dialog opens on, and what a download that
    skips confirmation ("Don't ask me again") writes in. An unset, unknown, or
    currently unavailable stored key falls back to the smart default.
    """
    if options is None:
        options = build_options(crs)
    settings = settings or QgsSettings()

    key = settings.value(OUTPUT_CRS_SETTING, None)
    option = option_for_key(str(key), options) if key else None
    if option is None:
        option = option_for_key(default_key(crs), options) or options[0]
    return option


def save_option(option, settings=None):
    """Persist *option* so the next download opens on (or reuses) it."""
    settings = settings or QgsSettings()
    settings.setValue(OUTPUT_CRS_SETTING, option.key)
