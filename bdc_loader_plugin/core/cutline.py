"""Cutline geometry for crops and area masks.

Reprojects an area polygon to a raster's CRS with densified edges, finds its
bounds on the raster grid, and clips a VRT to that bbox.
"""

import math
import os
import tempfile

from osgeo import gdal, ogr, osr

from .gdal_env import uses_gdal

# A crop downloads only the source blocks under its area (cog_window), in
# parallel. A tile the area covers at least this much of is still fetched
# whole: it costs under twice the blocks it needs and the file is reused by
# later downloads and loads of that tile.
WHOLE_TILE_PREFETCH_FRACTION = 0.5


@uses_gdal
def cutline_wgs84_bbox(cutline_path):
    """Return (xmin, ymin, xmax, ymax) of a cutline file already in EPSG:4326.

    Plugin-generated cutlines (shape and extent-crop) are always written in
    WGS84, matching the bbox on STAC items — no reprojection needed here.
    """
    ds = ogr.Open(cutline_path)
    if not ds:
        return None
    layer = ds.GetLayer()
    xmin, xmax, ymin, ymax = layer.GetExtent()
    ds = None
    return (xmin, ymin, xmax, ymax)


def estimate_tile_fetch_fraction(item_bbox, cutline_bbox):
    """Estimate the fraction of a source tile's area a crop/mask actually
    needs, from bbox metadata alone (no raster I/O) — the "windows vs shape"
    intersection used to decide whether a windowed remote read or a full
    parallel prefetch-then-crop is the faster way to fetch this tile.
    """
    if not item_bbox or not cutline_bbox:
        return 1.0
    ixmin = max(item_bbox[0], cutline_bbox[0])
    iymin = max(item_bbox[1], cutline_bbox[1])
    ixmax = min(item_bbox[2], cutline_bbox[2])
    iymax = min(item_bbox[3], cutline_bbox[3])
    if ixmax <= ixmin or iymax <= iymin:
        return 0.0
    item_area = (item_bbox[2] - item_bbox[0]) * (item_bbox[3] - item_bbox[1])
    if item_area <= 0:
        return 1.0
    inter_area = (ixmax - ixmin) * (iymax - iymin)
    return inter_area / item_area


# A reprojected cutline edge is only as smooth as the chords the boundary is
# densified into: too few and the "curve" becomes a visibly kinked polyline
# along the crop border. Aiming each chord at a few source pixels keeps the
# deviation between chord and true curve well under one pixel, so the mask
# edge follows the geometry instead of a coarse approximation of it.
CUTLINE_CHORD_PIXELS = 4


# ...but a large shape must not turn into an unbounded vertex list: the warp
# pays for every cutline vertex, so the chord count per envelope span is
# capped and the chords simply get longer on very large crops.
CUTLINE_MAX_CHORDS = 2048


# Floor on subdivision, whatever the pixel size: even a shape whose pixels are
# huge relative to its extent gets a boundary broken into this many chords.
CUTLINE_MIN_CHORDS = 64


def _cutline_chord_length(span, pixel_size, scale_to_cutline_units):
    """Return the segmentize length, in cutline SRS units, for a shape of
    extent *span* over a raster with *pixel_size* pixels.

    scale_to_cutline_units converts one raster unit into cutline units (a
    lat/lon cutline over a metric grid measures its pixels in degrees), and
    is None when that ratio could not be established — the coarse fixed
    subdivision is used then. The result is clamped between CUTLINE_MIN_CHORDS
    and CUTLINE_MAX_CHORDS chords across *span*, so neither a tiny pixel nor a
    huge shape can blow up the vertex count.
    """
    if span <= 0:
        return None
    coarse = span / CUTLINE_MIN_CHORDS
    if not pixel_size or not scale_to_cutline_units or scale_to_cutline_units <= 0:
        return coarse
    target = pixel_size * scale_to_cutline_units * CUTLINE_CHORD_PIXELS
    return max(span / CUTLINE_MAX_CHORDS, min(coarse, target))


def _units_per_raster_unit(envelope, transform):
    """Return how many cutline SRS units one raster SRS unit spans, measured
    across *envelope*'s diagonal, or None when it cannot be measured.

    Comparing the same diagonal in both SRSs is enough to turn a raster pixel
    size into the cutline's own units, which is what the segmentize step needs.
    """
    minx, maxx, miny, maxy = envelope
    diagonal = math.hypot(maxx - minx, maxy - miny)
    if diagonal <= 0:
        return None
    try:
        x0, y0, _ = transform.TransformPoint(minx, miny)
        x1, y1, _ = transform.TransformPoint(maxx, maxy)
    except (RuntimeError, TypeError, ValueError):
        return None
    projected = math.hypot(x1 - x0, y1 - y0)
    if projected <= 0:
        return None
    return diagonal / projected


@uses_gdal
def _cutline_in_raster_srs(cutline_path, raster_path):
    """Return a cutline file guaranteed to be in the same SRS as raster_path.

    gdal.Warp's cutlineSRS keyword isn't available in every GDAL Python
    binding version, and GDAL's own reprojection of a cross-SRS cutline
    raises a PROJ "Invalid latitude" error on a non-standard Albers
    grid. Reprojecting the cutline geometry here with
    plain OGR, and writing it as a GeoPackage rather than GeoJSON (which is
    fixed to WGS84 by format convention and cannot carry other CRS
    metadata), means the SRS GDAL reads back from the file already matches
    the raster, so no cutlineSRS override is needed at all. Returns the
    original path unchanged when the SRS already matches (no reprojection
    needed) — the caller can tell the two cases apart by identity.
    """
    cut_ds = ogr.Open(cutline_path)
    if not cut_ds:
        return cutline_path
    cut_layer = cut_ds.GetLayer()
    cut_srs = cut_layer.GetSpatialRef()

    raster_ds = gdal.Open(raster_path, gdal.GA_ReadOnly)
    if not raster_ds:
        return cutline_path
    raster_wkt = raster_ds.GetProjection()
    geotransform = raster_ds.GetGeoTransform(can_return_null=True)
    raster_ds = None
    raster_srs = osr.SpatialReference()
    raster_srs.ImportFromWkt(raster_wkt)
    pixel_size = min(abs(geotransform[1]), abs(geotransform[5])) if geotransform else 0.0

    if cut_srs and cut_srs.IsSame(raster_srs):
        return cutline_path

    if not cut_srs:
        return cutline_path

    cut_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    raster_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    transform = osr.CoordinateTransformation(cut_srs, raster_srs)

    fd, tmp_path = tempfile.mkstemp(suffix=".gpkg", prefix="bdc_cutline_reproj_")
    os.close(fd)
    os.remove(tmp_path)  # the GPKG driver creates the file itself

    out_driver = ogr.GetDriverByName("GPKG")
    out_ds = out_driver.CreateDataSource(tmp_path)
    out_layer = out_ds.CreateLayer("cutline", srs=raster_srs, geom_type=ogr.wkbUnknown)
    for feature in cut_layer:
        geom = feature.GetGeometryRef()
        if geom is None:
            continue
        geom = geom.Clone()
        # A straight edge in the cutline's SRS (e.g. a lat/lon extent-crop
        # rectangle) is a curve once reprojected into a different projection
        # (e.g. BDC's Albers grid). Transforming only the original vertices
        # connects the reprojected corners with straight lines instead of
        # following that curve, which visibly skews/misaligns the crop.
        # Densifying the boundary first keeps the reprojected shape faithful,
        # and doing it at pixel scale keeps the mask edge from stepping away
        # from the true boundary.
        env = geom.GetEnvelope()  # (minx, maxx, miny, maxy)
        span = max(env[1] - env[0], env[3] - env[2])
        chord = _cutline_chord_length(span, pixel_size, _units_per_raster_unit(env, transform))
        if chord:
            geom.Segmentize(chord)
        geom.Transform(transform)
        geom.FlattenTo2D()
        out_feat = ogr.Feature(out_layer.GetLayerDefn())
        out_feat.SetGeometry(geom)
        out_layer.CreateFeature(out_feat)
        out_feat = None
    out_ds = None
    return tmp_path


# Corners alone under-measure a reprojected extent: the edges between them
# bow outwards in the target projection, so a corner-only bbox slices off the
# bulge and the crop loses a strip along its border. Walking each edge at this
# many steps captures it.
_BOUNDS_SAMPLES_PER_EDGE = 32


def _extent_boundary_points(extent, samples_per_edge=_BOUNDS_SAMPLES_PER_EDGE):
    """Yield points along the perimeter of *extent* (xmin, xmax, ymin, ymax),
    corners included, for measuring how that rectangle reprojects."""
    xmin, xmax, ymin, ymax = extent
    steps = max(1, int(samples_per_edge))
    for index in range(steps + 1):
        fraction = index / steps
        x = xmin + (xmax - xmin) * fraction
        y = ymin + (ymax - ymin) * fraction
        yield (x, ymin)
        yield (x, ymax)
        yield (xmin, y)
        yield (xmax, y)


@uses_gdal
def _get_cutline_bounds_in_vrt_crs(cutline_path, src_path):
    """Return (xmin, ymin, xmax, ymax) of the cutline in the VRT's CRS."""
    cut_ds = ogr.Open(cutline_path)
    cut_layer = cut_ds.GetLayer()
    cut_srs = cut_layer.GetSpatialRef()
    cut_extent = cut_layer.GetExtent()  # (xmin, xmax, ymin, ymax)
    cut_ds = None

    vrt_ds = gdal.Open(src_path, gdal.GA_ReadOnly)
    vrt_wkt = vrt_ds.GetProjection()
    vrt_ds = None
    vrt_srs = osr.SpatialReference()
    vrt_srs.ImportFromWkt(vrt_wkt)

    if cut_srs and not cut_srs.IsSame(vrt_srs):
        cut_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        vrt_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        ct = osr.CoordinateTransformation(cut_srs, vrt_srs)
        xs, ys = [], []
        for x, y in _extent_boundary_points(cut_extent):
            tx, ty, _ = ct.TransformPoint(x, y)
            xs.append(tx)
            ys.append(ty)
        return (min(xs), min(ys), max(xs), max(ys))
    else:
        return (cut_extent[0], cut_extent[2], cut_extent[1], cut_extent[3])


@uses_gdal
def _aligned_clip_bounds(cutline_path, src_path):
    """Return cutline bounds snapped to the source VRT pixel grid."""
    bounds = _get_cutline_bounds_in_vrt_crs(cutline_path, src_path)
    src_ds = gdal.Open(src_path, gdal.GA_ReadOnly)
    if not src_ds:
        return None
    gt = src_ds.GetGeoTransform(can_return_null=True)
    src_ds = None
    if gt:
        origin_x, pixel_w, _, origin_y, _, pixel_h = gt
        if pixel_w and pixel_h:
            xmin, ymin, xmax, ymax = bounds
            px_min = (xmin - origin_x) / pixel_w
            px_max = (xmax - origin_x) / pixel_w
            py_top = (ymax - origin_y) / pixel_h
            py_bottom = (ymin - origin_y) / pixel_h
            xmin = origin_x + math.floor(px_min) * pixel_w
            xmax = origin_x + math.ceil(px_max) * pixel_w
            ymax = origin_y + math.floor(py_top) * pixel_h
            ymin = origin_y + math.ceil(py_bottom) * pixel_h
            bounds = (xmin, ymin, xmax, ymax)
    return bounds


@uses_gdal
def _bbox_clip(cutline_path, src_path, dst_path, resample="nearest", mixed_res=False):
    """Clip by BBOX via BuildVRT(outputBounds) — preserves spatial selectivity.

    No Warp/cutline: data stays clean for stats/stretch.
    Visual clipping by shape is done as a mask layer in QGIS.
    """
    bounds = _aligned_clip_bounds(cutline_path, src_path)
    if bounds is None:
        return False
    bvrt_kwargs = dict(
        outputBounds=list(bounds),
        resampleAlg=resample,
    )
    if mixed_res:
        bvrt_kwargs["resolution"] = "highest"
    ds = gdal.BuildVRT(dst_path, [src_path], options=gdal.BuildVRTOptions(**bvrt_kwargs))
    if ds:
        ds = None
        return True
    return False
