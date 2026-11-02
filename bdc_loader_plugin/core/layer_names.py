"""
layer_names.py

Readable names for the layers and groups the plugin adds to the project.

A layer or group keeps its machine name (the one that also names its .vrt and
lets the plugin find it again) in a custom property, and shows a short name
in the Layers panel. Layers and groups without the property are identified
by their name, which is what older projects contain.
"""

import re

from .download_outputs import crop_label, slug

KEY_PROPERTY = "bdc_loader/key"
_UNSAFE_FILENAME_CHARS = re.compile(r"[^\w.\-]")


def _stored_key(node):
    try:
        key = node.customProperty(KEY_PROPERTY, "")
    except Exception:
        return ""
    return key if isinstance(key, str) else ""


def layer_key(node):
    """Machine name of a layer or layer-tree group."""
    return _stored_key(node) or node.name()


def set_display_name(node, key, display):
    """Show ``display`` for ``node`` while keeping ``key`` as its machine name."""
    node.setCustomProperty(KEY_PROPERTY, key)
    node.setName(display or key)


def find_group(root, key):
    """First group under ``root`` whose machine name is ``key``, or None."""
    by_name = root.findGroup(key)
    if by_name is not None and _stored_key(by_name) in ("", key):
        return by_name
    pending = list(root.children())
    while pending:
        node = pending.pop(0)
        if not hasattr(node, "addGroup"):
            continue
        if layer_key(node) == key:
            return node
        pending.extend(node.children())
    return None


def area_layer_display(collection_id, label, date, bands):
    """Layer of a crop or feature, in the pattern of tile layers with the area
    label in place of the tile: ``S2-16D-2_crop_20230712_B04-B03-B02``,
    ``S2-16D-2_Basaltos-do-Parana_20230712_B04-B03-B02``."""
    return f"{collection_id}_{slug(label, 60)}_{str(date).replace('-', '')}_{'-'.join(str(b) for b in bands)}"


def area_group_display(collection_id, area, crop_bbox=None, feature_name=None):
    """Group of one crop or vector-feature area.

    A crop reads as its corners (``S2-16D-2 / crop 47.950W 15.850S to ...``);
    a feature as its name (``S2-16D-2 / Basaltos do Paraná``).
    """
    if crop_bbox:
        try:
            return f"{collection_id} / crop {crop_label(crop_bbox)}"
        except (TypeError, ValueError):
            pass
    return f"{collection_id} / {feature_name or area}"


def build_item_naming_prefix(item_id, collection_id, tile_safe, date_str, is_mosaic, naming_format="stac") -> str:
    """Build the base (pre-band-suffix) name for a generated VRT/layer.

    naming_format:
      - "stac": the real STAC item id verbatim, so the layer name matches what the
        user sees on the STAC browser. Only applies to a single real item — mosaics
        and extent crops merge many items and have no single id.
      - "compact": collection_id + tile + date.

    Mosaics/crops (is_mosaic=True) always use collection_id + tile_safe — which
    already encodes the crop location/feature name and date, see core/search.py's
    bbox_tag — regardless of naming_format, since there's no single item id to use.
    """
    if is_mosaic:
        return f"{collection_id}_{tile_safe}"
    if naming_format == "stac" and item_id:
        return _UNSAFE_FILENAME_CHARS.sub("_", str(item_id).strip())
    return f"{collection_id}_{tile_safe}_{date_str}"


def build_vrt_layer_name(
    item_id,
    collection_id,
    tile_safe,
    date_str,
    bands,
    is_mosaic=False,
    naming_format="stac",
):
    """Build a VRT layer name using the selected naming format."""
    prefix = build_item_naming_prefix(
        item_id,
        collection_id,
        tile_safe,
        date_str,
        is_mosaic,
        naming_format,
    )
    return f"{prefix}_{'-'.join(bands)}"


def build_vrt_layer_name_candidates(item_id, collection_id, tile_safe, date_str, bands):
    """Return every name, in both naming formats, which may identify the same VRT layer."""
    names = [
        build_vrt_layer_name(item_id, collection_id, tile_safe, date_str, bands, naming_format="stac"),
        build_vrt_layer_name(item_id, collection_id, tile_safe, date_str, bands, naming_format="compact"),
    ]
    if len(bands) > 1:
        compact_prefix = build_item_naming_prefix(
            item_id,
            collection_id,
            tile_safe,
            date_str,
            False,
            "compact",
        )
        names.append(f"{compact_prefix}_{'_'.join(bands)}")
    return tuple(dict.fromkeys(names))


def _ts_points_layer_pos(root):
    """Return index after 'BDC TS Points' in root children, or 0 if not found."""
    from qgis.core import QgsLayerTreeLayer

    for i, child in enumerate(root.children()):
        if isinstance(child, QgsLayerTreeLayer):
            lyr = child.layer()
            if lyr and lyr.name() == "BDC TS Points":
                return i + 1
    return 0
