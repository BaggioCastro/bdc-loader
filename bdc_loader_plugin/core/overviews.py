"""Local overviews (.ovr) of remote VRTs.

Decides whether one is worth building, warps the VRT at reduced resolution
with an optional cutline mask, and validates the result against the source.
"""

import math
import os

from osgeo import gdal

from ..logger import error as _log_error
from ..logger import warning as _log_warning
from .cutline import _cutline_in_raster_srs
from .gdal_env import uses_gdal
from .overview_cache import _overview_is_current, _stamp_overview
from .render_ranges import calculate_render_range
from .vrt_builder import vrt_has_direct_remote_source

_OVERVIEW_WARP_MEM = 512 * 1024 * 1024


def _sample_band_signature(dataset, band_no, sample_size=128):
    """Return bounded value statistics used to validate a generated overview."""
    band = dataset.GetRasterBand(band_no)
    width = max(1, min(int(sample_size), dataset.RasterXSize))
    height = max(1, min(int(sample_size), dataset.RasterYSize))
    values = band.ReadAsArray(
        0,
        0,
        dataset.RasterXSize,
        dataset.RasterYSize,
        buf_xsize=width,
        buf_ysize=height,
    )
    if values is None:
        return None

    nodata = band.GetNoDataValue()
    try:
        nodata_value = float(nodata) if nodata is not None else None
    except (TypeError, ValueError):
        nodata_value = None

    valid = []
    flattened = values.ravel() if hasattr(values, "ravel") else values
    for value in flattened:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(number):
            continue
        if nodata_value is not None and math.isfinite(nodata_value) and number == nodata_value:
            continue
        valid.append(number)

    if not valid:
        return {
            "valid_count": 0,
            "nonzero_count": 0,
            "minimum": None,
            "maximum": None,
            "render_range": None,
        }

    return {
        "valid_count": len(valid),
        "nonzero_count": sum(value != 0.0 for value in valid),
        "minimum": min(valid),
        "maximum": max(valid),
        "render_range": calculate_render_range(valid),
    }


def _nodata_matches(source_nodata, overview_nodata):
    if source_nodata is None or overview_nodata is None:
        return source_nodata is None and overview_nodata is None
    try:
        source_value = float(source_nodata)
        overview_value = float(overview_nodata)
    except (TypeError, ValueError):
        return source_nodata == overview_nodata
    if math.isnan(source_value) or math.isnan(overview_value):
        return math.isnan(source_value) and math.isnan(overview_value)
    return source_value == overview_value


@uses_gdal
def _validate_overview(source_path, overview_path, sample_size=128):
    """Validate structure and sampled values before publishing an overview.

    The comparison is intentionally tolerant of small grid differences created
    by gdal.Warp. It rejects the observed failure modes: empty/zero output from
    a varying source and finite but wildly corrupted Float32 values.
    """
    source = overview = None
    try:
        source = gdal.Open(source_path, gdal.GA_ReadOnly)
        overview = gdal.Open(overview_path, gdal.GA_ReadOnly)
        if not source or not overview:
            return False, "source or generated overview could not be reopened"
        if source.RasterCount != overview.RasterCount:
            return False, "band count differs from source"
        if (
            overview.RasterXSize < 1
            or overview.RasterYSize < 1
            or max(overview.RasterXSize, overview.RasterYSize) > 512
        ):
            return False, "generated overview has invalid dimensions"

        for band_no in range(1, source.RasterCount + 1):
            source_band = source.GetRasterBand(band_no)
            overview_band = overview.GetRasterBand(band_no)
            if source_band.DataType != overview_band.DataType:
                return False, f"band {band_no} data type differs from source"
            if not _nodata_matches(source_band.GetNoDataValue(), overview_band.GetNoDataValue()):
                return False, f"band {band_no} nodata differs from source"

            source_sample = _sample_band_signature(source, band_no, sample_size)
            overview_sample = _sample_band_signature(overview, band_no, sample_size)
            if source_sample is None or overview_sample is None:
                return False, f"band {band_no} could not be sampled"

            source_count = source_sample["valid_count"]
            overview_count = overview_sample["valid_count"]
            if source_count and not overview_count:
                return False, f"band {band_no} lost all valid pixels"
            if not source_count:
                if overview_count:
                    return False, f"band {band_no} gained values absent from source sample"
                continue

            source_nonzero_fraction = source_sample["nonzero_count"] / source_count
            if source_nonzero_fraction >= 0.01 and overview_sample["nonzero_count"] == 0:
                return False, f"band {band_no} became all zero"

            source_range = source_sample["render_range"]
            overview_range = overview_sample["render_range"]
            if source_range is not None and overview_range is None:
                return False, f"band {band_no} lost its dynamic range"

            source_abs_max = max(abs(source_sample["minimum"]), abs(source_sample["maximum"]))
            overview_abs_max = max(abs(overview_sample["minimum"]), abs(overview_sample["maximum"]))
            if overview_abs_max > max(1.0, source_abs_max * 1000.0):
                return False, f"band {band_no} contains values far outside the source scale"

            if source_range is not None and overview_range is not None:
                source_span = source_range[1] - source_range[0]
                overview_span = overview_range[1] - overview_range[0]
                if overview_span < source_span / 1000.0 or overview_span > source_span * 1000.0:
                    return False, f"band {band_no} dynamic range is inconsistent with source"

        return True, None
    except Exception as exc:
        return False, str(exc)
    finally:
        source = None
        overview = None


# Above this many pixels per band, generating an overview from sources that
# carry no pyramid costs more than the overview is worth: the warp streams the
# whole raster, and an RGB load does it once per band and item. The limit keeps
# the mid-size scenes that finish inside the phase budget and skips the larger ones.
PYRAMIDLESS_OVERVIEW_MAX_PIXELS = 64_000_000


def overview_streams_full_raster(dataset):
    """Return whether building an overview for *dataset* would stream its
    sources in full, for no benefit worth the wait.

    A COG carries an internal overview pyramid, so GDAL satisfies the
    reduced-resolution read from a small upper level and transfers a few
    hundred KB. A plain GeoTIFF has no pyramid, so the same read decompresses
    every full-resolution block it overlaps — for a striped file (one scanline
    per block) that is the whole file, fetched over HTTP.

    Size is part of the test because a pyramid-less source is only a problem
    once it is big: a 16 Mpx tiled scene warps in well under a second, while a
    228 Mpx striped one takes over a minute per band.

    The overview count propagates from the sources through the VRT band, so
    this is a metadata-only check with no extra request. Block size does not
    propagate (a VRT band always reports its own tiling), which is why the
    pyramid is the signal used here.
    """
    if dataset is None:
        return False
    try:
        if dataset.GetRasterBand(1).GetOverviewCount():
            return False
        return dataset.RasterXSize * dataset.RasterYSize > PYRAMIDLESS_OVERVIEW_MAX_PIXELS
    except Exception:
        return False


@uses_gdal
def remote_vrt_streams_full_raster(vrt_path):
    """Return whether *vrt_path* reads remote sources an overview cannot help.

    Call this from a worker thread: opening the VRT touches the network on a
    cold VSI cache. Used to tell "the overview was skipped because the source
    format cannot support one cheaply" apart from "building it failed", which
    need different advice in the UI.
    """
    if not vrt_has_direct_remote_source(vrt_path):
        return False
    dataset = None
    try:
        dataset = gdal.Open(vrt_path, gdal.GA_ReadOnly)
        return overview_streams_full_raster(dataset)
    except Exception:
        return False
    finally:
        dataset = None


class _OverviewNotNeeded(str):
    """Marker returned by build_overview for a raster small enough to draw
    without an overview: falsy like a failure, but distinguishable from one."""

    def __new__(cls):
        return super().__new__(cls, "")

    def __repr__(self):
        return "OVERVIEW_NOT_NEEDED"


OVERVIEW_NOT_NEEDED = _OverviewNotNeeded()


@uses_gdal
def build_overview(vrt_path, cutline_path=None):
    """Generate a local overview (.ovr) for a remote VRT.

    Creates a compressed GeoTIFF at reduced resolution that QGIS uses
    to render zoom-out without fetching full-res data from all tiles.
    The .ovr is saved next to the source .vrt file.

    When cutline_path is given (shape/crop mode), pixels outside the shape
    are masked to nodata so the zoomed-out preview matches the shape, not
    just its bbox. This never applies to the live full-resolution VRT (see
    _bbox_clip) — gdal.Warp+cutline is markedly more expensive per remote-COG
    read and to construct than a plain BuildVRT reference, which matters for
    interactive rendering but not for a one-time build that already pays for
    a gdal.Warp call. If cutline masking fails (e.g. a CRS edge case with a
    non-standard projection), falls back to the plain unmasked overview
    rather than losing the overview entirely.

    Returns:
        ovr_path on success, OVERVIEW_NOT_NEEDED for a raster of at most
        1024 pixels on its longer side, None on failure.
    """
    ovr_path = vrt_path + ".ovr"
    if _overview_is_current(ovr_path, vrt_path):
        return ovr_path
    tmp_ovr_path = ovr_path + ".tmp.tif"

    try:
        # GDAL automatically attaches an existing external overview when the
        # VRT is opened. Remove stale caches first so they cannot contaminate
        # the newly generated overview.
        for stale in (ovr_path, tmp_ovr_path):
            if os.path.isfile(stale):
                os.remove(stale)

        source = _overview_source(vrt_path)
        if source is None:
            return None
        xsize, ysize, src_xres, src_yres, streams_full_raster = source
        max_dim = max(xsize, ysize)
        if max_dim <= 1024:
            return OVERVIEW_NOT_NEEDED

        # gdal.Warp below reads the source at reduced resolution. With no
        # source pyramid that read expands to the full raster, so a large
        # remote scene would be pulled and decompressed in its entirety over
        # /vsicurl before a single pixel reaches the canvas. Skip the overview
        # and let QGIS render from the VRT, which reads only the blocks the
        # current canvas covers. Downloading the scene first is the supported
        # way to get a fast local layer for these collections.
        if streams_full_raster and vrt_has_direct_remote_source(vrt_path):
            _log_warning(
                f"Skipping overview for {os.path.basename(vrt_path)}: its remote sources have no "
                f"internal overviews and are {xsize}x{ysize}, so building one would download every "
                "full-resolution block. Rendering from the remote VRT instead — download the scene "
                "for a faster local layer."
            )
            return None

        base_opts = _overview_warp_options(src_xres, src_yres, max_dim)
        ds = _warp_masked_overview(tmp_ovr_path, vrt_path, cutline_path, base_opts) if cutline_path else None
        masked = ds is not None
        if not ds:
            ds = gdal.Warp(tmp_ovr_path, vrt_path, options=gdal.WarpOptions(**base_opts))
        if not ds:
            return None
        ds.FlushCache()
        ds = None

        if not _overview_passes_check(vrt_path, tmp_ovr_path, masked):
            return None
        if not _stamp_overview(tmp_ovr_path, vrt_path):
            return None
        os.replace(tmp_ovr_path, ovr_path)
        return ovr_path
    except Exception as e:
        _log_error(f"Overview generation failed for {vrt_path}: {e}")
        return None
    finally:
        if os.path.isfile(tmp_ovr_path):
            try:
                os.remove(tmp_ovr_path)
            except OSError:
                pass


@uses_gdal
def _overview_source(vrt_path):
    """(xsize, ysize, xres, yres, streams_full_raster) of the VRT, or None when it does not open."""
    src_ds = gdal.Open(vrt_path, gdal.GA_ReadOnly)
    if not src_ds:
        return None
    gt = src_ds.GetGeoTransform()
    source = (src_ds.RasterXSize, src_ds.RasterYSize, abs(gt[1]), abs(gt[5]), overview_streams_full_raster(src_ds))
    src_ds = None
    return source


def _overview_warp_options(src_xres, src_yres, max_dim):
    """gdal.Warp keyword options for an overview about 512 pixels on its longer side."""
    factor = max(1, math.ceil(max_dim / 512))
    return dict(
        format="GTiff",
        xRes=src_xres * factor,
        yRes=src_yres * factor,
        resampleAlg="nearest",
        multithread=True,
        warpMemoryLimit=_OVERVIEW_WARP_MEM,
        creationOptions=[
            "COMPRESS=DEFLATE",
            "TILED=YES",
            "BLOCKXSIZE=256",
            "BLOCKYSIZE=256",
            "NUM_THREADS=ALL_CPUS",
        ],
    )


@uses_gdal
def _warp_masked_overview(tmp_ovr_path, vrt_path, cutline_path, base_opts):
    """Warp the overview with pixels outside the cutline set to nodata; None when that fails."""
    matched_cutline = None
    try:
        matched_cutline = _cutline_in_raster_srs(cutline_path, vrt_path)
        masked_opts = gdal.WarpOptions(cutlineDSName=matched_cutline, dstNodata=0, **base_opts)
        return gdal.Warp(tmp_ovr_path, vrt_path, options=masked_opts)
    except Exception as exc:
        _log_warning(f"Cutline-masked overview failed for {vrt_path}, falling back to bbox-only: {exc}")
        return None
    finally:
        if matched_cutline and matched_cutline != cutline_path and os.path.isfile(matched_cutline):
            try:
                os.remove(matched_cutline)
            except OSError:
                pass


@uses_gdal
def _overview_passes_check(vrt_path, tmp_ovr_path, masked):
    """Check the written overview before it replaces the cached one.

    Masking is expected to change band statistics (more nodata), so a masked
    overview gets only a structural check; the statistical comparison of
    _validate_overview would reject a correctly masked one.
    """
    if masked:
        check_ds = gdal.Open(tmp_ovr_path, gdal.GA_ReadOnly)
        structurally_ok = bool(check_ds and check_ds.RasterXSize > 0 and check_ds.RasterYSize > 0)
        check_ds = None
        if not structurally_ok:
            _log_warning(f"Masked overview for {vrt_path} failed structural check. Using the remote VRT instead.")
        return structurally_ok
    valid, reason = _validate_overview(vrt_path, tmp_ovr_path)
    if not valid:
        _log_warning(f"Overview validation failed for {vrt_path}: {reason}. Using the remote VRT instead.")
    return valid
