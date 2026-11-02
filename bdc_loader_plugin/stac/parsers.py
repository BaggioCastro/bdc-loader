"""
STAC Response Parsers

Collection of parsing utilities for extracting titles, formatting platforms,
resolutions, bands, and grids from STAC responses.

Developed by Baggio Luiz de Castro e Silva
INPE - Sao Jose dos Campos, 2026
"""

import logging
import os
import re
from datetime import datetime

from .fallback import ID_TO_DISPLAY_NAME

_logger = logging.getLogger("bdc_loader")

TILE_PATTERN = re.compile(r"^\d{6}$")
MGRS_PATTERN = re.compile(r"^\d{2}[A-Z]{3}$")
WRS2_PATTERN = re.compile(r"^\d{3}\d{3}$")
STG_PATTERN = re.compile(r"^h\d{2}v\d{2}$", re.IGNORECASE)
ROW_PATH_PATTERN = re.compile(r"^\d{1,3}[/_ -]\d{1,3}$")

# Assets excluded when extracting data bands from STAC
EXCLUDED_ASSETS = {
    "thumbnail",
    "CLEAROB",
    "TOTALOB",
    "PROVENANCE",
    "DATASOURCE",
    "CMASK",
    "qa_pixel",
    "qa_aerosol",
    "qa_radsat",
    "sr_cloud_qa",
    "sr_atmos_opacity",
    # landsat-2 mixes TM/ETM+/OLI scenes under one collection ID; each sensor generation
    # names its cloud/atmospheric-opacity QA mask with a different prefix for the same
    # role ("data", never selectable as a real band): TM -> tm_*, ETM+ -> etm_*, OLI has
    # none (uses qa_aerosol instead, already excluded above).
    "tm_cloud_qa",
    "tm_atmos_opacity",
    "etm_cloud_qa",
    "etm_atmos_opacity",
    "VI_Quality",
    "pixel_reliability",
    "composite_day_of_the_year",
    "sun_zenith_angle",
    "view_zenith_angle",
    "relative_azimuth_angle",
    "st_qa",
    "st_drad",
    "st_emis",
    "st_emsd",
    "st_trad",
    "st_urad",
    "st_atran",
    "st_cdist",
    "sr_stac",
    "st_stac",
    "mtl.txt",
    "mtl.xml",
    "mtl.json",
    "ang",
    "thumb_large.jpeg",
    "thumb_small.jpeg",
    "AOT",
    "WVP",
    "PVI",
    "SCL",
    "topo_data",
}


def has_valid_tile_system(grs: str) -> bool:
    """
    Checks if the specified Grid Reference System (GRS) is valid for filtering tiles.

    Args:
        grs (str): The Grid Reference System identifier.

    Returns:
        bool: True if the GRS provides a valid tile system, False otherwise.
    """
    if not grs:
        return False

    known_valid_grs = {
        "MGRS",
        "WRS2",
        "BDC_SM_V2",
        "BDC_MD_V2",
        "BDC_LG_V2",
        "STG",
        "CBERS4_MUX_GRID",
        "GRID_CBERS4_MUX",
        "AMAZONIA1_WFI_GRID",
        "grid_amazonia_1_wfi",
    }

    return grs in known_valid_grs


def build_display_name(coll_id: str, title: str, bdc_type: str) -> str:
    """
    Constructs a display name for a given STAC collection.
    Prioritizes fallback names to ensure UI consistency.

    Args:
        coll_id (str): The STAC collection ID.
        title (str): The STAC collection title.
        bdc_type (str): The BDC type (e.g., 'cube', 'collection').

    Returns:
        str: The formatted display name.
    """
    if coll_id in ID_TO_DISPLAY_NAME:
        return ID_TO_DISPLAY_NAME[coll_id]

    type_labels = {
        "cube": "Cube",
        "collection": "Scenes",
        "mosaic": "Mosaic",
        "classification": "Classification",
    }
    type_label = type_labels.get(bdc_type, bdc_type.title() if bdc_type else "Data")
    short_title = title.split(" - ")[0] if title else coll_id
    # Mosaic titles already say "Mosaic" ("CBERS-4/WFI 3M Mosaic").
    if type_label.lower() in short_title.lower().split():
        return f"{short_title} ({coll_id})"
    return f"{short_title} {type_label} ({coll_id})"


def format_platform(platform_data) -> str:
    """
    Formats the platform data retrieved from STAC into a user-friendly string.

    Args:
        platform_data: Raw platform data from the STAC item.

    Returns:
        str: A formatted platform string like 'Sentinel-2A/2B' or 'Landsat 4-9'.
    """
    if not platform_data:
        return "Unknown"

    if isinstance(platform_data, dict):
        codes = platform_data.get("code", [])
        if codes:
            return "/".join(str(c).title() for c in codes)
        return "Unknown"

    if isinstance(platform_data, str):
        return platform_data.title()

    if isinstance(platform_data, list):
        if not platform_data:
            return "Unknown"

        platforms = [str(p) for p in platform_data]

        if all(p.lower().startswith("landsat") for p in platforms):
            nums = []
            for p in platforms:
                parts = p.split("-")
                if len(parts) >= 2 and parts[-1].isdigit():
                    nums.append(int(parts[-1]))
            if nums:
                return f"Landsat {min(nums)}-{max(nums)}"

        if all(p.lower().startswith("sentinel") for p in platforms):
            variants = []
            for p in platforms:
                parts = p.lower().replace("sentinel-", "")
                variants.append(parts.upper())
            if variants:
                return f"Sentinel-{'/'.join(variants)}"

        if all(p.lower().startswith("cbers") for p in platforms):
            return " + ".join(p.upper() for p in platforms)

        return "/".join(p.title() for p in platforms)

    return str(platform_data)


def format_compositing(temporal_comp: dict, bdc_type: str) -> str:
    """
    Formats temporal composition data.

    Args:
        temporal_comp (dict): The bdc:temporal_composition dictionary.
        bdc_type (str): The BDC type.

    Returns:
        str: Extracted composition string format.
    """
    if bdc_type == "collection" or not temporal_comp:
        return "Individual scenes"

    step = temporal_comp.get("step", "")
    unit = temporal_comp.get("unit", "")

    unit_map = {
        "day": "days",
        "month": "months",
        "year": "years",
    }
    unit_en = unit_map.get(unit, unit)

    if step and unit_en:
        return f"LCF {step} {unit_en}"

    return "Temporal composition"


def extract_bands_from_assets(item_assets: dict) -> list:
    """
    Extracts purely data-based optical bands from STAC item assets,
    ignoring QA/cloud masks.

    Args:
        item_assets (dict): The assets dictionary from the STAC item.

    Returns:
        list: Sorted list of valid band/asset names.
    """
    if not item_assets:
        return []

    bands = []
    for asset_name, asset_info in item_assets.items():
        if asset_name in EXCLUDED_ASSETS:
            continue

        if asset_name.endswith("_xml") or asset_name.endswith(".xml"):
            continue

        asset_type = asset_info.get("type", "")
        if "image/tiff" not in asset_type and "application/geotiff" not in asset_type:
            continue

        bands.append(asset_name)

    return sorted(bands)


def extract_resolution(eo_bands: list) -> str:
    """
    Extracts a representative resolution indicator from STAC eo:bands.

    Args:
        eo_bands (list): The list of electro-optical band dicts.

    Returns:
        str: Resolution string, like '10m', '30m' or '10-60m'.
    """
    if not eo_bands:
        return ""

    resolutions = set()
    for band in eo_bands:
        res_x = band.get("resolution_x")
        gsd = band.get("gsd")
        res_val = res_x if res_x and res_x > 0 else gsd
        if res_val and res_val > 0:
            resolutions.add(int(res_val) if res_val == int(res_val) else res_val)

    if not resolutions:
        return ""

    if len(resolutions) == 1:
        return f"{list(resolutions)[0]}m"

    sorted_res = sorted(resolutions)
    return f"{sorted_res[0]}-{sorted_res[-1]}m"


def extract_tile_from_id(item_id: str) -> str:
    """
    Hueristically extracts a tile/scene identifier directly from a STAC Item ID.

    Args:
        item_id (str): The ID of the STAC Item.

    Returns:
        str: Tile identifier, e.g. '002011', '19MCP', '211059', or 'NA' if parsing fails.
    """
    if not item_id:
        return "NA"

    if "AMAZONIA" in item_id or "CBERS" in item_id:
        parts = item_id.split("_")
        # Scene ids contain adjacent 3-digit path/row tokens. Searching for
        # that pair remains stable when processing suffixes follow L2/L4;
        # using the final tokens mislabels composites and mosaic date ranges.
        for path, row in zip(parts, parts[1:]):
            if len(path) == len(row) == 3 and path.isdigit() and row.isdigit():
                return f"{path}/{row}"

    if item_id.startswith("S2"):
        parts = item_id.split("_")
        for part in parts:
            if part.startswith("T") and len(part) == 6 and MGRS_PATTERN.match(part[1:]):
                return part[1:]

    if item_id.startswith("L"):
        parts = item_id.split("_")
        if len(parts) >= 3 and len(parts[2]) == 6 and parts[2].isdigit():
            return parts[2]

    if "-" in item_id and "_V" in item_id:
        parts = item_id.split("_")
        # BDC cube IDs: "S2-16D-2_002011_V2023-01-01_2023-01-16"
        # tile is at parts[1] (e.g. '002011')
        if len(parts) >= 2:
            tile_candidate = parts[1]
            if TILE_PATTERN.match(tile_candidate):
                return tile_candidate

    stg_match = re.search(r"h\d{2}v\d{2}", item_id, re.IGNORECASE)
    if stg_match:
        return stg_match.group(0).lower()

    return "NA"


def _safe_path_component(value: str) -> str:
    """Sanitize a value for safe use as a filesystem path component.

    Strips directory separators, null bytes, and relative-path tricks
    (e.g. '..', leading '/') so the result can never escape the intended
    parent directory.
    """
    s = str(value)
    # Remove null bytes
    s = s.replace("\x00", "")
    # Extract only the basename (strip any directory components)
    s = os.path.basename(s)
    # Reject pure relative-nav names
    if s in ("", ".", ".."):
        return "NA"
    return s


def extract_tile_from_item(item) -> str:
    """
    Extracts the tile or path/row from a STAC item object.
    Checks properties for `bdc:tiles` or `row`/`path` before reverting to ID heuristics.

    Args:
        item: A pystac.Item.

    Returns:
        str: The tile identifier string (sanitized for filesystem safety).
    """
    props = getattr(item, "properties", {}) or {}
    tiles = props.get("bdc:tiles")
    if isinstance(tiles, list) and tiles:
        return _safe_path_component(tiles[0])
    if "row" in props and "path" in props:
        row = _safe_path_component(props["row"])
        path = _safe_path_component(props["path"])
        return f"{path}/{row}"
    item_id = _safe_path_component(getattr(item, "id", "NA"))
    tile = extract_tile_from_id(item_id)
    # Some valid scene collections (for example Sentinel-1 RTC) do not use a
    # tile grid. Keep their real STAC item id visible instead of presenting
    # the user with the ambiguous label "NA".
    return item_id if tile == "NA" else tile


def format_tile_display(tile: str, grid_type: str) -> str:
    """
    Formats the tile string for user-friendly UI display with system metadata.

    Args:
        tile (str): The raw tile identifier.
        grid_type (str): The grid system.

    Returns:
        str: Nicely formatted tile, e.g. 'WRS-2 219/066'.
    """
    if ROW_PATH_PATTERN.match(tile):
        return f"ROW/PATH {tile}"
    if grid_type == "MGRS":
        return f"MGRS {tile}"
    if grid_type == "WRS2":
        if len(tile) == 6:
            return f"WRS-2 {tile[:3]}/{tile[3:]}"
        return f"WRS-2 {tile}"
    if grid_type == "STG":
        return f"MODIS {tile}"
    if grid_type.startswith("BDC"):
        return f"BDC {tile}"
    return tile


def _item_datetime(item):
    """Naive datetime of a STAC item (``datetime`` attribute or property), or None."""
    dt = getattr(item, "datetime", None)
    if dt:
        return dt
    value = (getattr(item, "properties", {}) or {}).get("datetime")
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def group_items_by_date(items):
    """[(YYYY-MM-DD, datetime, items)] of ``items`` grouped by day, newest first.

    A group's datetime is the latest of its items; items without a date form
    an "undated" group placed by ``datetime.min``.
    """
    groups = {}
    for item in items:
        dt = _item_datetime(item)
        key = dt.strftime("%Y-%m-%d") if dt else "undated"
        group = groups.setdefault(key, {"datetime": dt, "items": []})
        if dt and (group["datetime"] is None or dt > group["datetime"]):
            group["datetime"] = dt
        group["items"].append(item)
    result = []
    for key in sorted(groups, reverse=True):
        group_dt = groups[key]["datetime"]
        if group_dt is None:
            try:
                group_dt = datetime.strptime(key, "%Y-%m-%d")
            except ValueError:
                group_dt = datetime.min
        result.append((key, group_dt, groups[key]["items"]))
    return result


def wavelength_label(wavelength):
    """'### nm' for an eo:bands center_wavelength (micrometres below 100, else nm), or None."""
    if not wavelength or wavelength <= 0:
        return None
    return f"{int(wavelength * 1000) if wavelength < 100 else int(wavelength)} nm"


def resolution_label(resolution):
    """'##m' for a positive resolution, integer when whole, or None."""
    if not resolution or resolution <= 0:
        return None
    return f"{int(resolution) if resolution == int(resolution) else resolution}m"


def cloud_cover(item):
    """The item's ``eo:cloud_cover`` in percent, or None when it has none or it is not a number."""
    value = (getattr(item, "properties", None) or {}).get("eo:cloud_cover")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
