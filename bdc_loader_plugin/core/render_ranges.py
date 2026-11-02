"""Display ranges and valid-pixel checks.

Sampled from a raster, or from its overview when that overview is current.
"""

import math

from osgeo import gdal

from ..logger import error as _log_error
from ..logger import warning as _log_warning
from .gdal_env import uses_gdal
from .overview_cache import _overview_is_current


def calculate_render_range(values, nodata=None):
    """Return a bounded 2nd/98th-percentile display range for sampled pixels.

    Non-finite and explicit nodata values are ignored. For continuous imagery,
    zero-valued borders/backgrounds are also ignored when they represent at
    least 2% of the sample; small categorical samples retain zero as a class.
    Returns ``None`` when the sample has no usable variation.
    """

    if hasattr(values, "ravel"):
        values = values.ravel()

    nodata_value = None
    try:
        nodata_value = float(nodata) if nodata is not None else None
    except (TypeError, ValueError):
        pass

    valid = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(number):
            continue
        if nodata_value is not None and math.isfinite(nodata_value) and number == nodata_value:
            continue
        valid.append(number)

    if len(valid) < 2:
        return None

    unique_values = set(valid)
    nonzero = [value for value in valid if value != 0.0]
    zero_fraction = 1.0 - (len(nonzero) / len(valid))
    if len(unique_values) > 16 and len(nonzero) >= 20 and zero_fraction >= 0.02:
        valid = nonzero

    valid.sort()
    if valid[0] == valid[-1]:
        return None

    def _percentile(fraction):
        position = (len(valid) - 1) * fraction
        lower = int(math.floor(position))
        upper = int(math.ceil(position))
        if lower == upper:
            return valid[lower]
        weight = position - lower
        return valid[lower] * (1.0 - weight) + valid[upper] * weight

    if len(valid) < 20:
        return valid[0], valid[-1]

    low = _percentile(0.02)
    high = _percentile(0.98)
    if not math.isfinite(low) or not math.isfinite(high) or low >= high:
        low, high = valid[0], valid[-1]
    return (low, high) if low < high else None


# Distinct values up to which a gray-table band is drawn as classes; a
# continuous 8-bit band (a hillshade) has more in its sample.
MAX_PALETTE_CLASSES = 32


class RenderRanges(dict):
    """Per-band display ranges, {band number: (min, max)}.

    ``empty`` is True when every band was sampled and none had a valid pixel,
    so the layer would draw nothing (a scene that touches the area only with
    the empty border around its imagery, for example).

    ``classes`` lists the values found in a single-band raster whose color
    table holds only grays, when there are at most MAX_PALETTE_CLASSES of
    them, else None. BDC class products carry a gray ramp as color table (the
    topodata landform, slope class and curvature class bands), so classes 1
    to 9 are drawn almost black.
    """

    empty = False
    classes = None


def _is_gray_table(band):
    """True when ``band`` has a color table made only of grays (r = g = b)."""
    try:
        table = band.GetColorTable()
        count = int(table.GetCount()) if table is not None else 0
        if count == 0:
            return False
        for i in range(min(count, 256)):
            red, green, blue = tuple(table.GetColorEntry(i)[:3])
            if not red == green == blue:
                return False
        return True
    except Exception:
        return False


@uses_gdal
def _has_gray_table(sample_band, sample_path, vrt_path):
    """Gray color table on the layer's source; the local overview the sample
    may come from is written without a color table."""
    if sample_path == vrt_path:
        return _is_gray_table(sample_band)
    source = None
    try:
        source = gdal.Open(vrt_path, gdal.GA_ReadOnly)
        return source is not None and source.RasterCount == 1 and _is_gray_table(source.GetRasterBand(1))
    except Exception:
        return False
    finally:
        source = None


def _constant_range(values, nodata):
    """(v - 1, v + 1) when every valid sampled pixel holds the same nonzero v.

    A uniform area (a crop inside a saturated cloud, all 1023 on a 10-bit
    sensor) has no range of its own; QGIS then derives a degenerate stretch
    from it and draws the area black. Centred on v it is drawn mid-gray.
    """
    import numpy as np

    flat = np.asarray(values, dtype="float64").ravel()
    keep = np.isfinite(flat) & (flat != 0)
    if nodata is not None:
        keep &= flat != float(nodata)
    found = np.unique(flat[keep])
    if len(found) != 1:
        return None
    value = float(found[0])
    return value - 1.0, value + 1.0


def _class_values(values, nodata):
    import numpy as np

    flat = np.asarray(values).ravel()
    if nodata is not None:
        flat = flat[flat != nodata]
    found = np.unique(flat)
    return [int(v) for v in found[:256]]


def has_valid_pixels(values, nodata=None):
    """True when ``values`` holds a finite value that is neither nodata nor 0."""
    import numpy as np

    arr = np.asarray(values, dtype="float64")
    mask = np.isfinite(arr) & (arr != 0)
    try:
        if nodata is not None and math.isfinite(float(nodata)):
            mask &= arr != float(nodata)
    except (TypeError, ValueError):
        pass
    return bool(mask.any())


def _sample_bands(dataset, sample_size):
    """Yield (band, reduced-resolution values) for every band of ``dataset``."""
    width = max(1, min(int(sample_size), dataset.RasterXSize))
    height = max(1, min(int(sample_size), dataset.RasterYSize))
    for band_no in range(1, dataset.RasterCount + 1):
        band = dataset.GetRasterBand(band_no)
        yield (
            band_no,
            band,
            band.ReadAsArray(0, 0, dataset.RasterXSize, dataset.RasterYSize, buf_xsize=width, buf_ysize=height),
        )


@uses_gdal
def estimate_vrt_render_ranges(vrt_path, sample_size=256):
    """Estimate per-band display ranges from a memory-bounded GDAL sample.

    GDAL performs a reduced-resolution read, allowing remote COG overviews (or
    the local external overview, when present) to satisfy the request. At most
    ``sample_size ** 2`` values are retained per band. The result also says
    whether the sample had no valid pixel at all (RenderRanges.empty).
    """

    overview_path = vrt_path + ".ovr"
    sample_path = overview_path if _overview_is_current(overview_path) else vrt_path
    dataset = None
    ranges = RenderRanges()
    try:
        dataset = gdal.Open(sample_path, gdal.GA_ReadOnly)
        if not dataset:
            return ranges

        read_every_band = dataset.RasterCount > 0
        any_valid = False
        for band_no, band, values in _sample_bands(dataset, sample_size):
            if values is None:
                read_every_band = False
                continue
            nodata = band.GetNoDataValue()
            any_valid = any_valid or has_valid_pixels(values, nodata)
            render_range = calculate_render_range(values, nodata) or _constant_range(values, nodata)
            if render_range is not None:
                ranges[band_no] = render_range
            if dataset.RasterCount == 1 and _has_gray_table(band, sample_path, vrt_path):
                classes = _class_values(values, nodata)
                if 0 < len(classes) <= MAX_PALETTE_CLASSES:
                    ranges.classes = classes
        ranges.empty = read_every_band and not any_valid
        return ranges
    except Exception as exc:
        _log_error(f"Render range sampling failed for {vrt_path}: {exc}")
        return RenderRanges()
    finally:
        dataset = None


@uses_gdal
def raster_has_valid_pixels(path, sample_size=256):
    """True/False when a reduced-resolution sample of ``path`` has/lacks a valid
    pixel in any band; None when the file cannot be read."""
    dataset = None
    try:
        dataset = gdal.Open(path, gdal.GA_ReadOnly)
        if not dataset:
            return None
        for _band_no, band, values in _sample_bands(dataset, sample_size):
            if values is not None and has_valid_pixels(values, band.GetNoDataValue()):
                return True
        return False
    except Exception as exc:
        _log_warning(f"Could not sample {path}: {exc}")
        return None
    finally:
        dataset = None
