"""
STAC Client Configuration

Handles fetching STAC collections and defining core config variables.
Provides the entry point for API interactions.

Developed by Baggio Luiz de Castro e Silva
INPE - Sao Jose dos Campos, 2026
"""

from urllib.parse import quote, urljoin

import requests

from ..logger import warning
from ..net import STAC_PAGE_S

STAC_URL = "https://data.inpe.br/bdc/stac/v1/"


class _TimedSession(requests.Session):
    """A session whose requests without a time limit get ``STAC_PAGE_S``."""

    def send(self, request, **kwargs):
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = STAC_PAGE_S
        return super().send(request, **kwargs)


def open_stac_client(pystac_client, url):
    """A pystac_client ``Client`` for ``url`` whose requests give up after ``STAC_PAGE_S``.

    The bundled pystac_client sends its requests without a time limit, so a
    server that accepts the connection and never answers would hold the
    calling thread for good. Conformance is handled as ``Client.open`` does.
    """
    stac_io = pystac_client.stac_api_io.StacApiIO()
    stac_io.session = _TimedSession()
    client = pystac_client.Client.from_file(url, stac_io=stac_io)
    if "conformsTo" not in client.extra_fields and client.get_links("search"):
        client._stac_io.set_conformance(None)
    return client


def search_items(search):
    """Items of a pystac_client search: ``items()``, or ``get_items()`` before 0.5.

    The bundled pystac_client (0.3.2) only has ``get_items()``; a newer one
    imported first by another plugin warns that it is deprecated.
    """
    return search.items() if hasattr(search, "items") else search.get_items()


BDC_DOC_URL = "https://brazil-data-cube.github.io/products.html"

# Supported collection IDs (used to filter STAC responses)
SUPPORTED_COLLECTION_IDS = {
    "S2-16D-2",
    "S2_L2A-1",
    "LANDSAT-16D-1",
    "landsat-2",
    "CBERS4-WFI-16D-2",
    "CBERS-WFI-8D-1",
    "CBERS4-MUX-2M-1",
    "AMZ1-WFI-L4-SR-1",
    "mod13q1-6.1",
}

# Mapping of bdc:grs from STAC to plugin-specific grid names
GRS_TO_GRID = {
    "BDC_SM_V2": "BDC_SM_V2",
    "BDC_MD_V2": "BDC_MD_V2",
    "BDC_LG_V2": "BDC_LG_V2",
    "MGRS": "MGRS",
    "WRS2": "WRS2",
    "STG": "BDC_SM_V2",  # MODIS STG maps to BDC_SM_V2 tiles here
    "AMAZONIA1_WFI_GRID": "grid_amazonia_1_wfi",  # Amazonia-1 WFI native scene grid (121 features)
    "CBERS4_MUX_GRID": "MUX_GRID",  # CBERS-4 MUX uses its own grid
    "GRID_CBERS4_MUX": "MUX_GRID",  # Alias for CBERS-4 MUX grid in raw collections
}

# Default STAC search limit (configurable, avoids silent truncation)
DEFAULT_MAX_ITEMS = 1000


def collection_has_geotiff_assets(collection: dict) -> bool:
    """Return whether a STAC collection advertises at least one GeoTIFF asset."""
    item_assets = collection.get("item_assets", {})
    if not isinstance(item_assets, dict):
        return False

    return any(
        "image/tiff" in str(asset.get("type", "")).lower()
        or "application/geotiff" in str(asset.get("type", "")).lower()
        for asset in item_assets.values()
        if isinstance(asset, dict)
    )


def collection_is_cog(collection: dict) -> bool:
    """Return whether title or asset media type identifies a collection as COG."""
    title = str(collection.get("title", "")).lower()
    if "cog" in title or "cloud optimized" in title:
        return True

    item_assets = collection.get("item_assets", {})
    if not isinstance(item_assets, dict):
        return False

    return any(
        "cloud-optimized" in str(asset.get("type", "")).lower()
        for asset in item_assets.values()
        if isinstance(asset, dict)
    )


def is_supported_image_collection(collection: dict) -> bool:
    """Return whether the collection can follow the plugin's GeoTIFF/VRT path.

    COG-backed mosaics, radar/ocean products, and single-asset visual products
    use the same STAC item and ``/vsicurl/`` VRT flow as the existing optical
    collections. Collections that advertise assets but no GeoTIFF remain
    excluded (for example ZIP bundles, NetCDF, and GRIB products).
    """
    item_assets = collection.get("item_assets", {})
    if not isinstance(item_assets, dict):
        return False
    if item_assets and not collection_has_geotiff_assets(collection):
        return False

    bdc_type = collection.get("bdc:type", "")
    grs = collection.get("bdc:grs")
    return collection_is_cog(collection) or bdc_type == "cube" or grs in GRS_TO_GRID


def _fetch_all_stac_collections(base_url: str, timeout=STAC_PAGE_S) -> list:
    """Fetch all collections from a STAC /collections endpoint, following pagination.

    A ``next`` link may be relative, and one that points back to a page
    already read ends the walk. An error on the first page raises, so the
    caller can tell an unreachable server from an empty catalog; an error on
    a later page keeps the collections read so far.
    """
    all_collections = []
    next_url = base_url
    visited = set()
    while next_url and next_url not in visited:
        visited.add(next_url)
        try:
            resp = requests.get(next_url, timeout=timeout)
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}")
            data = resp.json()
        except Exception as exc:
            if not all_collections:
                raise
            warning(f"Error fetching STAC collections page ({next_url}): {exc}")
            break
        all_collections.extend(data.get("collections", []))
        href = next((lnk.get("href") for lnk in data.get("links", []) if lnk.get("rel") == "next"), None)
        next_url = urljoin(next_url, href) if href else None
    return all_collections


class AssetNames(set):
    """Asset names seen in a collection's items.

    ``complete`` is False when the scan stopped at its page budget before
    seeing every item, so an expected name that is missing may still exist
    in older items.
    """

    complete = True


def fetch_collection_asset_names(collection_id: str, expected_assets=(), timeout=STAC_PAGE_S, max_pages: int = 3):
    """Return asset names found in current items of a collection (an AssetNames set).

    The first-item request is a cheap fast path for collections whose items all
    expose the advertised assets. Otherwise up to ``max_pages`` pages are read,
    newest first. A collection can advertise a band that only older items carry
    (Landsat 4-7 ``lwir`` next to Landsat 8-9 ``lwir11``); scanning until it
    turns up could mean paging through the whole catalogue, so the scan stops at
    the budget and reports itself incomplete instead.
    """
    items_url = f"{STAC_URL}collections/{quote(collection_id, safe='')}/items"
    expected = set(expected_assets)

    def _fetch_page(url, params=None):
        response = requests.get(url, params=params, timeout=timeout)
        if response.status_code != 200:
            raise RuntimeError(f"STAC items request failed with HTTP {response.status_code}")
        return response.json()

    found = AssetNames()
    first_page = _fetch_page(items_url, {"limit": 1})
    found.update(name for item in first_page.get("features", []) for name in item.get("assets", {}))
    if not first_page.get("features") or expected.issubset(found):
        return found

    next_url = items_url
    params = {"limit": DEFAULT_MAX_ITEMS}
    visited = set()
    pages = 0
    while next_url and next_url not in visited:
        if pages >= max_pages:
            found.complete = False
            break
        visited.add(next_url)
        page = _fetch_page(next_url, params)
        pages += 1
        params = None
        found.update(name for item in page.get("features", []) for name in item.get("assets", {}))
        if expected.issubset(found):
            break
        next_href = next(
            (link.get("href") for link in page.get("links", []) if link.get("rel") == "next"),
            None,
        )
        next_url = urljoin(next_url, next_href) if next_href else None
    return found


def collection_is_cloud_optimized(collection: dict) -> bool:
    """Return whether a STAC collection advertises its raster assets as COGs.

    Inspects the ``item_assets`` block in the STAC collection metadata. A COG
    is identified by the ``profile=cloud-optimized`` parameter in its GeoTIFF
    media type (e.g. ``image/tiff; application=geotiff; profile=cloud-optimized``).

    Redundancy safeguard: Scene-level DN products (such as CB4A-WFI-L2-DN-1 or
    AMZ1-WFI-L4-DN-1) are raw untiled rasters without internal pyramids, even
    if a STAC collection entry carries an erroneous cloud-optimized profile label.
    """
    cid = str(collection.get("id", "")).lower()
    title = str(collection.get("title", "")).lower()

    # Redundancy safeguard: raw scene-level DN products in BDC are non-pyramided GeoTIFFs
    if "-dn" in cid or "level-2-dn" in title or "level-4-dn" in title or "-dn-" in cid:
        if "cog" not in title and "cloud-optimized" not in title and "cloud optimized" not in title:
            return False

    assets = collection.get("item_assets")
    if isinstance(assets, dict) and assets:
        raster_types = [
            str(a.get("type", "")).lower()
            for a in assets.values()
            if isinstance(a, dict) and "tiff" in str(a.get("type", "")).lower()
        ]
        if raster_types:
            return any("cloud-optimized" in t for t in raster_types)

    if "cog" in title or "cloud optimized" in title:
        return True

    bdc_type = str(collection.get("bdc:type", "")).lower()
    if bdc_type in ("cube", "mosaic"):
        return True

    return False
