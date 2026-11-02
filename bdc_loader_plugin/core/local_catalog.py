"""Images already downloaded, indexed from the download folder.

When the BDC cannot be reached, the search runs on this index instead of the
STAC, so downloaded scenes and crops can still be found and loaded. The index
reads the names the download writes (see download_outputs) and asks GDAL only
for the band count and the footprint of each file, cached by path, size and
modification time.

Layout read under ``<download_dir>/downloads/<collection>/``:

- ``<item>/<item>_<band>[_<proj>].tif``          one scene, one file per band
- ``<item>/<item>_<b1-b2-b3>[_<proj>].tif|.vrt``  one scene, bands stacked
- ``<area>/<area>_<date>_<band>[_<proj>].tif``    a crop or feature on a date
- ``<area>/<area>_<date>_<b1-b2-b3>[_<proj>].tif|.vrt``
- ``sits/<coll>_<proj>_<tile>_<band>_<date>.tif`` names read by the R package sits
- ``<area>_<date>_<b1-b2-b3>_masked.tif``         crops saved at the collection level

``<proj>`` is the projection tag of a reprojected download (``epsg4326`` or
``crs`` plus 8 hex digits); the native grid has none.
"""

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

from ..stac.parsers import extract_tile_from_id
from .download_outputs import SITS_DIR
from .gdal_env import uses_gdal

_PROJ_SUFFIX = re.compile(r"_(epsg\d+|crs[0-9a-f]{8})$")
_AREA_DATE = re.compile(r"^(?P<area>.+?)_(?P<date>\d{4}-\d{2}-\d{2})_(?P<bands>.+)$")
_ID_DATE = re.compile(r"(?<!\d)((?:19|20)\d{2})-?(0[1-9]|1[0-2])-?(0[1-9]|[12]\d|3[01])(?!\d)")
_ID_DOY = re.compile(r"\bA((?:19|20)\d{2})(\d{3})\b")
_SITS_NAME = re.compile(
    r"^(?P<coll>[^_]+)_(?P<proj>[^_]+)_(?P<tile>[^_]+)_(?P<band>[^_]+)_(?P<date>\d{4}-\d{2}-\d{2})\.tif$"
)
_RASTER_EXTENSIONS = (".tif", ".vrt")
_CUBE_TILE = re.compile(r"_V\d+_(\d{6})_")

# Bbox is (xmin, ymin, xmax, ymax) in EPSG:4326.
Bbox = Tuple[float, float, float, float]


@dataclass
class LocalImage:
    """A scene, or a crop or feature mosaic on one date, found in the download folder."""

    collection: str
    item_id: str
    date: str
    tile: str
    kind: str  # "scene" or "area"
    projection: str = ""
    band_files: Dict[str, str] = field(default_factory=dict)
    layer_file: Optional[str] = None
    layer_bands: Tuple[str, ...] = ()
    bbox: Optional[Bbox] = None

    @property
    def bands(self):
        """Every band this download holds, per-band files first."""
        return list(dict.fromkeys(list(self.band_files) + list(self.layer_bands)))

    @property
    def files(self):
        return list(self.band_files.values()) + ([self.layer_file] if self.layer_file else [])


def _strip_projection(stem):
    match = _PROJ_SUFFIX.search(stem)
    return (stem[: match.start()], match.group(1)) if match else (stem, "")


def date_from_id(item_id):
    """YYYY-MM-DD read from a STAC item id, or "" (8-digit dates and MODIS AYYYYDDD)."""
    match = _ID_DATE.search(item_id)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    match = _ID_DOY.search(item_id)
    if match:
        year, doy = int(match.group(1)), int(match.group(2))
        if 1 <= doy <= 366:
            return datetime.strptime(f"{year} {doy}", "%Y %j").strftime("%Y-%m-%d")
    return ""


def tile_from_id(item_id):
    """Tile of a STAC item id; data cube ids carry a 6-digit BDC grid tile (``S2-16D_V2_033008_...``)."""
    tile = extract_tile_from_id(item_id)
    if tile != "NA":
        return tile
    match = _CUBE_TILE.search(item_id)
    return match.group(1) if match else item_id


@uses_gdal
def _gdal_facts(path):
    """(band count, EPSG:4326 bbox) of a raster, or None when GDAL cannot read it."""
    from osgeo import gdal, osr

    try:
        ds = gdal.Open(path)
    except RuntimeError:
        return None
    if ds is None:
        return None
    count = ds.RasterCount
    gt = ds.GetGeoTransform(can_return_null=True)
    wkt = ds.GetProjection()
    width, height = ds.RasterXSize, ds.RasterYSize
    ds = None
    if not gt or not wkt:
        return count, None
    xs = [gt[0], gt[0] + width * gt[1] + height * gt[2]]
    ys = [gt[3], gt[3] + width * gt[4] + height * gt[5]]
    corners = [(x, y) for x in xs for y in ys]
    src = osr.SpatialReference()
    src.ImportFromWkt(wkt)
    src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    dst = osr.SpatialReference()
    dst.ImportFromEPSG(4326)
    dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    transform = osr.CoordinateTransformation(src, dst)
    points = [transform.TransformPoint(x, y)[:2] for x, y in corners]
    lons, lats = [p[0] for p in points], [p[1] for p in points]
    return count, (min(lons), min(lats), max(lons), max(lats))


_FACTS_CACHE: Dict[Tuple[str, float, int], Optional[tuple]] = {}


def raster_facts(path, reader: Callable = _gdal_facts):
    """Cached band count and bbox of ``path``; recomputed when the file changes."""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    key = (path, stat.st_mtime, stat.st_size)
    if key not in _FACTS_CACHE:
        _FACTS_CACHE[key] = reader(path)
    return _FACTS_CACHE[key]


def _usable(path):
    return os.path.isfile(path) and not os.path.exists(path + ".part")


def _split_bands(text, facts):
    """Band names of a file named after ``text``: a multiband file joins them with "-".

    Crops saved at the collection level carry an alpha band after the named ones.
    """
    parts = text.split("-")
    if len(parts) > 1 and facts and facts[0] >= len(parts):
        return parts
    return [text]


def _add_file(images, key, make, band_names, path, facts):
    image = images.get(key)
    if image is None:
        image = images[key] = make()
    if len(band_names) == 1 and path.endswith(".tif"):
        image.band_files.setdefault(band_names[0], path)
    elif image.layer_file is None or path.endswith(".tif"):
        image.layer_file, image.layer_bands = path, tuple(band_names)
    if image.bbox is None and facts and facts[1]:
        image.bbox = facts[1]


def _scan_folder(images, collection, folder, name, reader):
    """Files of one scene folder (named after the item) or one area folder."""
    for entry in sorted(os.listdir(folder)):
        path = os.path.join(folder, entry)
        stem, ext = os.path.splitext(entry)
        if ext not in _RASTER_EXTENSIONS or not _usable(path) or not stem.startswith(name + "_"):
            continue
        rest, projection = _strip_projection(stem[len(name) + 1 :])
        area = _AREA_DATE.match(f"{name}_{rest}")
        facts = raster_facts(path, reader)
        if area and area.group("area") == name:
            date, bands = area.group("date"), _split_bands(area.group("bands"), facts)
            key = (collection, name, date, projection)
            make = lambda: LocalImage(collection, f"{name}_{date}", date, name, "area", projection)  # noqa: E731
        else:
            bands = _split_bands(rest, facts)
            key = (collection, name, "", projection)
            make = lambda: LocalImage(  # noqa: E731
                collection, name, date_from_id(name), tile_from_id(name), "scene", projection
            )
        _add_file(images, key, make, bands, path, facts)


def _scan_sits(images, collection, folder, reader):
    for entry in sorted(os.listdir(folder)):
        match = _SITS_NAME.match(entry)
        path = os.path.join(folder, entry)
        if not match or not _usable(path):
            continue
        proj = "" if match.group("proj") == "native" else match.group("proj")
        tile, date = match.group("tile"), match.group("date")
        key = (collection, tile, date, proj)
        make = lambda: LocalImage(collection, f"{tile}_{date}", date, tile, "area", proj)  # noqa: E731
        _add_file(images, key, make, [match.group("band")], path, raster_facts(path, reader))


def _scan_loose_files(images, collection, folder, reader):
    """Crops saved at the collection level (``..._masked.tif``)."""
    for entry in sorted(os.listdir(folder)):
        path = os.path.join(folder, entry)
        stem, ext = os.path.splitext(entry)
        if ext != ".tif" or not _usable(path):
            continue
        stem, projection = _strip_projection(stem)
        stem = stem[: -len("_masked")] if stem.endswith("_masked") else stem
        match = _AREA_DATE.match(stem)
        if not match:
            continue
        facts = raster_facts(path, reader)
        area, date = match.group("area"), match.group("date")
        key = (collection, area, date, projection)
        make = lambda: LocalImage(collection, f"{area}_{date}", date, area, "area", projection)  # noqa: E731
        _add_file(images, key, make, _split_bands(match.group("bands"), facts) or [], path, facts)


def scan_downloads(download_dir, reader: Callable = _gdal_facts) -> List[LocalImage]:
    """Every downloaded image under ``<download_dir>/downloads``, by collection, place and date."""
    root = os.path.join(download_dir, "downloads")
    if not os.path.isdir(root):
        return []
    images: Dict[tuple, LocalImage] = {}
    for collection in sorted(os.listdir(root)):
        coll_dir = os.path.join(root, collection)
        if not os.path.isdir(coll_dir):
            continue
        _scan_loose_files(images, collection, coll_dir, reader)
        for name in sorted(os.listdir(coll_dir)):
            folder = os.path.join(coll_dir, name)
            if not os.path.isdir(folder):
                continue
            if name == SITS_DIR:
                _scan_sits(images, collection, folder, reader)
            else:
                _scan_folder(images, collection, folder, name, reader)
    return [image for image in images.values() if image.files]


def _intersects(a: Bbox, b: Bbox):
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def search_local(images, collection_id, start, end, bbox: Optional[Bbox] = None, tiles=None):
    """Images of ``collection_id`` dated from ``start`` to ``end`` (YYYY-MM-DD), newest first.

    With ``bbox`` only images whose footprint meets it; with ``tiles`` only
    scenes of those tiles. An image without a readable date never matches.
    """
    wanted_tiles = {t.upper() for t in tiles or []}
    found = []
    for image in images:
        if image.collection != collection_id or not image.date or not (start <= image.date <= end):
            continue
        if bbox and (image.bbox is None or not _intersects(image.bbox, bbox)):
            continue
        if wanted_tiles and (image.kind != "scene" or image.tile.upper() not in wanted_tiles):
            continue
        found.append(image)
    return sorted(found, key=lambda image: (image.date, image.item_id), reverse=True)


def to_stac_item(image: LocalImage):
    """A pystac Item whose assets are the downloaded files, so cards and loading work offline."""
    from ..lib import pystac

    xmin, ymin, xmax, ymax = image.bbox or (0.0, 0.0, 0.0, 0.0)
    geometry = {
        "type": "Polygon",
        "coordinates": [[[xmin, ymin], [xmax, ymin], [xmax, ymax], [xmin, ymax], [xmin, ymin]]],
    }
    when = datetime.strptime(image.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    properties = {"bdc:local": True, "bdc:tiles": [image.tile]}
    if image.layer_file and not image.band_files:
        properties["bdc:local_layer"] = image.layer_file
        properties["bdc:local_layer_bands"] = list(image.layer_bands)
    item = pystac.Item(
        id=image.item_id,
        geometry=geometry,
        bbox=[xmin, ymin, xmax, ymax],
        datetime=when,
        properties=properties,
        collection=image.collection,
    )
    for band, path in image.band_files.items():
        item.add_asset(band, pystac.Asset(href=path, media_type=pystac.MediaType.GEOTIFF, roles=["data"]))
    return item
