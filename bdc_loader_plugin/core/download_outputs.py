"""
Output formats and file names for downloads.

Provides:
- the three delivery formats offered when a download starts: one GeoTIFF per
  band, one GeoTIFF per band plus a VRT stacking them, or one multiband GeoTIFF
- `crop_tag` / `area_tag` — filesystem-safe names for a crop (its corner
  coordinates) or a vector feature (layer plus feature), so two areas never
  share a file name
- `tile_outputs` / `area_outputs` — the exact files a download writes for a
  STAC item or for a crop/feature mosaic
- `sits_file_name` — per-band names the R package sits reads as a local cube

Free of Qt widgets and GDAL, so the naming rules can be tested on their own.
"""

import os
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

PER_BAND = "per_band"
PER_BAND_VRT = "per_band_vrt"
MULTIBAND = "multiband"
FORMATS = (PER_BAND, PER_BAND_VRT, MULTIBAND)

FORMAT_SETTING = "bdc_loader/download_format"
SITS_SETTING = "bdc_loader/download_sits_names"

# sits splits a local file name on "_" into X1, X2, tile, band and date
# (its default parse_info), so no field may contain "_".
SITS_DIR = "sits"

_SAFE_RE = re.compile(r"[^\w.\-]")
_SLUG_RE = re.compile(r"[^A-Za-z0-9.]+")


def safe_component(name) -> str:
    """Sanitize a string for use as a single path component."""
    safe = _SAFE_RE.sub("_", str(name).strip())
    while ".." in safe:
        safe = safe.replace("..", "__")
    return safe or "unknown"


def slug(text, max_len=30) -> str:
    """Letters, digits and dots joined by "-", with no "_" (a sits field separator).

    Accents are dropped rather than the whole letter ("São José" -> "Sao-Jose").
    """
    plain = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")
    value = _SLUG_RE.sub("-", plain).strip("-.")
    value = value[:max_len].strip("-.")
    return value or "area"


def _lon(value):
    return f"{abs(value):.3f}{'W' if value < 0 else 'E'}"


def _lat(value):
    return f"{abs(value):.3f}{'S' if value < 0 else 'N'}"


def crop_label(bbox) -> str:
    """Readable corners of a crop, west-south to east-north, to about 100 m."""
    xmin, ymin, xmax, ymax = (float(v) for v in bbox)
    return f"{_lon(xmin)} {_lat(ymin)} to {_lon(xmax)} {_lat(ymax)}"


def crop_tag(bbox) -> str:
    """Area tag of an extent crop, e.g. ``crop-47.950W-15.850S-47.850W-15.750S``."""
    xmin, ymin, xmax, ymax = (float(v) for v in bbox)
    return f"crop-{_lon(xmin)}-{_lat(ymin)}-{_lon(xmax)}-{_lat(ymax)}"


def area_tag(*names) -> str:
    """Area tag from readable parts, e.g. ``area_tag("MGRS", "23LKC")`` -> ``MGRS-23LKC``.

    Names only: callers make the parts unique (layer plus feature, with the
    feature id added when a label repeats inside the layer).
    """
    return slug("-".join(str(n) for n in names if n not in (None, "")), max_len=60)


def normalize_format(value) -> str:
    return value if value in FORMATS else PER_BAND


def stored_format(settings):
    """(format, sits_names) last chosen by the user."""
    fmt = normalize_format(settings.value(FORMAT_SETTING, PER_BAND))
    sits = str(settings.value(SITS_SETTING, False)).lower() in ("true", "1")
    return fmt, sits


def save_format(settings, fmt, sits):
    settings.setValue(FORMAT_SETTING, normalize_format(fmt))
    settings.setValue(SITS_SETTING, bool(sits))


@dataclass
class OutputPlan:
    """Files one download writes.

    band_files: (band, path) per band, empty for a multiband GeoTIFF; named
        for sits when that option is on.
    multiband: path of the multiband GeoTIFF, or None.
    vrt: path of the VRT stacking band_files, or None.
    """

    band_files: list = field(default_factory=list)
    multiband: Optional[str] = None
    vrt: Optional[str] = None

    def paths(self):
        out = [path for _band, path in self.band_files]
        out += [p for p in (self.multiband, self.vrt) if p]
        return out

    def missing(self, exists=os.path.isfile):
        return [path for path in self.paths() if not exists(path)]

    def complete(self, exists=os.path.isfile):
        return bool(self.paths()) and not self.missing(exists)


def _suffix(tag):
    return f"_{safe_component(tag)}" if tag else ""


def _bands_tag(bands):
    return "-".join(safe_component(b) for b in bands)


def sits_file_name(collection_id, tag, tile, band, date) -> str:
    """``<collection>_<projection>_<tile>_<band>_<date>.tif`` with no "_" inside a field.

    sits reads it with its default ``parse_info = c("X1", "X2", "tile", "band", "date")``.
    """
    fields = (slug(collection_id, 40), slug(tag or "native", 40), slug(tile, 40), slug(band, 20), str(date))
    return "_".join(fields) + ".tif"


def sits_dir(download_dir, collection_id):
    return os.path.join(download_dir, "downloads", safe_component(collection_id), SITS_DIR)


def _with_format(plan, fmt, bands, band_path, stack_path, vrt_path, sits_path):
    if fmt == MULTIBAND and len(bands) > 1:
        plan.multiband = stack_path
        return plan
    named = sits_path if (fmt == PER_BAND and sits_path is not None) else band_path
    plan.band_files = [(band, named(band)) for band in bands]
    if fmt == PER_BAND_VRT and len(bands) > 1:
        plan.vrt = vrt_path
    return plan


def item_dir(download_dir, collection_id, item_id):
    return os.path.join(download_dir, "downloads", safe_component(collection_id), safe_component(item_id))


def tile_outputs(download_dir, collection_id, item_id, bands, fmt, tag="", sits=False, tile="", date=""):
    """Files written for a STAC item (one tile/scene).

    Native per-band files keep the ``<item>_<band>.tif`` name the VRT builder
    looks up, so a downloaded tile is reused when images are loaded.
    """
    folder = item_dir(download_dir, collection_id, item_id)
    stem = safe_component(item_id)
    suffix = _suffix(tag)

    def band_path(band):
        return os.path.join(folder, f"{stem}_{safe_component(band)}{suffix}.tif")

    def sits_path(band):
        return os.path.join(sits_dir(download_dir, collection_id), sits_file_name(collection_id, tag, tile, band, date))

    return _with_format(
        OutputPlan(),
        normalize_format(fmt),
        list(bands),
        band_path,
        os.path.join(folder, f"{stem}_{_bands_tag(bands)}{suffix}.tif"),
        os.path.join(folder, f"{stem}_{_bands_tag(bands)}{suffix}.vrt"),
        sits_path if sits else None,
    )


def area_dir(download_dir, collection_id, tag_name):
    return os.path.join(download_dir, "downloads", safe_component(collection_id), safe_component(tag_name))


def area_outputs(download_dir, collection_id, area, date, bands, fmt, tag="", sits=False):
    """Files written for a crop or vector-feature mosaic of one date.

    ``area`` is the area tag; everything goes to ``downloads/<collection>/<area>/``.
    """
    folder = area_dir(download_dir, collection_id, area)
    stem = f"{safe_component(area)}_{safe_component(date)}"
    suffix = _suffix(tag)

    def band_path(band):
        return os.path.join(folder, f"{stem}_{safe_component(band)}{suffix}.tif")

    def sits_path(band):
        return os.path.join(sits_dir(download_dir, collection_id), sits_file_name(collection_id, tag, area, band, date))

    return _with_format(
        OutputPlan(),
        normalize_format(fmt),
        list(bands),
        band_path,
        os.path.join(folder, f"{stem}_{_bands_tag(bands)}{suffix}.tif"),
        os.path.join(folder, f"{stem}_{_bands_tag(bands)}{suffix}.vrt"),
        sits_path if sits else None,
    )


def find_area_layer(download_dir, collection_id, area, date, bands, tags=("",), exists=os.path.isfile):
    """Return a downloaded file QGIS can open as one layer for these bands, or None.

    A multiband GeoTIFF or a VRT over per-band files both qualify; a single
    band also matches its per-band GeoTIFF. ``tags`` lists the projections to
    try, in order of preference.
    """
    for tag in tags:
        for fmt in (MULTIBAND, PER_BAND_VRT):
            plan = area_outputs(download_dir, collection_id, area, date, bands, fmt, tag)
            if not plan.complete(exists):
                continue
            if plan.multiband:
                return plan.multiband
            if plan.vrt:
                return plan.vrt
            if len(plan.band_files) == 1:
                return plan.band_files[0][1]
    return None


def find_area_band_files(download_dir, collection_id, area, date, bands, tags=("",), exists=os.path.isfile):
    """Downloaded per-band GeoTIFFs of an area, in ``bands`` order, or None.

    Covers a per-band download without its VRT, under either naming (plain
    or sits), so loading can stack the files already on disk.
    """
    for tag in tags:
        for sits in (False, True):
            plan = area_outputs(download_dir, collection_id, area, date, bands, PER_BAND, tag, sits)
            if plan.band_files and plan.complete(exists):
                return [path for _band, path in plan.band_files]
    return None
