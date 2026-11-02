# -*- coding: utf-8 -*-
"""
point_series.py

Point time series read straight from a collection's COGs, grouped by file.

A collection of scenes stores one COG per date and band, in compressed
blocks; a point's series needs one block per date and band, and every file
costs a few round trips before its first pixel. Reading every point that
falls in a file through one open of that file shares those round trips and,
for nearby points, the block itself. The values are the same as reading one
point at a time, with fewer requests to the server.

A read that fails (refused, timed out) is not a missing value: it is retried
once with fewer connections, after clearing what GDAL cached for the file,
and whatever still fails is counted and returned, so the caller can say the
series has holes.

No Qt: runs in worker threads.
"""

import json
import math
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from osgeo import gdal, ogr, osr

from ..core.gdal_env import plugin_gdal, uses_gdal
from .gdal_setup import _get_perf_config, point_read_options

_FAILED = object()
_RETRY_WORKERS = 4
_RETRY_PAUSE_S = 2.0
_MISSING_SENTINELS = (-9999.0, -32768.0, 32767.0)


def item_datetime(item):
    """The item's date as a naive UTC datetime, or None.

    WTSS gives naive dates; the COG series use the same kind, so the bands of
    one point pair by date whichever service read them.
    """
    dt = getattr(item, "datetime", None)
    if not dt:
        text = (getattr(item, "properties", None) or {}).get("datetime") or ""
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00")) if text else None
        except ValueError:
            return None
    if dt is not None and dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def resolve_asset(item, band):
    asset = item.assets.get(band)
    if asset is not None:
        return asset
    lower = band.lower()
    return next((v for k, v in item.assets.items() if k.lower() == lower), None)


@uses_gdal
def assign_items_to_points(items, points):
    """[[items covering point i]] using each item's footprint (bbox when it has none)."""
    probes = []
    for lon, lat in points:
        probe = ogr.Geometry(ogr.wkbPoint)
        probe.AddPoint_2D(lon, lat)
        probes.append(probe)
    per_point = [[] for _ in points]
    for item in items:
        geometry = getattr(item, "geometry", None)
        footprint = None
        if geometry:
            try:
                footprint = ogr.CreateGeometryFromJson(json.dumps(geometry))
            except Exception:
                footprint = None
        bbox = getattr(item, "bbox", None)
        for index, (lon, lat) in enumerate(points):
            if footprint is not None:
                inside = footprint.Intersects(probes[index])
            elif bbox and len(bbox) >= 4:
                inside = bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]
            else:
                inside = True
            if inside:
                per_point[index].append(item)
    return per_point


@uses_gdal
def _wgs84():
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return srs


@uses_gdal
def read_file_points(href, points, nodata_fallback=-9999):
    """Values at ``points`` [(lon, lat)] in one raster, opened once.

    Each value is a float, None for no data (nodata, outside the raster), or
    the module's failure marker when the file could not be read.
    """
    try:
        ds = gdal.Open(href, gdal.GA_ReadOnly)
    except Exception:
        return [_FAILED] * len(points)
    if ds is None:
        return [_FAILED] * len(points)
    try:
        gt = ds.GetGeoTransform()
        srs = osr.SpatialReference()
        srs.ImportFromWkt(ds.GetProjection())
        srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        transform = osr.CoordinateTransformation(_wgs84(), srs)
        band = ds.GetRasterBand(1)
        nodata = band.GetNoDataValue()
        values = []
        for lon, lat in points:
            x, y, _ = transform.TransformPoint(lon, lat)
            px = math.floor((x - gt[0]) / gt[1])
            py = math.floor((y - gt[3]) / gt[5])
            if not (0 <= px < ds.RasterXSize and 0 <= py < ds.RasterYSize):
                values.append(None)
                continue
            try:
                value = float(band.ReadAsArray(px, py, 1, 1)[0, 0])
            except Exception:
                values.append(_FAILED)
                continue
            if math.isnan(value):
                missing = True  # float products fill with NaN, declared or not
            elif nodata is not None:
                missing = value == nodata
            else:
                missing = value in _MISSING_SENTINELS or (nodata_fallback is not None and value == nodata_fallback)
            values.append(None if missing else value)
        return values
    finally:
        ds = None


def _forget_failure(href):
    """Drop what /vsicurl/ remembers of ``href``: after a refused open GDAL
    caches the file as missing and a new open sends no request at all."""
    clear = getattr(gdal, "VSICurlPartialClearCache", None)
    if clear is not None:
        try:
            clear(href)
        except Exception:
            pass


def extract_points_timeseries(
    items_per_point,
    points,
    bands,
    cancel_flag=None,
    progress_callback=None,
    max_workers=None,
    nodata_fallback=-9999,
    bands_per_point=None,
):
    """Series of every point and band, reading each file once.

    ``items_per_point[i]``: the items whose footprint covers ``points[i]``;
    ``bands_per_point[i]``, when given, limits point ``i`` to those bands.
    ``progress_callback(done_files, total_files)`` is called from worker
    threads. Returns ``({point index: {band: [(date, value)] sorted}}, failed)``
    where ``failed`` counts the pixel reads that still failed after a retry.
    """
    perf = _get_perf_config()
    gdal_options = point_read_options(perf)
    files = {}
    for index, items in enumerate(items_per_point):
        for item in items:
            dt = item_datetime(item)
            if dt is None:
                continue
            wanted = bands if bands_per_point is None else [b for b in bands if b in bands_per_point[index]]
            for band in wanted:
                asset = resolve_asset(item, band)
                if asset is None:
                    continue
                item_id = str(getattr(item, "id", id(item)))
                entry = files.setdefault(
                    (item_id, band),
                    {"href": f"/vsicurl/{asset.href}", "dt": dt, "band": band, "item": item_id, "points": []},
                )
                entry["points"].append(index)

    series = {index: {band: [] for band in bands} for index in range(len(points))}
    jobs = list(files.values())
    total = len(jobs)
    done = [0]

    def _run(job):
        with plugin_gdal(gdal_options):
            values = read_file_points(job["href"], [points[i] for i in job["points"]], nodata_fallback)
        return job, values

    def _pass(pending, workers, last):
        """Read ``pending``; a file with a failed pixel is kept for the next
        pass and adds nothing, unless this is the last pass. Returns the
        files to retry and, on the last pass, the pixels that failed."""
        retry, failed_pixels = [], 0
        if not pending:
            return retry, failed_pixels
        executor = ThreadPoolExecutor(max_workers=max(1, min(workers, len(pending))))
        try:
            futures = [executor.submit(_run, job) for job in pending]
            for future in as_completed(futures):
                if cancel_flag and cancel_flag():
                    for f in futures:
                        f.cancel()
                    break
                job, values = future.result()
                failures = sum(1 for value in values if value is _FAILED)
                if failures and not last:
                    retry.append(job)
                    continue
                failed_pixels += failures
                for index, value in zip(job["points"], values):
                    if value is not None and value is not _FAILED:
                        series[index][job["band"]].append((job["dt"], value, job["item"]))
                done[0] += 1
                if progress_callback:
                    progress_callback(done[0], total)
        finally:
            executor.shutdown(wait=False)
        return retry, failed_pixels

    workers = max_workers or perf.get("max_threads", 16)
    retry, failed = _pass(jobs, workers, last=False)
    if retry and not (cancel_flag and cancel_flag()):
        time.sleep(_RETRY_PAUSE_S)
        for job in retry:
            _forget_failure(job["href"])
        _retry, failed = _pass(retry, _RETRY_WORKERS, last=True)

    return {index: _one_item_per_date(by_band) for index, by_band in series.items()}, failed


def _one_item_per_date(by_band):
    """{band: [(date, value)] sorted} with every date's values taken from one item.

    Overlapping tiles of one acquisition give a point two items with the same
    date. Pairing bands by date (an index, the RGB chart) then mixed one
    tile's NIR with the other's red, and which value won depended on thread
    order. Each date keeps the item with a value in the most bands, then the
    smallest id, for all bands alike.
    """
    bands_with_value = defaultdict(Counter)
    for rows in by_band.values():
        for dt, _value, item in rows:
            bands_with_value[dt][item] += 1
    chosen = {dt: min(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0] for dt, counts in bands_with_value.items()}
    result = {}
    for band, rows in by_band.items():
        kept = sorted(((dt, value) for dt, value, item in rows if chosen[dt] == item), key=lambda row: row[0])
        if kept:
            result[band] = kept
    return result
