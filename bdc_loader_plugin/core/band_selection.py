"""Band names resolved to the asset keys of STAC items.

Also reports which bands the selected items lack.
"""

# Aliases for inconsistent band names between item_assets and actual items
BAND_ALIASES = {
    "rgb": "tci",
    "tci": "visual",
    "visual": "tci",
}


def resolve_band(band_name, item_assets_dict):
    """Resolve band name, trying aliases and case-insensitive match."""
    if band_name in item_assets_dict:
        return band_name
    alias = BAND_ALIASES.get(band_name)
    if alias and alias in item_assets_dict:
        return alias
    for k in item_assets_dict:
        if k.lower() == band_name.lower():
            return k
    return None


def band_availability_issues(bands, items):
    """Return selected-result items that cannot provide one or more bands.

    A grouped mosaic can provide a band when at least one of its source items
    contains that asset, matching the VRT task builder's behavior. A downloaded
    multiband file is loaded whole, so it provides exactly the bands it holds.
    """
    issues = []
    for item in items:
        source_items = list(getattr(item, "_source_items", []) or []) or [item]
        missing = []
        for band in bands:
            if not any(resolve_band(band, _band_keys(source)) for source in source_items):
                missing.append(band)
        if missing:
            available = sorted({key for source in source_items for key in _band_keys(source) if key != "thumbnail"})
            issues.append((getattr(item, "id", "unknown"), missing, available))
    return issues


def _band_keys(item):
    """Assets of an item; a downloaded multiband file (local_catalog) offers the bands it holds."""
    props = getattr(item, "properties", {}) or {}
    if props.get("bdc:local_layer"):
        return dict.fromkeys(props.get("bdc:local_layer_bands") or [])
    return getattr(item, "assets", {}) or {}


def available_bands_for_items(candidate_bands, items):
    """Keep collection bands that every selected result item can provide."""
    item_list = list(items)
    if not item_list:
        return list(candidate_bands)
    unavailable = {
        band
        for _item_id, missing, _available in band_availability_issues(candidate_bands, item_list)
        for band in missing
    }
    return [band for band in candidate_bands if band not in unavailable]


def unavailable_band_reasons(candidate_bands, items):
    """Return a short reason for bands missing from current result items."""
    item_list = list(items)
    if not item_list:
        return {}

    unavailable = {
        band
        for _item_id, missing, _available in band_availability_issues(candidate_bands, item_list)
        for band in missing
    }
    return {band: "Not available." for band in candidate_bands if band in unavailable}
