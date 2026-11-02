# -*- coding: utf-8 -*-
"""
TSCollectionManager — STAC collection loading, filtering, and combo management.

Handles STAC collection discovery, metadata extraction, band info parsing,
and UI combo population for the time series panel.
"""

import logging
import threading
from datetime import datetime

from qgis.PyQt.QtCore import QCoreApplication, QDate, Qt
from qgis.PyQt.QtWidgets import QDialog

_logger = logging.getLogger("bdc_loader")
from ..i18n import count_label, failure_text, tr
from ..logger import error as _log_error
from ..stac.client import STAC_URL, _fetch_all_stac_collections, is_supported_image_collection, open_stac_client
from ..stac.fallback import FALLBACK_BAND_INFO, FALLBACK_COLLECTIONS
from ..stac.parsers import resolution_label, wavelength_label
from ..widgets.collection_badge import (
    BADGE_ROLE,
    TYPE_BADGE_ROLE,
    badge_for_collection,
    type_badge_for_collection,
)
from ..widgets.cursors import apply_click_cursors
from .ts_constants import _INDEX_DEFS
from .ui_wait import run_in_worker

BDC_STAC_URL = STAC_URL


# Asset media types that hold scene metadata (MTL, angle files, STAC sidecars), not pixel values.
_STAC_CLIENT_LOCK = threading.Lock()
_METADATA_MEDIA_TYPES = frozenset({"application/json", "application/xml", "text/plain", "text/xml", "text/html"})


_GRID_NAMES = {
    "BDC_SM": "BDC_SM_V2",
    "BDC_SM_V2": "BDC_SM_V2",
    "BDC_MD": "BDC_MD_V2",
    "BDC_MD_V2": "BDC_MD_V2",
    "BDC_LG": "BDC_LG_V2",
    "BDC_LG_V2": "BDC_LG_V2",
}


def _ts_collection_entry(coll):
    """(display name, config, band info) of a STAC collection for the time series panel, or None.

    Unsupported collections and mosaics (single composites without a
    temporal axis, not meaningful as a point time series) are left out.
    """
    if not is_supported_image_collection(coll):
        return None
    bdc_type = coll.get("bdc:type", "collection")
    if bdc_type == "mosaic":
        return None
    cid = coll.get("id", "")
    item_assets = coll.get("item_assets", {})
    is_cube = bdc_type == "cube"
    summaries = coll.get("summaries", {})
    eo_bands_list = summaries.get("eo:bands", [])
    bands = _ts_bands(coll, item_assets)
    grs = coll.get("bdc:grs", "")
    platform_data = summaries.get("platform", [])
    if isinstance(platform_data, list) and platform_data:
        platform = ", ".join(platform_data[:3])
    else:
        platform = str(platform_data) if platform_data else "-"
    config = {
        "id": cid,
        "temporal": _ts_interval(coll),
        "bands": bands,
        "grid": _GRID_NAMES.get(grs, grs or ""),
        "type": bdc_type if bdc_type else ("cube" if is_cube else "collection"),
        "resolution": _ts_resolution(eo_bands_list),
        "compositing": _ts_compositing(coll, is_cube),
        "platform": platform,
        "doc_url": "https://brazil-data-cube.github.io/products.html",
    }
    band_info = _ts_band_info_from_eo_bands(eo_bands_list, bands) if eo_bands_list else {}
    if not band_info:
        band_info = _ts_band_info_from_assets(item_assets, bands) or band_info
    return f"{coll.get('title', cid)} ({cid})", config, band_info


def _ts_interval(coll):
    intervals = coll.get("extent", {}).get("temporal", {}).get("interval", [[]])
    start_date, end_date = "2017-01-01", datetime.now().strftime("%Y-%m-%d")
    if intervals and intervals[0] and len(intervals[0]) >= 2:
        if intervals[0][0]:
            start_date = intervals[0][0][:10]
        if intervals[0][1]:
            end_date = intervals[0][1][:10]
    return start_date, end_date


def _ts_bands(coll, item_assets):
    """Data assets of the collection's items, or its eo:bands names when it lists no assets."""
    bands = []
    for asset_name, asset_info in item_assets.items():
        media_type = asset_info.get("type", "")
        if "thumbnail" in asset_name or asset_name.endswith("_xml"):
            continue
        if "png" in media_type or "jpeg" in media_type:
            continue
        if media_type.split(";")[0].strip() in _METADATA_MEDIA_TYPES:
            continue
        bands.append(asset_name)
    if bands:
        return bands
    eo_bands = coll.get("summaries", {}).get("eo:bands", []) or coll.get("properties", {}).get("eo:bands", [])
    return [b.get("name") for b in eo_bands if b.get("name")]


def _ts_resolution(eo_bands_list):
    resolutions = set()
    for band in eo_bands_list:
        res = band.get("resolution_x") or band.get("gsd")
        if res and res > 0:
            resolutions.add(int(res) if res == int(res) else res)
    if not resolutions:
        return "-"
    if len(resolutions) == 1:
        return f"{list(resolutions)[0]}m"
    return f"{min(resolutions)}-{max(resolutions)}m"


def _ts_compositing(coll, is_cube):
    if not is_cube:
        return "Individual scenes"
    temporal_comp = coll.get("bdc:temporal_composition", {})
    if not temporal_comp:
        return "-"
    step, unit = temporal_comp.get("step", ""), temporal_comp.get("unit", "")
    if not step:
        return temporal_comp.get("schema", "")
    return f"LCF {step} {({'day': 'days', 'month': 'months', 'year': 'years'}).get(unit, unit)}"


def _ts_band_info_from_eo_bands(eo_bands_list, bands):
    info = {}
    for band in eo_bands_list:
        name = band.get("name", "")
        if not name or name not in bands:
            continue
        info[name] = {
            "common_name": band.get("common_name", name),
            "wavelength": wavelength_label(band.get("center_wavelength")) or "-",
            "resolution": resolution_label(band.get("resolution_x")) or "-",
        }
    return info


def _ts_band_info_from_assets(item_assets, bands):
    """Band info from the first eo:bands entry with a common name of each data asset."""
    info = {}
    for asset_name, asset_info in item_assets.items():
        if asset_name not in bands:
            continue
        eo_list = asset_info.get("eo:bands", [])
        if not (eo_list and isinstance(eo_list, list)):
            continue
        for eo_band in eo_list:
            common_name = eo_band.get("common_name", "")
            if common_name:
                info[asset_name] = {
                    "common_name": common_name,
                    "wavelength": wavelength_label(eo_band.get("center_wavelength")) or "-",
                    "resolution": "-",
                }
                break
    return info


class TSCollectionManager:
    """Collection loading, filtering, and combo population."""

    def _get_stac_client(self):
        # Called from both the main thread and worker threads: must not touch Qt.
        # The lock makes two threads that need it at once share one client.
        with _STAC_CLIENT_LOCK:
            if not self._stac_client:
                try:
                    from ..vendored import ensure_pystac_client

                    pystac_client = ensure_pystac_client()
                    self._stac_client = open_stac_client(pystac_client, BDC_STAC_URL)
                except Exception as e:
                    _log_error(f"STAC connection failed: {e}")
            return self._stac_client

    def _load_collections_from_plugin(self):
        """Fill the panel's collections from the BDC STAC, or the bundled fallback when offline."""
        self._collections = {}
        self._band_info = {}
        self._set_status("Loading collections...", "loading", 0)
        QCoreApplication.processEvents()
        try:
            all_collections = run_in_worker(_fetch_all_stac_collections, f"{BDC_STAC_URL}collections")
            for coll in all_collections:
                entry = _ts_collection_entry(coll)
                if entry is None:
                    continue
                display_name, config, band_info = entry
                self._collections[display_name] = config
                if band_info:
                    self._band_info[config["id"]] = band_info
            if not self._collections:
                raise RuntimeError("the STAC server listed no image collection")
            self._set_status(f"{count_label(len(self._collections), 'collection', 'collections')} loaded.", "success")
        except Exception as e:
            _log_error(f"Error loading collections: {e}")
            _logger.error("Failed to load STAC collections", exc_info=True)
            self._set_status(failure_text("Loading collections", str(e)[:80]), "error", 0)
            self._load_fallback_collections()
        self._visible_ids = {config.get("id", name) for name, config in self._collections.items()}
        self._populate_collection_combo()

    def _load_fallback_collections(self):
        try:
            self._collections = dict(FALLBACK_COLLECTIONS)
            self._band_info = dict(FALLBACK_BAND_INFO)
            if self._collections:
                self._set_status(
                    f"{count_label(len(self._collections), 'collection', 'collections')} loaded (offline).", "warning"
                )
            else:
                _logger.warning("Offline fallback also produced no collections.")
                self._set_status("No collection available. Check the connection and restart the plugin.", "error", 0)
        except Exception as fallback_err:
            _logger.error("Offline fallback failed: %s", fallback_err, exc_info=True)
            self._collections = {}
            self._band_info = {}
            self._set_status("No collection available: the list bundled with the plugin could not be read.", "error", 0)

    def _populate_collection_combo(self, filter_type="all"):
        current_cid = None
        if self.ts_collection_combo.currentIndex() >= 0:
            current_cid = self.ts_collection_combo.itemData(
                self.ts_collection_combo.currentIndex(), Qt.ItemDataRole.UserRole
            )
        self.ts_collection_combo.blockSignals(True)
        self.ts_collection_combo.clear()
        for name, config in sorted(self._collections.items(), key=lambda entry: entry[0].casefold()):
            cid = config.get("id", name)
            if cid not in self._visible_ids:
                continue
            ctype = config.get("type", "collection").lower()
            if ctype == "mosaic":
                # Mosaics are single spatial composites, not periodic time
                # series — never offered in the time series panel.
                continue
            if filter_type == "cube" and ctype != "cube":
                continue
            elif filter_type == "collection" and ctype != "collection":
                continue
            self.ts_collection_combo.addItem(name)

            idx = self.ts_collection_combo.count() - 1
            self.ts_collection_combo.setItemData(idx, cid, Qt.ItemDataRole.UserRole)
            self.ts_collection_combo.setItemData(idx, name, Qt.ItemDataRole.UserRole + 1)

            if filter_type == "all":
                t_badge = type_badge_for_collection(config)
                if t_badge:
                    self.ts_collection_combo.setItemData(idx, t_badge, TYPE_BADGE_ROLE)
                f_badge = badge_for_collection(config)
                if f_badge:
                    self.ts_collection_combo.setItemData(idx, f_badge, BADGE_ROLE)

        self.ts_collection_combo.blockSignals(False)
        restored = False
        if current_cid:
            for i in range(self.ts_collection_combo.count()):
                if self.ts_collection_combo.itemData(i, Qt.ItemDataRole.UserRole) == current_cid:
                    self.ts_collection_combo.setCurrentIndex(i)
                    restored = True
                    break
        if not restored and self.ts_collection_combo.count() > 0:
            default_idx = 0
            for i in range(self.ts_collection_combo.count()):
                if self.ts_collection_combo.itemData(i, Qt.ItemDataRole.UserRole) == "S2-16D-2":
                    default_idx = i
                    break
            self.ts_collection_combo.setCurrentIndex(default_idx)
            self._on_collection_changed(default_idx)

    def _filter_ts_collections(self):
        """Filter collections by type (All/Cubes/Collections). Mosaics are excluded
        entirely — they are single spatial composites, not periodic time series."""
        if self._type_all_btn.isChecked():
            self._populate_collection_combo("all")
        elif self._type_cube_btn.isChecked():
            self._populate_collection_combo("cube")
        elif self._type_coll_btn.isChecked():
            self._populate_collection_combo("collection")

    def _show_collection_filter(self):
        from ..widgets.dialogs import CollectionFilterDialog

        dlg = CollectionFilterDialog(self._collections, self._visible_ids, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._visible_ids = dlg.get_visible_ids()
            self._filter_ts_collections()

    def _on_collection_changed(self, index):
        from qgis.PyQt.QtWidgets import QCheckBox

        for cb in self._band_checkboxes:
            self._bands_grid_layout.removeWidget(cb)
            cb.hide()
            cb.setParent(None)
            cb.deleteLater()
        self._band_checkboxes = []

        cid = self.ts_collection_combo.itemData(index, Qt.ItemDataRole.UserRole)
        if not cid:
            return
        config = None
        for name, cfg in self._collections.items():
            if cfg.get("id") == cid:
                config = cfg
                break
        if not config:
            return

        info_parts = []
        if config.get("platform"):
            info_parts.append(config["platform"])
        if config.get("resolution"):
            info_parts.append(config["resolution"])
        if config.get("compositing"):
            info_parts.append(config["compositing"])
        temporal = config.get("temporal")
        if temporal and len(temporal) == 2:
            info_parts.append(f"{temporal[0]}-{temporal[1]}")
            start = QDate.fromString(temporal[0], "yyyy-MM-dd")
            end = QDate.fromString(temporal[1], "yyyy-MM-dd")
            if start.isValid() and end.isValid() and start < end:
                self.range_slider.set_date_range(start, end)
        self.ts_collection_info.setText(tr(" | ".join(info_parts)))

        bands = sorted(config.get("bands", []), key=lambda value: str(value).casefold())
        band_info = self._band_info.get(cid, {})
        n_cols = 3 if len(bands) > 6 else 2
        for i, band in enumerate(bands):
            binfo = band_info.get(band, {})
            common = binfo.get("common_name", "")
            label = f"{band} ({common})" if common else band
            cb = QCheckBox(label)
            cb.setChecked(True)
            cb.setProperty("band_name", band)
            cb.setStyleSheet("QCheckBox { font-size: 9px; }")
            self._band_checkboxes.append(cb)
            row = i // n_cols
            col = i % n_cols
            self._bands_grid_layout.addWidget(cb, row, col)

        ctype = config.get("type", "collection").lower()
        if ctype != "cube":
            available_indices = sorted(
                self._get_available_indices(cid, bands),
                key=lambda value: _INDEX_DEFS[value]["label"].casefold(),
            )
            if available_indices:
                n_real = len(self._band_checkboxes)
                sep_row = n_real // n_cols + (1 if n_real % n_cols else 0)
                for j, idx_key in enumerate(available_indices):
                    idx_def = _INDEX_DEFS[idx_key]
                    cb = QCheckBox(idx_def["label"])
                    cb.setChecked(False)
                    cb.setProperty("band_name", idx_key)
                    cb.setStyleSheet("QCheckBox { font-size: 9px; color: #27ae60; font-weight: bold; }")
                    self._band_checkboxes.append(cb)
                    self._bands_grid_layout.addWidget(cb, sep_row + j // n_cols, j % n_cols)
        for cb in self._band_checkboxes:
            apply_click_cursors(cb)
