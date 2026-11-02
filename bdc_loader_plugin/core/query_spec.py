# -*- coding: utf-8 -*-
"""
Query Specification and Code Generator Module.

Provides serialization, deserialization, schema validation, and multi-language
code generation (JSON, YAML, Python, R sits, R rstac, cURL) for STAC search queries.

Developed by Baggio Luiz de Castro e Silva
INPE - Sao Jose dos Campos, 2026
"""

import json
import logging
import os
from datetime import datetime

try:
    import yaml

    HAS_YAML = True
except ImportError:
    HAS_YAML = False

_logger = logging.getLogger("bdc_loader")
DEFAULT_STAC_URL = "https://data.inpe.br/bdc/stac/v1"

# BDC STAC collection IDs (uppercase) that have an equivalent in the R 'sits'
# package BDC source. sits only exposes regularized data cubes, so most of the
# BDC catalog (raw scenes, mosaics, DN products) has no sits equivalent and must
# be flagged. Keys are matched case-insensitively (see sits_collection_for).
SITS_BDC_COLLECTION_MAP = {
    "S2-16D-2": "SENTINEL-2-16D",
    "CBERS4-WFI-16D-2": "CBERS-WFI-16D",
    "CBERS-WFI-16D-1": "CBERS-WFI-16D",
    "CBERS-WFI-8D-1": "CBERS-WFI-8D",
    "CBERS4-WFI-8D-2": "CBERS-WFI-8D",
    "CBERS4-MUX-2M-1": "CBERS-MUX-2M",
    "LANDSAT-16D-1": "LANDSAT-OLI-16D",
    "LANDSAT-OLI-16D-1": "LANDSAT-OLI-16D",
    "MOD13Q1-6.1": "MOD13Q1-6.1",
    "MYD13Q1-6.1": "MYD13Q1-6.1",
}


def sits_collection_for(collection_id: str):
    """Returns the sits BDC collection name for a BDC collection id, or None when
    the sits package has no BDC equivalent for it."""
    if not collection_id:
        return None
    return SITS_BDC_COLLECTION_MAP.get(collection_id.strip().upper())


def clean_collection_id(raw_name: str) -> str:
    """Extracts clean STAC collection ID from human display titles."""
    if not raw_name:
        return "S2-16D-2"
    text = str(raw_name).strip()
    if "(" in text and ")" in text:
        text = text.split("(")[-1].split(")")[0].strip()
    for prefix in ("[CUBE] ", "[COLLECTION] ", "[MOSAIC] "):
        text = text.replace(prefix, "")
    return text.strip()


def validate_query_spec(data: dict) -> tuple:
    """Validates a QuerySpec dictionary structure and parameters."""
    if not isinstance(data, dict):
        return False, "Query specification must be a valid JSON or YAML dictionary object."

    collection = data.get("collection")
    if not collection or not isinstance(collection, str):
        return False, "Missing or invalid 'collection' field in query specification."

    if "temporal" in data:
        temporal = data["temporal"]
        if not isinstance(temporal, dict):
            return False, "Field 'temporal' must be an object with 'start' and 'end' dates."
        s_str, e_str = temporal.get("start"), temporal.get("end")
        if s_str and e_str:
            try:
                if datetime.strptime(str(s_str), "%Y-%m-%d") > datetime.strptime(str(e_str), "%Y-%m-%d"):
                    return False, "Start date must not be after end date."
            except ValueError:
                return False, "Invalid date format. Use YYYY-MM-DD (e.g. 2024-01-01)."

    filters = data.get("filters", {})
    if not isinstance(filters, dict):
        return False, "Field 'filters' must be an object."
    if "cloud_cover_max" in filters:
        try:
            cloud = float(filters["cloud_cover_max"])
        except (TypeError, ValueError):
            cloud = -1.0
        if not 0 <= cloud <= 100:
            return False, "Field 'cloud_cover_max' must be a number from 0 to 100."
    if "limit" in filters:
        limit = filters["limit"]
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            return False, "Field 'limit' must be a whole number greater than 0."

    if "spatial" in data:
        spatial = data["spatial"]
        if not isinstance(spatial, dict):
            return False, "Field 'spatial' must be an object."

        sp_type = spatial.get("type")
        if sp_type not in ("tiles", "bbox", "vector"):
            return False, f"Unknown spatial type '{sp_type}'. Must be 'tiles', 'bbox', or 'vector'."

        if sp_type == "tiles" and spatial.get("tiles") is not None and not isinstance(spatial["tiles"], list):
            return False, "Field 'tiles' must be a list of tile IDs."

        if sp_type in ("bbox", "vector") and spatial.get("bbox"):
            bbox = spatial["bbox"]
            if not isinstance(bbox, list) or len(bbox) != 4:
                return False, "Field 'bbox' must contain exactly 4 coordinates [west, south, east, north]."
            try:
                w, s, e, n = [float(v) for v in bbox]
                if not (-180 <= w <= 180 and -180 <= e <= 180 and -90 <= s <= 90 and -90 <= n <= 90):
                    return False, "BBOX coordinates are out of valid geographical bounds (WGS84)."
                if w >= e or s >= n:
                    return False, "Invalid BBOX: minimum longitude/latitude is greater than maximum."
            except (ValueError, TypeError):
                return False, "Invalid numeric values in BBOX coordinates."

    return True, f"Valid query specification (Collection: {clean_collection_id(collection)})"


def parse_query_text(raw_text: str) -> tuple:
    """Parses raw text (JSON or YAML) into a validated QuerySpec dict."""
    if not raw_text or not raw_text.strip():
        return False, None, "Paste JSON or YAML query text in the field above or load from a file."

    clean_text = raw_text.strip()
    try:
        parsed_data = json.loads(clean_text)
    except json.JSONDecodeError as json_err:
        if HAS_YAML:
            try:
                parsed_data = yaml.safe_load(clean_text)
            except Exception:
                return False, None, f"JSON/YAML syntax error on line {json_err.lineno}: {json_err.msg}"
        else:
            return False, None, f"JSON syntax error on line {json_err.lineno}: {json_err.msg}"
    except Exception as exc:
        return False, None, f"Decoding error: {exc}"

    ok, msg = validate_query_spec(parsed_data)
    return (True, parsed_data, msg) if ok else (False, None, msg)


def build_ui_query_spec(dialog) -> dict:
    """Extracts current UI input state from BDCLoaderDialog into a QuerySpec dict."""
    from qgis.PyQt.QtCore import Qt

    idx = dialog.collection_combo.currentIndex() if hasattr(dialog, "collection_combo") else 0
    raw_coll = (
        dialog.collection_combo.itemData(idx, Qt.ItemDataRole.UserRole) if hasattr(dialog, "collection_combo") else ""
    )
    if not raw_coll and hasattr(dialog, "collection_combo"):
        raw_coll = dialog.collection_combo.currentText()

    start_date, end_date = "2024-01-01", "2024-12-31"
    if hasattr(dialog, "range_slider"):
        start_date = dialog.range_slider.get_start_date().toString("yyyy-MM-dd")
        end_date = dialog.range_slider.get_end_date().toString("yyyy-MM-dd")

    bands = []
    if hasattr(dialog, "selected_bands"):
        for i in range(dialog.selected_bands.count()):
            item = dialog.selected_bands.item(i)
            b_name = item.data(Qt.ItemDataRole.UserRole) or item.text()
            if b_name:
                bands.append(b_name)

    spec = {
        "version": "1.0",
        "stac_url": getattr(dialog, "stac_url", DEFAULT_STAC_URL),
        "collection": clean_collection_id(raw_coll),
        "temporal": {"start": start_date, "end": end_date},
        "filters": {
            "cloud_cover_max": dialog.filter_cloud_spin.value() if hasattr(dialog, "filter_cloud_spin") else 100,
            "limit": dialog.limit_spin.value() if hasattr(dialog, "limit_spin") else 100,
            "downloaded_only": getattr(dialog, "_show_downloaded_only", False),
        },
        "bands": bands,
    }

    valid_tiles = dialog.get_tiles_list() if hasattr(dialog, "get_tiles_list") else []
    bbox = dialog.get_bbox_from_extent() if hasattr(dialog, "get_bbox_from_extent") else None
    shape_bbox = dialog._get_shape_bbox() if hasattr(dialog, "_get_shape_bbox") else None
    shape_file = getattr(dialog, "_shape_file_path", None)
    if not shape_file and hasattr(dialog, "shape_file_input") and dialog.shape_file_input.text().strip():
        # A project layer without a file shows "Layer: <name>"; that is no path.
        text = dialog.shape_file_input.text().strip()
        shape_file = "" if text.startswith("Layer: ") else text

    is_shape_active = (
        dialog._is_shape_search_active()
        if hasattr(dialog, "_is_shape_search_active")
        else bool(shape_file or shape_bbox)
    )

    if is_shape_active and (shape_bbox or shape_file):
        layer_name = (
            str(dialog.shape_layer_combo.currentData() or "")
            if hasattr(dialog, "shape_layer_combo") and dialog.shape_layer_combo.isVisible()
            else ""
        )
        attr_field = (
            str(dialog.shape_attr_combo.currentData())
            if hasattr(dialog, "shape_attr_combo") and dialog.shape_attr_combo.currentData()
            else None
        )
        is_merged = dialog.shape_merge_check.isChecked() if hasattr(dialog, "shape_merge_check") else False
        selected_names = []
        if not is_merged and hasattr(dialog, "shape_feature_list"):
            for i in range(dialog.shape_feature_list.count()):
                item = dialog.shape_feature_list.item(i)
                if item.checkState() == Qt.CheckState.Checked:
                    selected_names.append(item.text())

        spec["spatial"] = {
            "type": "vector",
            "file": shape_file or "",
            "layer": layer_name,
            "attribute": attr_field,
            "merged": is_merged,
            "selected_features": selected_names,
            "bbox": shape_bbox or [],
            "is_extent_crop": dialog.is_extent_crop_mode() if hasattr(dialog, "is_extent_crop_mode") else False,
        }
    elif valid_tiles:
        spec["spatial"] = {"type": "tiles", "tiles": valid_tiles}
    elif bbox:
        spec["spatial"] = {
            "type": "bbox",
            "bbox": bbox,
            "is_extent_crop": dialog.is_extent_crop_mode() if hasattr(dialog, "is_extent_crop_mode") else False,
        }
    else:
        spec["spatial"] = {"type": "tiles", "tiles": []}

    return spec


def apply_ui_query_spec(dialog, spec: dict):
    """Applies a QuerySpec dict to BDCLoaderDialog UI controls and triggers UI updates."""
    from qgis.PyQt.QtCore import QDate, Qt

    target_id = clean_collection_id(spec.get("collection"))
    if target_id and hasattr(dialog, "collection_combo"):
        for i in range(dialog.collection_combo.count()):
            u_data = dialog.collection_combo.itemData(i, Qt.ItemDataRole.UserRole)
            if clean_collection_id(u_data) == target_id or target_id in dialog.collection_combo.itemText(i):
                # setCurrentIndex fires currentTextChanged -> on_collection_changed.
                dialog.collection_combo.setCurrentIndex(i)
                break

    temporal = spec.get("temporal", {})
    if temporal.get("start") and temporal.get("end") and hasattr(dialog, "range_slider"):
        ds = QDate.fromString(str(temporal["start"]), "yyyy-MM-dd")
        de = QDate.fromString(str(temporal["end"]), "yyyy-MM-dd")
        if ds.isValid() and de.isValid():
            start_kept = dialog.range_slider.set_start_date(ds)
            end_kept = dialog.range_slider.set_end_date(de)
            if not (start_kept and end_kept) and hasattr(dialog, "_set_status"):
                shown = (
                    dialog.range_slider.get_start_date().toString("yyyy-MM-dd"),
                    dialog.range_slider.get_end_date().toString("yyyy-MM-dd"),
                )
                dialog._set_status(
                    f"The query period, {temporal['start']} to {temporal['end']}, goes beyond the dates of this "
                    f"collection; it was set to {shown[0]} to {shown[1]}.",
                    "warning",
                )

    filters = spec.get("filters", {})
    if "cloud_cover_max" in filters and hasattr(dialog, "filter_cloud_spin"):
        dialog.filter_cloud_spin.setValue(round(float(filters["cloud_cover_max"])))
    if "limit" in filters and hasattr(dialog, "limit_spin"):
        dialog.limit_spin.setValue(int(filters["limit"]))

    _apply_spatial(dialog, spec.get("spatial", {}))

    bands = spec.get("bands", [])
    if bands and hasattr(dialog, "selected_bands"):
        from qgis.PyQt.QtWidgets import QListWidgetItem

        dialog.selected_bands.clear()
        for b in bands:
            item = QListWidgetItem(str(b))
            item.setData(Qt.ItemDataRole.UserRole, str(b))
            dialog.selected_bands.addItem(item)
        if hasattr(dialog, "_sync_bands_with_selected_items"):
            dialog._sync_bands_with_selected_items()


def _apply_spatial(dialog, spatial: dict):
    """Reapplies a single spatial mode (tiles, bbox, or vector) to the dialog.

    The dialog enforces mutual exclusivity between tiles/extent/vector through its
    own signal handlers, so the target mode is set through the same entry points the
    user would use. Non-target modes are cleared first for a deterministic result.
    """
    sp_type = spatial.get("type")

    if hasattr(dialog, "clear_tiles"):
        dialog.clear_tiles()
    if hasattr(dialog, "_clear_extent"):
        dialog._clear_extent()
    elif hasattr(dialog, "extent_box"):
        dialog.extent_box.setActive(False)
    if hasattr(dialog, "_clear_shapefile"):
        dialog._clear_shapefile()

    if sp_type == "tiles" and spatial.get("tiles"):
        # Setting the tiles text triggers _on_tiles_text_changed, which locks
        # the extent and vector modes automatically.
        if hasattr(dialog, "tiles_input"):
            dialog.tiles_input.setText(", ".join(str(t) for t in spatial["tiles"]))

    elif sp_type == "bbox" and len(spatial.get("bbox", [])) == 4:
        # _apply_manual_bbox reads the bbox edit, activates extent_box, and locks
        # the other modes. Requires at least one map layer to anchor the canvas CRS.
        if hasattr(dialog, "_extent_bbox_edit") and hasattr(dialog, "_apply_manual_bbox"):
            dialog._extent_bbox_edit.setText(",".join(str(v) for v in spatial["bbox"]))
            dialog._apply_manual_bbox()
            if spatial.get("is_extent_crop") and hasattr(dialog, "_extent_mode_crop"):
                dialog._extent_mode_crop.setChecked(True)

    elif sp_type == "vector":
        v_file = spatial.get("file")
        if v_file and os.path.exists(v_file) and hasattr(dialog, "_load_shapefile"):
            try:
                dialog._load_shapefile(v_file)
                _restore_vector_state(dialog, spatial)
            except Exception as exc:
                _logger.warning("Could not load vector file '%s': %s", v_file, exc)


def _restore_vector_state(dialog, spatial: dict):
    """Restores GPKG layer, attribute field, merge mode and per-feature selection
    after a vector file has been loaded, so a vector ROI round-trips fully."""
    from qgis.PyQt.QtCore import Qt

    layer = spatial.get("layer")
    if layer and hasattr(dialog, "shape_layer_combo") and dialog.shape_layer_combo.isVisible():
        idx = dialog.shape_layer_combo.findData(layer)
        if idx >= 0:
            dialog.shape_layer_combo.setCurrentIndex(idx)

    attribute = spatial.get("attribute")
    if attribute and hasattr(dialog, "shape_attr_combo"):
        idx = dialog.shape_attr_combo.findData(attribute)
        if idx >= 0:
            # Changing the attribute repopulates the feature list (all checked).
            dialog.shape_attr_combo.setCurrentIndex(idx)

    merged = bool(spatial.get("merged", False))
    if hasattr(dialog, "shape_merge_check"):
        dialog.shape_merge_check.setChecked(merged)

    selected = spatial.get("selected_features")
    if not merged and selected and hasattr(dialog, "shape_feature_list"):
        wanted = set(selected)
        for i in range(dialog.shape_feature_list.count()):
            item = dialog.shape_feature_list.item(i)
            item.setCheckState(Qt.CheckState.Checked if item.text() in wanted else Qt.CheckState.Unchecked)


def _extract_query_meta(spec: dict):
    """Internal helper to extract structured parameters from QuerySpec."""
    clean_coll = clean_collection_id(spec.get("collection", "S2-16D-2"))
    sits_coll = sits_collection_for(clean_coll) or clean_coll
    temp = spec.get("temporal", {})
    start, end = temp.get("start", "2024-01-01"), temp.get("end", "2024-12-31")
    sp = spec.get("spatial", {})
    sp_type, tiles, bbox, v_file = sp.get("type"), sp.get("tiles", []), sp.get("bbox", []), sp.get("file", "")
    v_attr = sp.get("attribute")
    v_merged = sp.get("merged", False)
    v_features = sp.get("selected_features", [])
    flt = spec.get("filters", {})
    cloud, limit = flt.get("cloud_cover_max", 100), flt.get("limit", 100)
    bands = spec.get("bands", [])
    stac_url = spec.get("stac_url", DEFAULT_STAC_URL)
    return (
        clean_coll,
        sits_coll,
        start,
        end,
        sp_type,
        tiles,
        bbox,
        v_file,
        v_attr,
        v_merged,
        v_features,
        cloud,
        limit,
        bands,
        stac_url,
    )


def _r_vector_load_lines(v_file, v_merged, v_attr, v_features):
    """R lines that read a vector ROI into `roi_vector`, optionally filtering features."""
    lines = [
        "# Read vector ROI (all features merged into one boundary)"
        if v_merged
        else "# Read vector ROI (shapefile / GeoPackage)"
    ]
    lines.append(f'roi_vector <- sf::st_read("{v_file}")')
    if not v_merged and v_features:
        if v_attr:
            feats = ", ".join(f"{f!r}" for f in v_features)
            lines.append("# Keep only the features selected in the plugin UI")
            lines.append(f"roi_vector <- roi_vector[roi_vector${v_attr} %in% c({feats}), ]")
        else:
            lines.append("# NOTE: features were selected by FID in the UI; pick an attribute")
            lines.append("# field in the plugin to reproduce the exact selection here.")
    return lines


def _py_vector_load_lines(v_file, v_merged, v_attr, v_features):
    """Python lines that read a vector ROI into `gdf`, optionally filtering features."""
    lines = [
        "# Read vector ROI (all features merged into one boundary)"
        if v_merged
        else "# Read vector ROI (shapefile / GeoPackage)"
    ]
    lines.append(f'gdf = gpd.read_file("{v_file}")')
    if not v_merged and v_features:
        if v_attr:
            lines.append("# Keep only the features selected in the plugin UI")
            lines.append(f'gdf = gdf[gdf["{v_attr}"].isin({v_features})]')
        else:
            lines.append("# NOTE: features were selected by FID in the UI; pick an attribute")
            lines.append("# field in the plugin to reproduce the exact selection here.")
    return lines


def query_to_json(spec: dict) -> str:
    """Formats QuerySpec dict to pretty JSON string."""
    return json.dumps(spec, indent=2, ensure_ascii=False)


def query_to_yaml(spec: dict) -> str:
    """Formats QuerySpec dict to YAML string."""
    return yaml.dump(spec, sort_keys=False, allow_unicode=True) if HAS_YAML else query_to_json(spec)


def query_to_r_sits(spec: dict) -> str:
    """Generates R sits package data cube script from QuerySpec."""
    (
        clean_coll,
        sits_coll,
        start,
        end,
        sp_type,
        tiles,
        bbox,
        v_file,
        v_attr,
        v_merged,
        v_features,
        cloud,
        _,
        bands,
        _,
    ) = _extract_query_meta(spec)

    lines = ["library(sits)"]
    if sp_type == "vector" and v_file:
        lines.append("library(sf)")

    lines.append("")
    if sits_collection_for(clean_coll) is None:
        lines.extend(
            [
                "# ----------------------------------------------------------------------",
                f'# WARNING: collection "{clean_coll}" is not available in the sits BDC source.',
                "# sits exposes only a subset of BDC collections (regularized data cubes),",
                "# so sits_cube() below will fail with",
                '# ".check_source_collection: invalid collection parameter".',
                '# Confirm the supported list with: sits::sits_list_collections(source = "BDC")',
                '# For this collection use the "R - rstac" or "Python" export instead.',
                "# ----------------------------------------------------------------------",
                "",
            ]
        )

    if sp_type == "vector" and v_file:
        lines.extend(_r_vector_load_lines(v_file, v_merged, v_attr, v_features))
        lines.append("")

    lines.extend(
        [
            "# Create BDC data cube using the sits package",
            "cube <- sits_cube(",
            '  source = "BDC",',
            f'  collection = "{sits_coll}",',
        ]
    )

    if sp_type == "vector" and v_file:
        lines.append("  roi = roi_vector,")
    elif sp_type == "tiles" and tiles:
        lines.append(f"  tiles = c({', '.join(f'{t!r}' for t in tiles)}),")
    elif len(bbox) == 4:
        lines.append(f"  roi = c(lon_min = {bbox[0]}, lat_min = {bbox[1]}, lon_max = {bbox[2]}, lat_max = {bbox[3]}),")

    if bands:
        lines.append(f"  bands = c({', '.join(f'{b!r}' for b in bands)}),")

    lines.extend([f'  start_date = "{start}",', f'  end_date = "{end}"', ")"])
    if cloud < 100:
        lines.append(f"# Note: Cloud cover filter <= {cloud}% applied during processing")
    lines.extend(["", "# Plot data cube summary", "plot(cube)"])
    return "\n".join(lines)


def query_to_r_rstac(spec: dict) -> str:
    """Generates R rstac API search script from QuerySpec."""
    (
        clean_coll,
        _,
        start,
        end,
        sp_type,
        tiles,
        bbox,
        v_file,
        v_attr,
        v_merged,
        v_features,
        cloud,
        limit,
        bands,
        stac_url,
    ) = _extract_query_meta(spec)

    lines = ["library(rstac)"]
    if sp_type == "vector" and v_file:
        lines.append("library(sf)")
    lines.append("")

    if sp_type == "vector" and v_file:
        lines.extend(_r_vector_load_lines(v_file, v_merged, v_attr, v_features))
        lines.extend(["bbox_coords <- as.numeric(sf::st_bbox(roi_vector))", ""])

    lines.extend(
        [
            f'query <- stac("{stac_url}") %>%',
            "  stac_search(",
            f'    collections = "{clean_coll}",',
        ]
    )

    if sp_type == "vector" and v_file:
        lines.append("    bbox = bbox_coords,")
    elif sp_type in ("bbox", "vector") and len(bbox) == 4:
        lines.append(f"    bbox = c({', '.join(str(v) for v in bbox)}),")

    lines.extend([f'    datetime = "{start}/{end}",', f"    limit = {limit}"])

    # rstac ext_query takes comparison expressions, not raw STAC query JSON.
    query_exprs = []
    if sp_type == "tiles" and tiles:
        query_exprs.append(f'"bdc:tiles" %in% c({", ".join(f"{t!r}" for t in tiles)})')
    if cloud < 100:
        query_exprs.append(f'"eo:cloud_cover" <= {cloud}')

    if query_exprs:
        lines.append("  ) %>%")
        lines.append(f"  ext_query({', '.join(query_exprs)})")
    else:
        lines.append("  )")

    # Build the query object above, then issue a single request.
    lines.extend(["", "items <- post_request(query)", 'cat("Items found:", length(items$features), "\\n")'])

    if bands:
        lines.extend(["", f"# Selected bands for processing: {', '.join(bands)}"])

    return "\n".join(lines)


def query_to_python(spec: dict) -> str:
    """Generates Python pystac-client search script from QuerySpec."""
    (
        clean_coll,
        _,
        start,
        end,
        sp_type,
        tiles,
        bbox,
        v_file,
        v_attr,
        v_merged,
        v_features,
        cloud,
        limit,
        bands,
        stac_url,
    ) = _extract_query_meta(spec)

    lines = []
    if sp_type == "vector" and v_file:
        lines.append("import geopandas as gpd")

    lines.extend(
        [
            "from pystac_client import Client",
            "",
            f'catalog = Client.open("{stac_url}")',
        ]
    )

    if sp_type == "vector" and v_file:
        lines.extend(_py_vector_load_lines(v_file, v_merged, v_attr, v_features))
        lines.extend(["bbox = list(gdf.total_bounds)", ""])

    lines.extend(
        [
            "search_params = {",
            f'    "collections": ["{clean_coll}"],',
            f'    "datetime": "{start}/{end}",',
            f'    "limit": {limit},',
        ]
    )

    if sp_type == "vector" and v_file:
        lines.append('    "bbox": bbox,')
    elif sp_type in ("bbox", "vector") and len(bbox) == 4:
        lines.append(f'    "bbox": {bbox},')

    stac_query = {}
    if sp_type == "tiles" and tiles:
        stac_query["bdc:tiles"] = {"in": tiles}
    if cloud < 100:
        stac_query["eo:cloud_cover"] = {"lte": cloud}

    if stac_query:
        lines.append(f'    "query": {json.dumps(stac_query)},')

    lines.extend(
        [
            "}",
            "search = catalog.search(**search_params)",
            "items = list(search.items())",
            'print(f"Items found: {len(items)}")',
        ]
    )

    if bands:
        lines.extend(
            [
                "",
                f"selected_bands = {bands}",
                "for item in items[:5]:",
                "    for b in selected_bands:",
                "        if b in item.assets:",
                '            print(f"{item.id} [{b}]: {item.assets[b].href}")',
            ]
        )

    return "\n".join(lines)


def query_to_curl(spec: dict) -> str:
    """Generates cURL / HTTP POST request payload string from QuerySpec."""
    clean_coll, _, start, end, sp_type, tiles, bbox, _, _, _, _, cloud, limit, _, stac_url = _extract_query_meta(spec)
    search_endpoint = stac_url.rstrip("/") + "/search"

    payload = {"collections": [clean_coll], "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z", "limit": limit}

    if sp_type in ("bbox", "vector") and len(bbox) == 4:
        payload["bbox"] = bbox

    stac_query = {}
    if sp_type == "tiles" and tiles:
        stac_query["bdc:tiles"] = {"in": tiles}
    if cloud < 100:
        stac_query["eo:cloud_cover"] = {"lte": cloud}

    if stac_query:
        payload["query"] = stac_query

    return f'curl -X POST "{search_endpoint}" \\\n  -H "Content-Type: application/json" \\\n  -d \'{json.dumps(payload, indent=2)}\''
