"""VRT composition for a load task, without Qt.

Builds the VRT of one task from local files or /vsicurl/ URLs: a per-band
mosaic stacked into RGB, composed in /vsimem/ and published as a flat VRT,
clipped to the bbox of an area and given an area mask. Also checks whether a
local raster can be reused and whether a VRT reads remote sources.
"""

import hashlib
import os
import re
import threading
import uuid
import xml.etree.ElementTree as ET
from copy import deepcopy

from osgeo import gdal, ogr

from ..logger import warning as _log_warning
from .cutline import _aligned_clip_bounds, _bbox_clip, _cutline_in_raster_srs
from .gdal_env import uses_gdal
from .layer_names import _UNSAFE_FILENAME_CHARS
from .overview_cache import _file_digest

_VRT_RASTER_BAND_XML = re.compile(r"<VRTRasterBand\b.*?</VRTRasterBand>", re.DOTALL)
_VRT_BAND_NUMBER_ATTR = re.compile(r'(<VRTRasterBand\b[^>]*\bband=")[^"]*(")')
_VRT_COLOR_INTERP_XML = re.compile(r"\s*<ColorInterp>.*?</ColorInterp>")


@uses_gdal
def is_valid_local_raster(path, opener=None):
    """Return whether *path* is a finished, readable raster safe to reuse
    instead of downloading it again.

    A local file counts as reusable only when every check passes:
      - it exists and is a regular file;
      - its size is greater than zero;
      - no sibling ``<path>.part`` temp exists (a download/export writes to
        ``.part`` and renames on success, so a lingering ``.part`` means the
        final file is unfinished or a write is in progress);
      - GDAL opens it;
      - both raster dimensions are greater than zero;
      - it reports at least one band and band 1 is accessible.

    Any failing check makes the file count as not-yet-downloaded, so the caller
    fetches it again. Nothing is deleted here — an invalid file is simply not
    reused. ``opener`` defaults to ``gdal.Open`` and is injected only by tests
    that run without a real GDAL; it is called as ``opener(path, mode)``.
    """
    try:
        if not os.path.isfile(path):
            return False
        if os.path.getsize(path) <= 0:
            return False
        if os.path.exists(path + ".part"):
            return False
    except OSError:
        return False

    open_raster = opener or gdal.Open
    dataset = None
    try:
        dataset = open_raster(path, gdal.GA_ReadOnly)
        if dataset is None:
            return False
        if dataset.RasterXSize <= 0 or dataset.RasterYSize <= 0:
            return False
        if dataset.RasterCount < 1:
            return False
        return dataset.GetRasterBand(1) is not None
    except Exception:
        return False
    finally:
        dataset = None


def vrt_has_remote_source(vrt_path, max_depth=3):
    """Check if a VRT references remote COGs, directly or via intermediate VRTs.

    Follows VRT chains up to *max_depth* levels to detect /vsicurl/ sources
    hidden behind intermediate local VRTs (e.g. shape mosaic pipelines).
    """
    try:
        with open(vrt_path, "r") as f:
            content = f.read(16384)
        if "/vsicurl/" in content:
            return True
        if max_depth <= 0:
            return False
        # Follow local VRT references one level deeper
        base_dir = os.path.dirname(vrt_path)
        import re as _re

        for ref in _re.findall(r"<SourceFilename[^>]*>([^<]+\.vrt)</SourceFilename>", content):
            child = ref if os.path.isabs(ref) else os.path.join(base_dir, ref)
            if os.path.isfile(child) and vrt_has_remote_source(child, max_depth - 1):
                return True
        return False
    except Exception:
        return False


def vrt_sources_match(vrt_path, hrefs):
    """Return whether the VRT at *vrt_path* already references exactly *hrefs*.

    Rebuilding a VRT whose sources did not change costs a remote open per band
    and throws away a layer QGIS has already rendered. The one change worth
    rebuilding for is a source that moved from /vsicurl/ to a finished
    download, which this comparison catches because the paths differ.
    """
    if not os.path.isfile(vrt_path):
        return False
    try:
        # Parsed straight off disk rather than through gdal.Open, which would
        # open every remote source just to answer "did anything change?".
        root = ET.parse(vrt_path).getroot()
        existing = [node.text for node in root.iter("SourceFilename") if node.text]
        return existing == list(hrefs)
    except Exception:
        return False


def vrt_has_direct_remote_source(vrt_path):
    """Check if a VRT directly contains /vsicurl/ references (no chain following).

    Use this for operations that would be too expensive on chained VRTs
    (e.g. overview generation via gdal.Warp).
    """
    try:
        with open(vrt_path, "r", encoding="utf-8", errors="replace") as f:
            return "/vsicurl/" in f.read()
    except Exception:
        return False


def _vsimem_vrt_path(label):
    """Return a collision-resistant GDAL in-memory VRT path."""
    safe_label = _UNSAFE_FILENAME_CHARS.sub("_", str(label))[:48]
    return f"/vsimem/bdc_loader_{uuid.uuid4().hex}_{safe_label}.vrt"


@uses_gdal
def _unlink_vsimem(paths):
    for path in paths:
        try:
            gdal.Unlink(path)
        except Exception:
            pass


@uses_gdal
def _vrt_xml_root(path):
    dataset = gdal.Open(path, gdal.GA_ReadOnly)
    if not dataset:
        raise RuntimeError(f"Could not reopen VRT: {path}")
    metadata = dataset.GetMetadata("xml:VRT")
    if not metadata:
        dataset = None
        raise RuntimeError(f"VRT XML metadata is unavailable: {path}")
    root = ET.fromstring(metadata[0])
    return dataset, root


@uses_gdal
def _grid_signature(dataset):
    return (
        dataset.RasterXSize,
        dataset.RasterYSize,
        tuple(dataset.GetGeoTransform()),
        dataset.GetProjection(),
    )


def _target_grid_kwargs(dataset):
    geotransform = dataset.GetGeoTransform()
    xmin = geotransform[0]
    ymax = geotransform[3]
    xmax = xmin + dataset.RasterXSize * geotransform[1]
    ymin = ymax + dataset.RasterYSize * geotransform[5]
    return {
        "outputBounds": [xmin, ymin, xmax, ymax],
        "xRes": abs(geotransform[1]),
        "yRes": abs(geotransform[5]),
        "resolution": "user",
    }


def _publish_vrt_bytes(xml_bytes, final_path):
    """Atomically publish VRT bytes after rejecting transient RAM sources."""
    if b"/vsimem/" in xml_bytes:
        raise RuntimeError("Final VRT still references transient /vsimem/ data")

    part_path = f"{final_path}.{uuid.uuid4().hex}.part.vrt"
    try:
        with open(part_path, "wb") as stream:
            stream.write(xml_bytes)
        os.replace(part_path, final_path)
    finally:
        try:
            if os.path.exists(part_path):
                os.remove(part_path)
        except OSError:
            pass


def _publish_vrt_xml(root, final_path):
    """Atomically publish an XML tree as a persistent VRT."""
    _publish_vrt_bytes(
        ET.tostring(root, encoding="utf-8", xml_declaration=True),
        final_path,
    )


def _publish_same_grid_vrt(band_xml, final_path):
    """Combine one-band VRT documents without another GDAL stack file.

    This fast path applies only when all band mosaics have the same grid.
    Their source nodes already point directly at the original rasters, so
    splicing the band elements keeps the final VRT persistent after /vsimem/
    cleanup and avoids XML tree reconstruction for large mosaics.
    """
    first_match = _VRT_RASTER_BAND_XML.search(band_xml[0])
    if first_match is None:
        raise RuntimeError("Per-band VRT XML has no raster band")

    bands = []
    for index, xml_text in enumerate(band_xml, 1):
        match = _VRT_RASTER_BAND_XML.search(xml_text)
        if match is None:
            raise RuntimeError("Per-band VRT XML has no raster band")
        band_text = _VRT_COLOR_INTERP_XML.sub("", match.group(0))
        band_text = _VRT_BAND_NUMBER_ATTR.sub(
            lambda found: f"{found.group(1)}{index}{found.group(2)}",
            band_text,
            count=1,
        )
        bands.append(band_text)

    combined = band_xml[0][: first_match.start()] + "\n".join(bands) + band_xml[0][first_match.end() :]
    _publish_vrt_bytes(combined.encode("utf-8"), final_path)


@uses_gdal
def _publish_direct_vrt(final_path, sources, options):
    """Build a self-contained VRT on disk and atomically publish it."""
    part_path = f"{final_path}.{uuid.uuid4().hex}.part.vrt"
    try:
        dataset = gdal.BuildVRT(part_path, sources, options=options)
        if not dataset:
            return False
        dataset = None
        root = _vrt_xml_root(part_path)[1]
        if b"/vsimem/" in ET.tostring(root, encoding="utf-8"):
            raise RuntimeError("Final VRT still references transient /vsimem/ data")
        os.replace(part_path, final_path)
        return True
    finally:
        try:
            if os.path.exists(part_path):
                os.remove(part_path)
        except OSError:
            pass


def _build_grouped_vrt_vsimem(task, cutline):
    """Compose per-band mosaics in RAM and publish a persistent flat VRT.

    GDAL's normal stacked VRT contains references to the intermediate VRT
    filenames. Those references would become invalid when /vsimem/ is cleaned
    up, so the final XML copies direct source nodes from aligned per-band VRTs.
    Any failure returns False and lets the caller retry the original disk
    pipeline.
    """
    memory_paths = []
    band_datasets = []
    try:
        resample = "cubic" if task["mixed_res"] else "nearest"
        mosaics = _band_mosaics_vsimem(task["href_groups"], resample, memory_paths)
        if mosaics is None:
            return False
        band_vrts, band_datasets, band_xml = mosaics

        band_signatures = [_grid_signature(dataset) for dataset in band_datasets]
        if not cutline and all(signature == band_signatures[0] for signature in band_signatures[1:]):
            _publish_same_grid_vrt(band_xml, task["vrt_path"])
            return True

        target_path = _stacked_target_vsimem(band_vrts, cutline, task["mixed_res"], resample, memory_paths)
        if target_path is None:
            return False
        target_dataset, target_root = _vrt_xml_root(target_path)
        target_bands = list(target_root.findall("VRTRasterBand"))
        for band_node in target_bands:
            target_root.remove(band_node)

        direct_band_paths = _bands_on_target_grid(
            task["href_groups"], band_vrts, band_datasets, target_dataset, resample, memory_paths
        )
        if direct_band_paths is None or not _append_direct_bands(target_root, target_bands, direct_band_paths):
            return False

        _publish_vrt_xml(target_root, task["vrt_path"])
        target_dataset = None
        return True
    except Exception as exc:
        _log_warning(f"In-memory VRT composition failed; retrying on disk: {exc}")
        return False
    finally:
        band_datasets.clear()
        _unlink_vsimem(memory_paths)


@uses_gdal
def _band_mosaics_vsimem(href_groups, resample, memory_paths):
    """One in-memory mosaic VRT per band: (paths, open datasets, XML), or None on failure.

    The datasets stay open while the caller uses them, because closing one
    releases its /vsimem/ content.
    """
    band_vrts, band_datasets, band_xml = [], [], []
    for index, group_sources in enumerate(href_groups, 1):
        band_path = _vsimem_vrt_path(f"band_{index}_mosaic")
        memory_paths.append(band_path)
        options = gdal.BuildVRTOptions(resampleAlg=resample, allowProjectionDifference=True)
        dataset = gdal.BuildVRT(band_path, group_sources, options=options)
        if not dataset:
            return None
        metadata = dataset.GetMetadata("xml:VRT")
        if not metadata:
            return None
        dataset.FlushCache()
        band_vrts.append(band_path)
        band_datasets.append(dataset)
        band_xml.append(metadata[0])
    return band_vrts, band_datasets, band_xml


@uses_gdal
def _stacked_target_vsimem(band_vrts, cutline, mixed_res, resample, memory_paths):
    """Stack the band mosaics in memory and clip the stack to the cutline bbox when given.

    Returns the path whose grid the final VRT uses, or None on failure.
    """
    if mixed_res:
        stack_options = gdal.BuildVRTOptions(resampleAlg="cubic", separate=True, resolution="highest")
    else:
        stack_options = gdal.BuildVRTOptions(resampleAlg="nearest", separate=True)
    stack_path = _vsimem_vrt_path("stack")
    memory_paths.append(stack_path)
    stack = gdal.BuildVRT(stack_path, band_vrts, options=stack_options)
    if not stack:
        return None
    stack = None
    if not cutline:
        return stack_path

    target_path = _vsimem_vrt_path("bbox_clip")
    memory_paths.append(target_path)
    if not _bbox_clip(cutline, stack_path, target_path, resample=resample, mixed_res=mixed_res):
        return None
    return target_path


@uses_gdal
def _bands_on_target_grid(href_groups, band_vrts, band_datasets, target_dataset, resample, memory_paths):
    """Path of each band mosaic on the target grid, rebuilding the bands whose grid differs.

    Returns None when a rebuild fails.
    """
    target_signature = _grid_signature(target_dataset)
    direct_band_paths = []
    for index, (group_sources, band_path, band_dataset) in enumerate(zip(href_groups, band_vrts, band_datasets), 1):
        if _grid_signature(band_dataset) == target_signature:
            direct_band_paths.append(band_path)
            continue
        direct_path = _vsimem_vrt_path(f"band_{index}_aligned")
        memory_paths.append(direct_path)
        options_kwargs = _target_grid_kwargs(target_dataset)
        options_kwargs.update({"resampleAlg": resample, "allowProjectionDifference": True})
        aligned = gdal.BuildVRT(direct_path, group_sources, options=gdal.BuildVRTOptions(**options_kwargs))
        if not aligned:
            return None
        aligned = None
        direct_band_paths.append(direct_path)
    return direct_band_paths


def _append_direct_bands(target_root, target_bands, direct_band_paths):
    """Copy the first band node of each aligned VRT into the target XML.

    Each copy takes its band number from its position and the ColorInterp of
    the target band it replaces. Returns False when a VRT has no band.
    """
    for index, direct_path in enumerate(direct_band_paths, 1):
        _, direct_root = _vrt_xml_root(direct_path)
        direct_band = direct_root.find("VRTRasterBand")
        if direct_band is None:
            return False
        band_node = deepcopy(direct_band)
        band_node.set("band", str(index))

        for color_node in list(band_node.findall("ColorInterp")):
            band_node.remove(color_node)
        if index <= len(target_bands):
            target_color = target_bands[index - 1].find("ColorInterp")
            if target_color is not None:
                band_node.append(deepcopy(target_color))

        target_root.append(band_node)
    return True


@uses_gdal
def _build_cutline_vrt_vsimem(task, input_sources, options):
    """Use a RAM probe VRT, then publish a direct-source cropped VRT."""
    memory_path = _vsimem_vrt_path("cutline_source")
    try:
        dataset = gdal.BuildVRT(memory_path, input_sources, options=options)
        if not dataset:
            return False
        dataset = None
        bounds = _aligned_clip_bounds(task["cutline_path"], memory_path)
        if bounds is None:
            return False

        kwargs = {
            "outputBounds": list(bounds),
            "resampleAlg": "cubic" if task.get("mixed_res", False) else "nearest",
        }
        if task["separate"]:
            kwargs["separate"] = True
        if task.get("mixed_res", False):
            kwargs["resolution"] = "highest"
        return _publish_direct_vrt(
            task["vrt_path"],
            input_sources,
            gdal.BuildVRTOptions(**kwargs),
        )
    except Exception as exc:
        _log_warning(f"In-memory cutline VRT failed; retrying on disk: {exc}")
        return False
    finally:
        _unlink_vsimem([memory_path])


_mask_locks = {}
_mask_locks_guard = threading.Lock()


def _mask_lock(path):
    with _mask_locks_guard:
        return _mask_locks.setdefault(path, threading.Lock())


@uses_gdal
def _rasterize_area_mask(cutline_path, vrt_path, mask_path, width, height, geotransform, projection):
    """Write a 0/255 byte mask of the cutline on the VRT's pixel grid, with overviews."""
    matched = _cutline_in_raster_srs(cutline_path, vrt_path)
    tmp = mask_path + ".part"
    try:
        driver = gdal.GetDriverByName("GTiff")
        ds = driver.Create(
            tmp,
            width,
            height,
            1,
            gdal.GDT_Byte,
            ["COMPRESS=DEFLATE", "TILED=YES", "BLOCKXSIZE=512", "BLOCKYSIZE=512", "BIGTIFF=IF_SAFER"],
        )
        ds.SetGeoTransform(geotransform)
        ds.SetProjection(projection)
        cut_ds = ogr.Open(matched)
        # All touched: a pixel the boundary crosses stays visible, like the
        # downloaded crop (see export_masked_geotiff).
        gdal.RasterizeLayer(ds, [1], cut_ds.GetLayer(), burn_values=[255], options=["ALL_TOUCHED=TRUE"])
        cut_ds = None
        factors = []
        factor = 2
        while max(width, height) // factor >= 256:
            factors.append(factor)
            factor *= 2
        if factors:
            ds.BuildOverviews("NEAREST", factors)
        ds = None
        os.replace(tmp, mask_path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
        if matched != cutline_path and os.path.isfile(matched):
            try:
                os.remove(matched)
            except OSError:
                pass


@uses_gdal
def attach_area_mask(vrt_path, cutline_path, mask_dir):
    """Cut a crop VRT to its geometry with a mask band; returns True on success.

    The geometry is rasterized once onto the VRT's pixel grid (a byte mask
    with overviews, a few MB even for a 116k-vertex ecoregion at 10 m) and
    attached as the dataset mask band. QGIS then draws only the pixels inside
    the shape, at the cost of reading a local mask, where a warped VRT with a
    cutline re-clips the polygon on every draw, which is slow for a boundary
    with many vertices. The mask is
    named after the geometry and grid, so every date of an area shares it.
    """
    try:
        ds = gdal.Open(vrt_path, gdal.GA_ReadOnly)
        width, height = ds.RasterXSize, ds.RasterYSize
        geotransform = ds.GetGeoTransform()
        projection = ds.GetProjection()
        ds = None
        key = hashlib.sha1(
            f"{_file_digest(cutline_path)}|{tuple(geotransform)}|{width}|{height}|{projection}".encode(),
            usedforsecurity=False,
        ).hexdigest()[:20]
        os.makedirs(mask_dir, exist_ok=True)
        mask_path = os.path.join(mask_dir, f"mask_{key}.tif")
        with _mask_lock(mask_path):
            if not is_valid_local_raster(mask_path):
                _rasterize_area_mask(cutline_path, vrt_path, mask_path, width, height, geotransform, projection)

        tree = ET.parse(vrt_path)
        root = tree.getroot()
        for old in root.findall("MaskBand"):
            root.remove(old)
        mask_band = ET.SubElement(root, "MaskBand")
        band = ET.SubElement(mask_band, "VRTRasterBand", dataType="Byte")
        source = ET.SubElement(band, "SimpleSource")
        filename = ET.SubElement(source, "SourceFilename", relativeToVRT="0")
        filename.text = mask_path
        ET.SubElement(source, "SourceBand").text = "1"
        tmp = vrt_path + ".part"
        tree.write(tmp)
        os.replace(tmp, vrt_path)
        return True
    except Exception as exc:
        _log_warning(f"Could not cut {os.path.basename(vrt_path)} to its shape with a mask band: {exc}")
        return False


def vrt_has_mask_band(vrt_path):
    """True when a VRT on disk carries a dataset mask band."""
    try:
        with open(vrt_path, "r") as f:
            return "<MaskBand>" in f.read()
    except (OSError, UnicodeDecodeError):
        return False


@uses_gdal
def build_single_vrt(task):
    """Worker to generate a VRT — thread-safe, no Qt dependency.

    Pipeline for shape mosaic:
      1) BuildVRT per-band -> spatial mosaic (joins tiles at full extent)
      2) BuildVRT separate=True -> stacks bands (RGB)
      3) BuildVRT with outputBounds -> clips by shape BBOX

    Intermediate VRTs prefer /vsimem/. The final on-disk VRT is flattened to
    direct data sources before RAM files are removed. If in-memory composition
    is unavailable, the original disk pipeline is retried transparently.

    Returns:
        ('ok', vrt_path, layer_name, group_name) on success
        ('error', tile, error_message) on failure
    """
    try:
        group_name = task.get("group_name", task["tile_safe"])
        cutline = task.get("cutline_path")

        # --- Multi-band mosaic (href_groups): each group = 1 band's spatial tiles ---
        if task.get("href_groups"):
            if _build_grouped_vrt_vsimem(task, cutline):
                return ("ok", task["vrt_path"], task["layer_name"], group_name)

            resample = "cubic" if task["mixed_res"] else "nearest"
            band_vrts = []

            # Step 1: BuildVRT per-band (spatial mosaic of tiles — full extent)
            for idx_g, group_sources in enumerate(task["href_groups"]):
                band_vrt = task["vrt_path"].replace(".vrt", f"_b{idx_g + 1}_mosaic.vrt")
                bvrt_opts = gdal.BuildVRTOptions(resampleAlg=resample, allowProjectionDifference=True)
                ds = gdal.BuildVRT(band_vrt, group_sources, options=bvrt_opts)
                if not ds:
                    return ("error", task["tile"], f"Band mosaic {idx_g + 1} failed for {task['band_desc']}")
                ds = None
                band_vrts.append(band_vrt)

            # Step 2: stack bands (separate=True) — full extent kept
            if task["mixed_res"]:
                stack_opts = gdal.BuildVRTOptions(resampleAlg="cubic", separate=True, resolution="highest")
            else:
                stack_opts = gdal.BuildVRTOptions(resampleAlg="nearest", separate=True)

            if cutline:
                stack_vrt = task["vrt_path"].replace(".vrt", "_rgb_mosaic.vrt")
                ds = gdal.BuildVRT(stack_vrt, band_vrts, options=stack_opts)
                if not ds:
                    return ("error", task["tile"], f"BuildVRT stack failed for {task['band_desc']}")
                ds = None

                # Step 3: BuildVRT with outputBounds (cutline BBOX)
                if _bbox_clip(cutline, stack_vrt, task["vrt_path"], resample=resample, mixed_res=task["mixed_res"]):
                    return ("ok", task["vrt_path"], task["layer_name"], group_name)
                else:
                    return ("error", task["tile"], f"BuildVRT bbox clip failed for {task['band_desc']}")
            else:
                ds = gdal.BuildVRT(task["vrt_path"], band_vrts, options=stack_opts)
                if ds:
                    ds = None
                    return ("ok", task["vrt_path"], task["layer_name"], group_name)
                else:
                    return ("error", task["tile"], f"BuildVRT stack failed for {task['band_desc']}")

        # --- Regular hrefs (single source or tiles from 1 item) ---
        input_sources = task["hrefs"]
        if task["separate"]:
            if task["mixed_res"]:
                opts = gdal.BuildVRTOptions(resampleAlg="cubic", separate=True, resolution="highest")
            else:
                opts = gdal.BuildVRTOptions(resampleAlg="nearest", separate=True)
        else:
            opts = gdal.BuildVRTOptions(resampleAlg="nearest")

        if cutline:
            if _build_cutline_vrt_vsimem(task, input_sources, opts):
                return ("ok", task["vrt_path"], task["layer_name"], group_name)

            intermediate = task["vrt_path"].replace(".vrt", "_src.vrt")
            ds = gdal.BuildVRT(intermediate, input_sources, options=opts)
            if not ds:
                return ("error", task["tile"], f"BuildVRT returned None for {task['band_desc']}")
            ds = None

            if _bbox_clip(cutline, intermediate, task["vrt_path"], mixed_res=task.get("mixed_res", False)):
                return ("ok", task["vrt_path"], task["layer_name"], group_name)
            else:
                return ("error", task["tile"], f"BuildVRT bbox clip failed for {task['band_desc']}")
        else:
            vrt = gdal.BuildVRT(task["vrt_path"], input_sources, options=opts)
            if vrt:
                vrt = None
                return ("ok", task["vrt_path"], task["layer_name"], group_name)
            else:
                return ("error", task["tile"], f"BuildVRT returned None for {task['band_desc']}")
    except Exception as e:
        return ("error", task["tile"], str(e))
