# -*- coding: utf-8 -*-
"""
cog_window.py

Local copies of only the part of a remote COG an area needs.

A crop reading a remote GeoTIFF window through /vsicurl/ pulls its blocks
over a single connection, which is slow for a crop of a large tile. Here the
blocks the area touches are located
from the TIFF index, downloaded in parallel byte ranges together with the
file header, and written at their original offsets into a sparse file of the
remote file's size. GDAL then reads that file like the original: same
header, same block offsets, real data wherever the crop reads, with
pixel-identical results.

Blocks the area does not touch are never written and read back as zeros, so
a copy is only good for reads inside the planned window; verify() checks the
copy's block index against the remote one before it is used.

No Qt: runs in worker threads.
"""

import math
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from osgeo import gdal, ogr, osr

from ..net import TRANSFER_S
from . import download_engine
from .gdal_env import uses_gdal

# Nearby blocks are fetched in one request when the gap between them is at
# most this many bytes; a long run is split so it still spreads over connections.
MERGE_GAP = 64 * 1024
MAX_RANGE = 8 * 1024 * 1024
# Pixels added around the area, so resampling at its edge reads real data.
MARGIN_PX = 2

VSICURL = "/vsicurl/"


@dataclass
class WindowPlan:
    """What to fetch from one remote file."""

    url: str
    size: int
    header_end: int
    blocks: dict = field(default_factory=dict)  # (band, x, y) -> (offset, nbytes)
    window: tuple = (0, 0, 0, 0)  # pixel window (x0, y0, x1, y1) the blocks cover, end exclusive

    @property
    def nbytes(self):
        return self.header_end + sum(n for _off, n in self.blocks.values())

    def ranges(self):
        """Byte ranges to download: the header, then the blocks, merged and split."""
        spans = sorted((off, off + n - 1) for off, n in self.blocks.values())
        merged = [[0, self.header_end - 1]]
        for start, end in spans:
            if start - merged[-1][1] <= MERGE_GAP:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        out = []
        for start, end in merged:
            while end - start + 1 > MAX_RANGE:
                out.append((start, start + MAX_RANGE - 1))
                start += MAX_RANGE
            out.append((start, end))
        return out


def is_remote(href):
    return str(href).startswith(VSICURL)


def _block_index(band, cols, rows):
    out = {}
    for y in rows:
        for x in cols:
            off = band.GetMetadataItem(f"BLOCK_OFFSET_{x}_{y}", "TIFF")
            size = band.GetMetadataItem(f"BLOCK_SIZE_{x}_{y}", "TIFF")
            if off and size and int(size) > 0:
                out[(x, y)] = (int(off), int(size))
    return out


def _first_data_offset(band):
    """Smallest image-data offset over every level: all bytes before it are
    the TIFF header, IFDs and block index arrays."""
    levels = [band] + [band.GetOverview(i) for i in range(band.GetOverviewCount())]
    first = None
    for level in levels:
        bx, by = level.GetBlockSize()
        index = _block_index(level, range(-(-level.XSize // bx)), range(-(-level.YSize // by)))
        if index:
            low = min(off for off, _n in index.values())
            first = low if first is None else min(first, low)
    return first


@uses_gdal
def _area_in_raster_srs(wkt_geometry, raster_wkt):
    """The lon/lat bounding rectangle of the area, densified and reprojected.

    The rectangle rather than the shape itself: the crop VRTs clip to the
    reprojected lon/lat box of the area, and every block of that box is read.
    """
    xmin, xmax, ymin, ymax = ogr.CreateGeometryFromWkt(wkt_geometry).GetEnvelope()
    geom = ogr.CreateGeometryFromWkt(bbox_wkt((xmin, ymin, xmax, ymax)))
    src = osr.SpatialReference()
    src.ImportFromEPSG(4326)
    dst = osr.SpatialReference()
    dst.ImportFromWkt(raster_wkt)
    for srs in (src, dst):
        if hasattr(srs, "SetAxisMappingStrategy"):
            srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    geom.Segmentize(min(0.01, (xmax - xmin) / 50 or 0.01, (ymax - ymin) / 50 or 0.01))
    geom.Transform(osr.CoordinateTransformation(src, dst))
    return geom


def bbox_wkt(bbox):
    """Lon/lat bbox (xmin, ymin, xmax, ymax) as a WKT polygon."""
    xmin, ymin, xmax, ymax = bbox
    return f"POLYGON(({xmin} {ymin},{xmax} {ymin},{xmax} {ymax},{xmin} {ymax},{xmin} {ymin}))"


@uses_gdal
def plan_window(href, area_wkt):
    """Plan the fetch of the blocks under the lon/lat bounding box of
    ``area_wkt``, reprojected with densified edges and grown by MARGIN_PX pixels.

    The whole box is kept even for an irregular shape: a masked gdal.Warp reads
    every block of the box and only then masks, and an unfetched block would
    not decompress. Returns None when the file cannot be planned (not a tiled
    GeoTIFF, unreadable index).
    """
    ds = gdal.Open(href)
    if ds is None or ds.GetDriver().ShortName != "GTiff":
        return None
    band = ds.GetRasterBand(1)
    bx, by = band.GetBlockSize()
    if bx >= ds.RasterXSize and by == 1:
        return None  # striped, not tiled
    gt = ds.GetGeoTransform()
    area = _area_in_raster_srs(area_wkt, ds.GetProjection())
    pixel = max(abs(gt[1]), abs(gt[5]))
    grown = area.Buffer(pixel * MARGIN_PX)
    xmin, xmax, ymin, ymax = grown.GetEnvelope()

    px0 = max(0, math.floor((xmin - gt[0]) / gt[1]))
    px1 = min(ds.RasterXSize, math.ceil((xmax - gt[0]) / gt[1]))
    py0 = max(0, math.floor((ymax - gt[3]) / gt[5]))
    py1 = min(ds.RasterYSize, math.ceil((ymin - gt[3]) / gt[5]))

    blocks = {}
    if px0 < px1 and py0 < py1:
        cols = range(px0 // bx, (px1 - 1) // bx + 1)
        rows = range(py0 // by, (py1 - 1) // by + 1)
        for b in range(1, ds.RasterCount + 1):
            for (x, y), value in _block_index(ds.GetRasterBand(b), cols, rows).items():
                blocks[(b, x, y)] = value

    header_end = _first_data_offset(band)
    stat = gdal.VSIStatL(href)
    ds = None
    if not header_end or stat is None:
        return None
    url = href[len(VSICURL) :] if is_remote(href) else href
    return WindowPlan(url=url, size=stat.size, header_end=header_end, blocks=blocks, window=(px0, py0, px1, py1))


def fetch(plan, dest_path, session, limiter, progress_cb=None, cancel_check=None, max_workers=None):
    """Write the planned ranges of ``plan`` into a sparse file at ``dest_path``."""
    tmp = dest_path + ".part"
    with open(tmp, "wb") as f:
        f.truncate(plan.size)
    ranges = plan.ranges()
    workers = max(1, min(max_workers or limiter.limit, len(ranges)))

    def _one(span):
        start, end = span
        download_engine._with_throttle_retry(
            lambda progress: download_engine._download_segment(
                plan.url, tmp, start, end, session, progress, cancel_check, TRANSFER_S
            ),
            limiter,
            progress_cb,
        )

    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            list(executor.map(_one, ranges))
        os.replace(tmp, dest_path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return dest_path


@uses_gdal
def verify(plan, path):
    """True when ``path`` lists every planned block at the remote offset and size."""
    try:
        ds = gdal.Open(path)
        if ds is None:
            return False
        for (b, x, y), (off, nbytes) in plan.blocks.items():
            band = ds.GetRasterBand(b)
            if int(band.GetMetadataItem(f"BLOCK_OFFSET_{x}_{y}", "TIFF") or -1) != off:
                return False
            if int(band.GetMetadataItem(f"BLOCK_SIZE_{x}_{y}", "TIFF") or -1) != nbytes:
                return False
        return True
    except Exception:
        return False
    finally:
        ds = None


@uses_gdal
def area_wkt_from_cutline(cutline_path):
    """Union of the features of a WGS84 cutline file, as WKT, or None."""
    ds = ogr.Open(cutline_path)
    if ds is None:
        return None
    union = None
    for feature in ds.GetLayer():
        geom = feature.GetGeometryRef()
        if geom is None:
            continue
        union = geom.Clone() if union is None else union.Union(geom)
    ds = None
    return union.ExportToWkt() if union is not None else None


# Files planned and fetched at once; the shared limiter still caps connections.
_FILES_AT_ONCE = 4


def plan_all(hrefs, area_wkt):
    """{href: WindowPlan or None} for the remote hrefs, planned in parallel."""
    remote = list(dict.fromkeys(h for h in hrefs if is_remote(h)))

    def _plan(href):
        try:
            return href, plan_window(href, area_wkt)
        except Exception:
            return href, None

    if not remote:
        return {}
    with ThreadPoolExecutor(max_workers=min(_FILES_AT_ONCE, len(remote))) as executor:
        return dict(executor.map(_plan, remote))


def localize(hrefs, area_wkt, folder, session, limiter, progress_cb=None, cancel_check=None, budget=None):
    """Replace every remote href by a verified local window copy, or none of them.

    All files are planned first; ``budget(total_bytes)`` (called from a
    worker thread) may then refuse the whole set before anything is fetched.
    Returns ({href: local_path}, fetched_bytes): an empty mapping means the
    caller keeps reading every source remotely, so a layer never mixes a
    partial local copy with remote reads.
    """
    plans = plan_all(hrefs, area_wkt)
    if not plans or any(plan is None for plan in plans.values()):
        return {}, 0
    total = sum(plan.nbytes for plan in plans.values())
    if budget is not None and not budget(total):
        return {}, 0
    os.makedirs(folder, exist_ok=True)

    def _fetch(indexed):
        index, (href, plan) = indexed
        if cancel_check and cancel_check():
            return href, None
        dest = os.path.join(folder, f"w{index}_{os.path.basename(plan.url)}")
        try:
            fetch(plan, dest, session, limiter, progress_cb, cancel_check)
        except Exception:
            return href, None
        if verify(plan, dest):
            return href, dest
        os.remove(dest)
        return href, None

    with ThreadPoolExecutor(max_workers=min(_FILES_AT_ONCE, len(plans))) as executor:
        results = dict(executor.map(_fetch, enumerate(plans.items())))
    if any(dest is None for dest in results.values()):
        for dest in results.values():
            if dest and os.path.exists(dest):
                os.remove(dest)
        return {}, 0
    return results, total


def localize_task(task, mapping):
    """Copy of a VRT task whose sources point at the local copies in ``mapping``."""
    local = dict(task)
    if task.get("hrefs"):
        local["hrefs"] = [mapping.get(h, h) for h in task["hrefs"]]
    if task.get("href_groups"):
        local["href_groups"] = [[mapping.get(h, h) for h in group] for group in task["href_groups"]]
    return local


def task_hrefs(task):
    """Every source href of a VRT task."""
    out = list(task.get("hrefs") or [])
    for group in task.get("href_groups") or []:
        out.extend(group)
    return out
