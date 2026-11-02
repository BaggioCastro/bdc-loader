"""GeoTIFF exports of downloaded data.

A band stack, one file per band with its VRT, and crops by bbox or by cutline.
Each output is written to a .part file and renamed when complete.
"""

import os
import uuid
import xml.etree.ElementTree as ET

from osgeo import gdal, osr

from ..logger import error as _log_error
from ..logger import warning as _log_warning
from .cutline import _cutline_in_raster_srs
from .gdal_env import uses_gdal


def _remove_tif_sidecars(path):
    """Remove GDAL sidecars (external overview / PAM stats / mask) that may sit
    beside a GeoTIFF at *path*, ignoring ones that aren't there. The main file
    is handled separately (os.remove on failure, os.replace on success)."""
    for sidecar in (path + ".aux.xml", path + ".ovr", path + ".msk"):
        try:
            os.remove(sidecar)
        except OSError:
            pass


def _remove_geotiff_artifacts(path):
    """Remove a partial GeoTIFF at *path* and any GDAL sidecars beside it,
    ignoring files that aren't there. Used to clean up the ``.part`` temp on
    every failed/cancelled export path."""
    try:
        os.remove(path)
    except OSError:
        pass
    _remove_tif_sidecars(path)


@uses_gdal
def _effective_dst_srs(dst_srs, src_path):
    """Return *dst_srs*, or None when it names the CRS the source already uses.

    Warping a raster into its own projection costs a full resample and changes
    nothing, so an output CRS that matches the source is dropped and the warp
    stays on the untouched native path. Anything that cannot be compared (no
    projection on the source, an SRS string GDAL will not parse) is passed
    through unchanged and left for gdal.Warp to judge.
    """
    if not dst_srs:
        return None
    try:
        target = osr.SpatialReference()
        target.SetFromUserInput(dst_srs)
        src_ds = gdal.Open(src_path, gdal.GA_ReadOnly)
        if not src_ds:
            return dst_srs
        src_wkt = src_ds.GetProjection()
        src_ds = None
        if not src_wkt:
            return dst_srs
        source = osr.SpatialReference()
        source.ImportFromWkt(src_wkt)
        return None if target.IsSame(source) else dst_srs
    except (RuntimeError, TypeError, ValueError):
        return dst_srs


_GEOTIFF_CREATION_OPTIONS = [
    "COMPRESS=DEFLATE",
    "TILED=YES",
    "BLOCKXSIZE=256",
    "BLOCKYSIZE=256",
    "NUM_THREADS=ALL_CPUS",
    "BIGTIFF=IF_SAFER",
]


def _describe_bands(ds, band_names):
    """Name each band; a three-band file is also marked red, green, blue."""
    if not band_names:
        return
    names = list(band_names)
    rgb = ds.RasterCount == 3 and len(names) == 3
    color = (gdal.GCI_RedBand, gdal.GCI_GreenBand, gdal.GCI_BlueBand)
    for index in range(1, min(ds.RasterCount, len(names)) + 1):
        band = ds.GetRasterBand(index)
        band.SetDescription(str(names[index - 1]))
        if rgb:
            band.SetColorInterpretation(color[index - 1])
        elif ds.RasterCount == 1:
            band.SetColorInterpretation(gdal.GCI_GrayIndex)


@uses_gdal
def _build_internal_overviews(ds, dst_path):
    """Add an internal overview pyramid, so QGIS draws zoomed-out views from it
    instead of resampling the full resolution on every redraw."""
    try:
        max_dim = max(ds.RasterXSize, ds.RasterYSize)
        levels = []
        level = 2
        while max_dim // level > 256:
            levels.append(level)
            level *= 2
        if levels:
            gdal.SetConfigOption("COMPRESS_OVERVIEW", "DEFLATE")
            try:
                ds.BuildOverviews("NEAREST", levels)
            finally:
                gdal.SetConfigOption("COMPRESS_OVERVIEW", None)
    except Exception as e:
        _log_warning(f"Overview build skipped for {dst_path}: {e}")


def _gdal_progress_callback(progress_cb, cancel_check):
    if not (progress_cb or cancel_check):
        return None

    def _callback(complete, _message, _cb_data):
        if progress_cb:
            progress_cb(complete)
        return 0 if (cancel_check and cancel_check()) else 1

    return _callback


@uses_gdal
def export_stack_geotiff(src_paths, dst_path, band_names=None, dst_srs=None, progress_cb=None, cancel_check=None):
    """Write ``src_paths`` (one band each) as one GeoTIFF, optionally reprojected.

    Bands of different resolutions are resampled to the finest one. With a
    single source this is a plain copy or reprojection of that band. The
    output goes to ``<dst_path>.part`` first and replaces dst_path only when
    complete, like export_masked_geotiff.

    Returns:
        (True, dst_path) on success, (False, error_message) on failure.
    """
    tmp_path = dst_path + ".part"
    stack_path = f"/vsimem/bdc_stack_{uuid.uuid4().hex}.vrt"
    try:
        sources = list(src_paths)
        if len(sources) > 1:
            gdal.BuildVRT(
                stack_path,
                sources,
                options=gdal.BuildVRTOptions(separate=True, resolution="highest", resampleAlg="nearest"),
            )
            src = stack_path
        else:
            src = sources[0]
        warp_kwargs = dict(
            format="GTiff",
            multithread=True,
            warpMemoryLimit=512 * 1024 * 1024,
            creationOptions=_GEOTIFF_CREATION_OPTIONS,
            callback=_gdal_progress_callback(progress_cb, cancel_check),
        )
        target_srs = _effective_dst_srs(dst_srs, src)
        if target_srs:
            warp_kwargs["dstSRS"] = target_srs
        ds = gdal.Warp(tmp_path, src, options=gdal.WarpOptions(**warp_kwargs))
        if not ds:
            _remove_geotiff_artifacts(tmp_path)
            return False, "gdal.Warp returned no dataset"
        if cancel_check and cancel_check():
            ds = None
            _remove_geotiff_artifacts(tmp_path)
            return False, "export cancelled"
        _describe_bands(ds, band_names)
        ds.FlushCache()
        _build_internal_overviews(ds, dst_path)
        ds = None
        os.replace(tmp_path, dst_path)
        _remove_tif_sidecars(tmp_path)
        return True, dst_path
    except Exception as e:
        _log_error(f"GeoTIFF export failed for {dst_path}: {e}")
        _remove_geotiff_artifacts(tmp_path)
        return False, str(e)
    finally:
        try:
            gdal.Unlink(stack_path)
        except Exception:
            pass


@uses_gdal
def split_bands(src_path, band_paths, band_names=None):
    """Write band i of ``src_path`` to ``band_paths[i]``, one GeoTIFF each.

    Each file is written to ``<path>.part`` and renamed when complete. Returns
    (True, band_paths) or (False, error_message); on failure no partial file
    is left at any destination.
    """
    names = list(band_names or [])
    written = []
    try:
        for index, path in enumerate(band_paths, start=1):
            tmp_path = path + ".part"
            ds = gdal.Translate(
                tmp_path,
                src_path,
                options=gdal.TranslateOptions(
                    format="GTiff", bandList=[index], creationOptions=_GEOTIFF_CREATION_OPTIONS
                ),
            )
            if not ds:
                _remove_geotiff_artifacts(tmp_path)
                raise RuntimeError(f"gdal.Translate returned no dataset for band {index}")
            _describe_bands(ds, names[index - 1 : index])
            ds.FlushCache()
            _build_internal_overviews(ds, path)
            ds = None
            os.replace(tmp_path, path)
            _remove_tif_sidecars(tmp_path)
            written.append(path)
        return True, list(band_paths)
    except Exception as e:
        _log_error(f"Band split failed for {src_path}: {e}")
        for path in band_paths:
            _remove_geotiff_artifacts(path + ".part")
        return False, str(e)


@uses_gdal
def write_band_vrt(vrt_path, band_paths, band_names=None):
    """Write a VRT stacking ``band_paths`` (one band each) with paths relative to it.

    The VRT sits beside the files, so the folder can be moved as a whole.
    Returns (True, vrt_path) or (False, error_message).
    """
    tmp_path = vrt_path + ".part"
    try:
        ds = gdal.BuildVRT(
            tmp_path,
            [os.path.abspath(p) for p in band_paths],
            options=gdal.BuildVRTOptions(separate=True, resolution="highest", resampleAlg="nearest"),
        )
        if not ds:
            return False, "gdal.BuildVRT returned no dataset"
        _describe_bands(ds, band_names)
        ds = None
        folder = os.path.dirname(os.path.abspath(vrt_path))
        tree = ET.parse(tmp_path)
        for node in tree.getroot().iter("SourceFilename"):
            source = node.text or ""
            if node.get("relativeToVRT") == "1" or not os.path.isabs(source):
                continue
            relative = os.path.relpath(source, folder)
            if not relative.startswith(".."):
                node.text = relative.replace(os.sep, "/")
                node.set("relativeToVRT", "1")
        tree.write(tmp_path)
        os.replace(tmp_path, vrt_path)
        return True, vrt_path
    except Exception as e:
        _log_error(f"VRT write failed for {vrt_path}: {e}")
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return False, str(e)


@uses_gdal
def _bbox_envelope(bbox, target_wkt, steps=50):
    """Envelope, in ``target_wkt``, of a lon/lat bbox whose edges are densified
    so a curved image of a straight edge is fully covered."""
    source = osr.SpatialReference()
    source.ImportFromEPSG(4326)
    target = osr.SpatialReference()
    target.ImportFromWkt(target_wkt)
    for srs in (source, target):
        if hasattr(srs, "SetAxisMappingStrategy"):
            srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    transform = osr.CoordinateTransformation(source, target)
    xmin, ymin, xmax, ymax = (float(v) for v in bbox)
    points = []
    for i in range(steps + 1):
        t = i / steps
        x = xmin + (xmax - xmin) * t
        y = ymin + (ymax - ymin) * t
        points += [(x, ymin), (x, ymax), (xmin, y), (xmax, y)]
    xs, ys = [], []
    for lon, lat in points:
        px, py, *_rest = transform.TransformPoint(lon, lat)
        xs.append(px)
        ys.append(py)
    return min(xs), min(ys), max(xs), max(ys)


@uses_gdal
def export_bbox_geotiff(vrt_path, bbox, dst_path, progress_cb=None, cancel_check=None, dst_srs=None, band_names=None):
    """Cut a lon/lat ``bbox`` out of ``vrt_path`` as a rectangle with straight edges.

    A lon/lat box drawn on the map is a true rectangle only in lon/lat; in a
    projected grid (BDC Albers, UTM) it turns into a slightly rotated
    quadrilateral, and masking along it leaves stair-stepped edges and nodata
    corners. Instead, this writes the rectangle of the output projection that
    covers the box:

    - output in WGS 84: exactly the box;
    - output in the source projection: the covering rectangle snapped to the
      source pixel grid, so every pixel is an original one (no resampling);
    - any other projection: the covering rectangle in that projection.

    Pixels with no source data stay nodata (0). Written through
    ``<dst_path>.part`` like export_masked_geotiff.

    Returns:
        (True, dst_path) on success, (False, error_message) on failure.
    """
    tmp_path = dst_path + ".part"
    try:
        src = gdal.Open(vrt_path)
        if src is None:
            return False, f"cannot open {vrt_path}"
        src_wkt = src.GetProjection()
        gt = src.GetGeoTransform()
        src = None
        target_srs = _effective_dst_srs(dst_srs, vrt_path)
        warp_kwargs = dict(
            format="GTiff",
            dstNodata=0,
            multithread=True,
            warpMemoryLimit=512 * 1024 * 1024,
            creationOptions=_GEOTIFF_CREATION_OPTIONS,
            callback=_gdal_progress_callback(progress_cb, cancel_check),
        )
        if target_srs:
            target = osr.SpatialReference()
            target.SetFromUserInput(target_srs)
            warp_kwargs["dstSRS"] = target_srs
            warp_kwargs["outputBounds"] = _bbox_envelope(bbox, target.ExportToWkt())
        else:
            warp_kwargs["outputBounds"] = _bbox_envelope(bbox, src_wkt)
            warp_kwargs["xRes"] = abs(gt[1])
            warp_kwargs["yRes"] = abs(gt[5])
            warp_kwargs["targetAlignedPixels"] = True
        ds = gdal.Warp(tmp_path, vrt_path, options=gdal.WarpOptions(**warp_kwargs))
        if not ds:
            _remove_geotiff_artifacts(tmp_path)
            return False, "gdal.Warp returned no dataset"
        if cancel_check and cancel_check():
            ds = None
            _remove_geotiff_artifacts(tmp_path)
            return False, "export cancelled"
        _describe_bands(ds, band_names)
        ds.FlushCache()
        _build_internal_overviews(ds, dst_path)
        ds = None
        os.replace(tmp_path, dst_path)
        _remove_tif_sidecars(tmp_path)
        return True, dst_path
    except Exception as e:
        _log_error(f"Rectangle export failed for {vrt_path}: {e}")
        _remove_geotiff_artifacts(tmp_path)
        return False, str(e)


@uses_gdal
def export_masked_geotiff(
    vrt_path, cutline_path, dst_path, progress_cb=None, cancel_check=None, dst_srs=None, band_names=None
):
    """Materialize *vrt_path* to a real GeoTIFF with pixels outside the shape
    set to nodata (0), reading directly from whatever vrt_path references —
    local files or a remote COG. GDAL's own windowed /vsicurl/ reads fetch
    only the byte ranges the cropped output window needs, so this is cheap
    even when vrt_path points straight at remote data — no separate whole-file
    download is required first.

    The output is written to a sibling ``<dst_path>.part`` and moved onto
    dst_path with os.replace only after every handle is released and the
    export finished. A failed, cancelled, or crashed run therefore never
    leaves a partial file at dst_path — the caller's "already downloaded"
    check keys off dst_path existing, so a partial there would be mistaken
    for a finished download — and the temp is removed on every error path. An
    existing valid dst_path is replaced only once the new file is complete.

    dst_srs, if given, is the output projection (anything gdal.Warp accepts as
    dstSRS: "EPSG:4326", WKT, PROJ). It is dropped when it names the CRS the
    source is already in, so the native grid — or a project CRS that happens to
    equal it — resamples nothing.

    The cutline is applied with CUTLINE_ALL_TOUCHED, so a pixel the boundary
    only crosses is kept rather than dropped. Under the shape overlay QGIS
    draws on top of the layer, a centre-based mask leaves that partial ring as
    stair-stepped transparent notches just inside the outline; keeping it means
    the raster always reaches past the line. No pixel value is altered.

    progress_cb(fraction), if given, receives GDAL's own 0.0-1.0 Warp
    progress; called from whatever thread runs this function, so callers on
    a background thread should aggregate into something thread-safe (e.g.
    download_engine.ProgressCounter) rather than touching UI state directly.
    cancel_check(), if given, is polled the same way; returning True aborts
    the Warp and this returns (False, <abort message>).

    band_names, if given, become the band descriptions; three bands are also
    marked red, green and blue so QGIS opens the file as a color composite.

    Returns:
        (True, dst_path) on success, (False, error_message) on failure.
    """
    matched_cutline = None
    tmp_path = dst_path + ".part"
    try:
        matched_cutline = _cutline_in_raster_srs(cutline_path, vrt_path)

        warp_kwargs = dict(
            format="GTiff",
            cutlineDSName=matched_cutline,
            cropToCutline=True,
            dstNodata=0,
            multithread=True,
            warpMemoryLimit=512 * 1024 * 1024,
            creationOptions=_GEOTIFF_CREATION_OPTIONS,
            # A warp option string rather than a WarpOptions keyword: older
            # GDAL Python bindings are missing several of those keywords, while
            # the option strings have been accepted for far longer.
            warpOptions=["CUTLINE_ALL_TOUCHED=TRUE"],
            callback=_gdal_progress_callback(progress_cb, cancel_check),
        )
        target_srs = _effective_dst_srs(dst_srs, vrt_path)
        if target_srs:
            warp_kwargs["dstSRS"] = target_srs

        w_opts = gdal.WarpOptions(**warp_kwargs)
        ds = gdal.Warp(tmp_path, vrt_path, options=w_opts)
        if not ds:
            _remove_geotiff_artifacts(tmp_path)
            return False, "gdal.Warp returned no dataset"
        # GDAL may hand back a partial dataset even when the progress callback
        # aborted; check explicitly so a cancelled crop never reaches dst_path.
        if cancel_check and cancel_check():
            ds = None
            _remove_geotiff_artifacts(tmp_path)
            return False, "export cancelled"
        _describe_bands(ds, band_names)
        ds.FlushCache()
        _build_internal_overviews(ds, dst_path)
        ds = None
        os.replace(tmp_path, dst_path)
        _remove_tif_sidecars(tmp_path)
        return True, dst_path
    except Exception as e:
        _log_error(f"Masked GeoTIFF export failed for {vrt_path}: {e}")
        _remove_geotiff_artifacts(tmp_path)
        return False, str(e)
    finally:
        if matched_cutline and matched_cutline != cutline_path and os.path.isfile(matched_cutline):
            try:
                os.remove(matched_cutline)
            except OSError:
                pass
