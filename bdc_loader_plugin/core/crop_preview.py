# -*- coding: utf-8 -*-
"""
crop_preview.py

Card preview of a crop or vector-feature mosaic, built from the overviews of
its source tiles.

A STAC item has a thumbnail; a crop is assembled from several items and has
none. Each source file is warped straight onto a small lon/lat grid over the
area: GDAL then reads only the overview level that matches the preview size
(a few KB per file). The files are read in parallel, composited, stretched
2-98 %, and everything outside the area is left transparent.

No Qt: runs in the card thumbnail threads and returns PNG bytes.
"""

import hashlib
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from osgeo import gdal, ogr, osr

from ..logger import warning as _log_warning
from .band_selection import resolve_band
from .gdal_env import uses_gdal

PREVIEW_SIZE = 180
# Reads at once over all previews: several cards render together, and the
# server throttles a client that opens too many connections.
_READS = threading.BoundedSemaphore(12)
_FILES_PER_PREVIEW = 8


def preview_key(item_id, collection_id, bands, area):
    """Cache key of a preview: the same area, date, bands and collection give the same image."""
    text = "|".join([str(collection_id), str(item_id), ",".join(bands), str(area)])
    return hashlib.sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()


def _grid(bbox, size):
    xmin, ymin, xmax, ymax = bbox
    width_deg, height_deg = xmax - xmin, ymax - ymin
    if width_deg >= height_deg:
        return size, max(1, round(size * height_deg / width_deg))
    return max(1, round(size * width_deg / height_deg)), size


@uses_gdal
def _read(href, bbox, width, height):
    with _READS:
        ds = gdal.Warp(
            "",
            href,
            options=gdal.WarpOptions(
                format="MEM",
                outputBounds=list(bbox),
                width=width,
                height=height,
                dstSRS="EPSG:4326",
                resampleAlg="average",
                dstNodata=0,
            ),
        )
        return ds.GetRasterBand(1).ReadAsArray().astype(np.float32)


@uses_gdal
def _shape_mask(area_wkt, bbox, width, height):
    mask_ds = gdal.GetDriverByName("MEM").Create("", width, height, 1, gdal.GDT_Byte)
    xmin, ymin, xmax, ymax = bbox
    mask_ds.SetGeoTransform((xmin, (xmax - xmin) / width, 0, ymax, 0, -(ymax - ymin) / height))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    mem = ogr.GetDriverByName("Memory").CreateDataSource(f"preview_{uuid.uuid4().hex}")
    layer = mem.CreateLayer("area", srs, ogr.wkbUnknown)
    feature = ogr.Feature(layer.GetLayerDefn())
    feature.SetGeometry(ogr.CreateGeometryFromWkt(area_wkt))
    layer.CreateFeature(feature)
    gdal.RasterizeLayer(mask_ds, [1], layer, burn_values=[1], options=["ALL_TOUCHED=TRUE"])
    return mask_ds.GetRasterBand(1).ReadAsArray() > 0


@uses_gdal
def render_preview(source_items, bands, bbox, area_wkt=None, size=PREVIEW_SIZE, cancel_check=None):
    """PNG bytes (RGBA) of the area, or None when nothing could be read.

    ``bands``: three bands make a colour composite, one makes a grey image.
    ``bbox``: lon/lat (xmin, ymin, xmax, ymax) of the area; ``area_wkt``, when
    given, clears everything outside that lon/lat shape. ``cancel_check()``
    is asked before each file is read; once it returns True nothing more is
    read and None is returned.
    """
    bands = list(bands)[:3] if len(bands) >= 3 else list(bands)[:1]
    if not bands or not source_items or not bbox:
        return None
    width, height = _grid(bbox, size)
    per_band = []
    for band in bands:
        hrefs = []
        for item in source_items:
            asset = resolve_band(band, item.assets)
            if asset:
                hrefs.append("/vsicurl/" + item.assets[asset].href)
        per_band.append(hrefs)
    jobs = [(b, href) for b, hrefs in enumerate(per_band) for href in hrefs]
    if not jobs:
        return None
    layers = [np.zeros((height, width), dtype=np.float32) for _ in bands]

    def _wanted_read(href):
        if cancel_check and cancel_check():
            return None
        return _read(href, bbox, width, height)

    with ThreadPoolExecutor(max_workers=min(_FILES_PER_PREVIEW, len(jobs))) as executor:
        futures = [(b, executor.submit(_wanted_read, href)) for b, href in jobs]
        for b, future in futures:
            try:
                data = future.result()
            except Exception as exc:
                _log_warning(f"Crop preview: band {b} could not be read, it shows dark: {exc}")
                continue
            if data is not None:
                layers[b] = np.where((layers[b] == 0) & (data > 0), data, layers[b])
    if cancel_check and cancel_check():
        return None
    valid = np.all([layer > 0 for layer in layers], axis=0)
    if area_wkt:
        try:
            valid &= _shape_mask(area_wkt, bbox, width, height)
        except Exception as exc:
            _log_warning(f"Crop preview: the area mask failed, the preview shows the whole box: {exc}")
    if not valid.any():
        return None

    channels = []
    for layer in layers:
        values = layer[valid]
        low, high = np.percentile(values, 2), np.percentile(values, 98)
        scaled = np.clip((layer - low) / max(high - low, 1e-6) * 255, 0, 255).astype(np.uint8)
        channels.append(scaled)
    if len(channels) == 1:
        channels = channels * 3
    alpha = np.where(valid, 255, 0).astype(np.uint8)

    image = gdal.GetDriverByName("MEM").Create("", width, height, 4, gdal.GDT_Byte)
    for index, channel in enumerate(channels + [alpha], start=1):
        image.GetRasterBand(index).WriteArray(channel)
    path = f"/vsimem/bdc_preview_{uuid.uuid4().hex}.png"
    try:
        gdal.Translate(path, image, format="PNG")
        handle = gdal.VSIFOpenL(path, "rb")
        try:
            gdal.VSIFSeekL(handle, 0, os.SEEK_END)
            length = gdal.VSIFTellL(handle)
            gdal.VSIFSeekL(handle, 0, os.SEEK_SET)
            return bytes(gdal.VSIFReadL(1, length, handle))
        finally:
            gdal.VSIFCloseL(handle)
    finally:
        gdal.Unlink(path)
        if gdal.VSIStatL(path + ".aux.xml") is not None:
            gdal.Unlink(path + ".aux.xml")
