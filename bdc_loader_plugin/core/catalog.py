# -*- coding: utf-8 -*-
"""
STAC catalog, collection, and band management mixin for BDCLoaderDialog.

Provides:
- `CatalogManager` — mixin inherited by BDCLoaderDialog that handles:
  - Populating and filtering the collection combo by type (cube/scenes/all)
  - Per-collection band listing and dynamic RGB preset generation
  - STAC connectivity check and online status indicator
  - Fetching live temporal extents, bands, and eo:bands metadata from STAC API
  - Dynamic collection discovery (replaces fallback data when STAC is reachable)
  - Band add/remove and preset application for VRT building

Dependencies:
  stac.client   — STAC endpoint URLs and grid lookup tables
  stac.fallback — offline collection defaults
  stac.parsers  — display name, platform, band extraction helpers
  ui.result_widgets — thread-safe UI invocation
"""

import threading

from qgis.PyQt.QtCore import QDate, Qt, QTimer
from qgis.PyQt.QtGui import QBrush, QColor
from qgis.PyQt.QtWidgets import QDialog, QListWidgetItem, QMessageBox

from ..config import ConfigManager
from ..i18n import tr
from ..net import PING_S
from ..stac.client import (
    BDC_DOC_URL,
    GRS_TO_GRID,
    STAC_URL,
    collection_is_cloud_optimized,
    fetch_collection_asset_names,
    is_supported_image_collection,
)
from ..stac.fallback import FALLBACK_COLLECTIONS, FALLBACK_UPDATED
from ..stac.parsers import (
    build_display_name,
    extract_bands_from_assets,
    extract_resolution,
    format_compositing,
    format_platform,
    has_valid_tile_system,
    resolution_label,
    wavelength_label,
)
from ..timing import COLLECTION_PERIODS_MS
from ..ui.thumbnails import _invoke_on_ui_thread
from ..widgets.collection_badge import (
    BADGE_ROLE,
    COG_BADGE,
    GEOTIFF_BADGE,
    GRID_BADGE_ROLE,
    TYPE_BADGE_ROLE,
    badge_for_collection,
    grid_badge_for_collection,
    type_badge_for_collection,
)
from ..widgets.dialogs import CollectionFilterDialog, CompositionDialog
from .band_selection import available_bands_for_items, resolve_band, unavailable_band_reasons
from .catalog_data import BAND_INFO, COLLECTIONS, RGB_PRESETS

_BAND_UNAVAILABLE_TOOLTIP = "Not available."


# Item data role marking a preset entry saved by the user.
_CUSTOM_PRESET_ROLE = Qt.ItemDataRole.UserRole + 1


def _warn_stale_fallback():
    """Log a warning when the bundled fallback catalogue is more than 180 days old."""
    try:
        from datetime import date as _date

        age = (_date.today() - _date.fromisoformat(FALLBACK_UPDATED)).days
        if age > 180:
            from ..logger import warning as _warn

            _warn(
                f"Fallback collection data is {age} days old (last updated {FALLBACK_UPDATED}). "
                "Consider refreshing the bundled fallback."
            )
    except (TypeError, ValueError):
        pass


def _collection_entry(coll, fallback):
    """(display name, config, STAC interval or None, eo:bands) of a STAC collection.

    Fields the STAC answer lacks come from the bundled ``fallback`` entry.
    """
    coll_id = coll.get("id", "")
    stac_type = coll.get("bdc:type", "collection")
    stac_grs = coll.get("bdc:grs")
    platform_data = coll.get("summaries", {}).get("platform", coll.get("platform", None))

    interval = None
    temporal = coll.get("extent", {}).get("temporal", {}).get("interval", [[]])
    if temporal and temporal[0] and len(temporal[0]) >= 2 and temporal[0][0] and temporal[0][1]:
        interval = (temporal[0][0][:10], temporal[0][1][:10])
    start_date, end_date = interval or fallback.get("temporal", ("2017-01-01", "2026-01-01"))

    eo_bands = coll.get("properties", {}).get("eo:bands", []) or coll.get("summaries", {}).get("eo:bands", [])
    stac_bands = extract_bands_from_assets(coll.get("item_assets", {}))
    if not stac_bands and eo_bands:
        stac_bands = [b.get("name") for b in eo_bands if b.get("name")]
    temporal_comp = coll.get("bdc:temporal_composition", {})
    config = {
        "id": coll_id,
        "temporal": (start_date, end_date),
        "bands": stac_bands or fallback.get("bands", []),
        "grid": GRS_TO_GRID.get(stac_grs, stac_grs or ""),
        "type": stac_type,
        "resolution": extract_resolution(eo_bands) or fallback.get("resolution", "-"),
        "compositing": (
            format_compositing(temporal_comp, stac_type)
            if temporal_comp or stac_type
            else fallback.get("compositing", "-")
        ),
        "platform": format_platform(platform_data) if platform_data else fallback.get("platform", "-"),
        "doc_url": BDC_DOC_URL,
        "has_tiles": has_valid_tile_system(stac_grs),
        # Read off the raw STAC collection, which carries item_assets; the
        # combo badge and the pre-build warning both key off this.
        "cloud_optimized": collection_is_cloud_optimized(coll),
    }
    return build_display_name(coll_id, coll.get("title", ""), stac_type), config, interval, eo_bands


def _merge_eo_band_info(band_info, eo_bands, bands):
    """Update ``band_info`` ({band: info}) with the common name, wavelength and resolution in ``eo_bands``."""
    bands_set = set(bands) if bands else set()
    for band_data in eo_bands:
        band_name = band_data.get("name", "")
        if not band_name or (bands_set and band_name not in bands_set):
            continue
        info = band_info.setdefault(band_name, {"common_name": band_name, "wavelength": "-", "resolution": "-"})
        if band_data.get("common_name", ""):
            info["common_name"] = band_data["common_name"]
        wavelength = wavelength_label(band_data.get("center_wavelength"))
        if wavelength:
            info["wavelength"] = wavelength
        resolution = resolution_label(band_data.get("resolution_x"))
        if resolution:
            info["resolution"] = resolution


# RGB composites as (label, band roles). Based on
# https://custom-scripts.sentinel-hub.com/custom-scripts/sentinel-2/composites/
# with equivalents for Landsat, CBERS, AMAZONIA and MODIS; the label shows the
# Sentinel-2 bands of each role.
_PRESET_RECIPES = (
    ("True Color (B04,B03,B02)", ("red", "green", "blue")),
    ("False Color (B08,B04,B03)", ("nir", "red", "green")),
    ("SWIR (B12,B08,B04)", ("swir22", "nir", "red")),
    ("Agriculture (B11,B08,B02)", ("swir16", "nir", "blue")),
    ("Geology (B12,B11,B02)", ("swir22", "swir16", "blue")),
    ("Bathimetric (B04,B03,B01)", ("red", "green", "coastal")),
    ("Vegetation Analysis (B08,B06,B04)", ("nir", "rededge2", "red")),
    ("Healthy Vegetation (B08,B05,B04)", ("nir", "rededge1", "red")),
    ("Vegetation/Built-up (B08,B11,B04)", ("nir", "swir16", "red")),
    ("Urban/Moisture (B08,B11,B12)", ("nir", "swir16", "swir22")),
    ("Land/Water (B11,B08,B03)", ("swir16", "nir", "green")),
    ("NDVI+NIR+Red", ("ndvi", "nir", "red")),
    ("EVI+NIR+Red", ("evi", "nir", "red")),
    ("NDVI+EVI+NIR", ("ndvi", "evi", "nir")),
)

# Common names each role accepts, in order of preference; sensors name NIR and SWIR differently.
_ROLE_COMMON_NAMES = {
    "blue": ("blue",),
    "green": ("green",),
    "red": ("red",),
    "nir": ("nir", "nir08"),
    "swir16": ("swir16", "swir1"),
    "swir22": ("swir22", "swir2"),
    "coastal": ("coastal",),
    "evi": ("evi",),
    "ndvi": ("ndvi",),
}


def _band_roles(bands, band_info):
    """Band filling each composite role, found by the bands' common names.

    The first band with a common name takes it. The first and second red-edge
    bands (B05 and B06 on Sentinel-2) are the roles rededge1 and rededge2.
    """
    by_common = {}
    rededge = []
    for band in bands:
        common = band_info.get(band, {}).get("common_name", "").lower()
        if common:
            by_common.setdefault(common, band)
        if common == "rededge":
            rededge.append(band)
    roles = {
        role: next((by_common[name] for name in names if name in by_common), None)
        for role, names in _ROLE_COMMON_NAMES.items()
    }
    roles["rededge1"] = rededge[0] if rededge else None
    roles["rededge2"] = rededge[1] if len(rededge) > 1 else None
    return roles


def dynamic_presets(bands, band_info):
    """{label: [r, g, b]} for every composite whose roles the bands all fill."""
    roles = _band_roles(bands, band_info)
    return {
        label: [roles[role] for role in recipe]
        for label, recipe in _PRESET_RECIPES
        if all(roles[role] for role in recipe)
    }


class CatalogManager:
    """Provides STAC status, collection management, and band selection."""

    def _populate_collections(self, filter_type="all"):
        """Populate the collection combo based on the selected type filter."""
        self.collection_combo.clear()

        for coll_name, config in sorted(COLLECTIONS.items(), key=lambda entry: entry[0].casefold()):
            coll_type = config.get("type", "collection").lower()
            coll_id = config.get("id", coll_name)

            # Skip collections hidden by the individual filter
            if hasattr(self, "_hidden_collections") and coll_id in self._hidden_collections:
                continue

            # Apply type filter
            if filter_type == "cube" and coll_type != "cube":
                continue
            elif filter_type == "collection" and coll_type != "collection":
                continue
            elif filter_type == "mosaic" and coll_type != "mosaic":
                continue

            # Add item with clean collection name (badges painted by delegate)
            self.collection_combo.addItem(coll_name)

            # Store the original name in UserRole for internal use
            idx = self.collection_combo.count() - 1
            self.collection_combo.setItemData(idx, coll_name, Qt.ItemDataRole.UserRole)

            # Raster format badge, category badge, and grid badge painted by CollectionBadgeDelegate.
            badge = badge_for_collection(config)
            if badge:
                self.collection_combo.setItemData(idx, badge, BADGE_ROLE)

            if filter_type == "all":
                t_badge = type_badge_for_collection(config)
                if t_badge:
                    self.collection_combo.setItemData(idx, t_badge, TYPE_BADGE_ROLE)

            g_badge = grid_badge_for_collection(config)
            if g_badge:
                self.collection_combo.setItemData(idx, g_badge, GRID_BADGE_ROLE)

    def _filter_collections(self):
        """Filter collections based on the selected radio button."""
        current_selection = None
        if self.collection_combo.currentIndex() >= 0:
            current_selection = self.collection_combo.itemData(
                self.collection_combo.currentIndex(), Qt.ItemDataRole.UserRole
            )

        if self.filter_all_btn.isChecked():
            self._populate_collections("all")
        elif self.filter_cube_btn.isChecked():
            self._populate_collections("cube")
        elif self.filter_collection_btn.isChecked():
            self._populate_collections("collection")
        elif self.filter_mosaic_btn.isChecked():
            self._populate_collections("mosaic")

        # Try to restore the previous selection if still in the list
        if current_selection:
            for i in range(self.collection_combo.count()):
                if self.collection_combo.itemData(i, Qt.ItemDataRole.UserRole) == current_selection:
                    self.collection_combo.setCurrentIndex(i)
                    return

        # If not found, select the first item
        if self.collection_combo.count() > 0:
            self.collection_combo.setCurrentIndex(0)

    def _show_collection_filter_dialog(self):
        """Open a dialog to show/hide individual collections."""
        # Build the set of visible IDs (all except hidden ones)
        visible_ids = set()
        for name, config in COLLECTIONS.items():
            cid = config.get("id", name)
            if cid not in self._hidden_collections:
                visible_ids.add(cid)

        dlg = CollectionFilterDialog(COLLECTIONS, visible_ids, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_visible = dlg.get_visible_ids()
            # Compute hidden collections
            all_ids = set()
            for name, config in COLLECTIONS.items():
                all_ids.add(config.get("id", name))
            self._hidden_collections = all_ids - new_visible
            # Re-populate combo applying filters
            self._filter_collections()

    def on_collection_changed(self, display_name: str):
        # Extract the real collection name from UserRole
        idx = self.collection_combo.currentIndex()
        name = self.collection_combo.itemData(idx, Qt.ItemDataRole.UserRole)
        if not name:
            # Fallback to display name if UserRole is absent
            name = display_name.replace("[CUBE] ", "").replace("[COLLECTION] ", "")

        config = COLLECTIONS.get(name, {})
        # Results belong to the collection they were searched in; Load layers
        # and Download read the collection from this combo.
        if self.result_widgets:
            self.clear_results()
        collection_id = config.get("id", "")

        # Use STAC temporal cache if available, otherwise use the default
        if collection_id in self._stac_temporal_cache:
            temporal = self._stac_temporal_cache[collection_id]
        else:
            temporal = config.get("temporal", ("2017-01-01", "2026-01-01"))

        start = QDate.fromString(temporal[0], "yyyy-MM-dd")
        end = QDate.fromString(temporal[1], "yyyy-MM-dd")

        self.range_slider.set_date_range(start, end)

        # Update collection info display
        col_type = config.get("type", "collection")
        resolution = config.get("resolution", "-")
        compositing = config.get("compositing", "-")
        platform = config.get("platform", "-")
        tipo_label = "Cube" if col_type == "cube" else "Scenes"
        has_tiles = config.get("has_tiles", True)
        tiles_msg = ""
        if not has_tiles:
            tiles_msg = " | <span style='color:#e67e22;'>No tiles (use Extent only)</span>"
        # The combo badge is only visible while the list is open, so the format
        # is repeated here, where it stays put for the selected collection.
        format_msg = ""
        badge = badge_for_collection(config)
        if badge == GEOTIFF_BADGE:
            format_msg = " | <span style='color:#b9770e;'>GeoTIFF (not cloud-optimized) — prefer Download</span>"
        elif badge == COG_BADGE:
            format_msg = " | <span style='color:#1e8449;'>COG</span>"
        self.collection_info_label.setText(
            tr(
                f"Type: {tipo_label} | Resolution: {resolution} | "
                f"Compositing: {compositing} | Platform: {platform}{tiles_msg}{format_msg}"
            )
        )

        if not has_tiles:
            if hasattr(self, "tiles_input"):
                self.tiles_input.setPlaceholderText(tr("No tile grid available"))
            self._set_tiles_mode(False)
        else:
            if hasattr(self, "tiles_input"):
                self.tiles_input.setPlaceholderText("031023, 031024, ...")
            # The area-filter locks keep Tiles greyed out while another filter is in use.
            self._set_tiles_mode(True)

        # Clear selected tiles if grid type changed
        new_grid = config.get("grid", "BDC_SM_V2")
        prev_grid = getattr(self, "_current_grid_name", None)
        if prev_grid and prev_grid != new_grid:
            self.clear_tiles()
        self._current_grid_name = new_grid

        self.available_bands.clear()
        self.selected_bands.clear()
        bands = config.get("bands", [])
        unavailable_reasons = self._collection_band_reasons(collection_id, bands)
        available_bands = [band for band in bands if band not in unavailable_reasons]
        self._update_band_list(name, bands, unavailable_reasons)
        self._update_preset_list(name, available_bands, collection_changed=True)
        self._request_collection_band_availability(name, collection_id, bands)

        self.update_bands_status()
        self.update_grid_status()

    def update_bands_status(self):
        """Update VRT preview after a band change."""
        self._update_vrt_preview()

    def _update_band_list(self, collection_name: str, bands=None, unavailable_reasons=None):
        """Update the available bands list for the given collection."""
        config = COLLECTIONS.get(collection_name, {})
        if bands is None:
            bands = config.get("bands", [])
        unavailable_reasons = unavailable_reasons or {}
        collection_id = config.get("id", "")
        band_info = BAND_INFO.get(collection_id, {})

        self.available_bands.setUpdatesEnabled(False)
        self.available_bands.clear()
        for band in sorted(bands, key=lambda value: str(value).casefold()):
            common = band_info.get(band, {}).get("common_name")
            if common and common != band:
                label = f"{band} ({common})"
            else:
                label = band
            item = QListWidgetItem(tr(label))
            item.setData(Qt.ItemDataRole.UserRole, band)
            reason = unavailable_reasons.get(band)
            if reason:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled & ~Qt.ItemFlag.ItemIsSelectable)
                item.setForeground(QBrush(QColor("#9e9e9e")))
                item.setToolTip(reason)
            self.available_bands.addItem(item)
        self.available_bands.setUpdatesEnabled(True)

    def _collection_band_reasons(self, collection_id: str, bands: list) -> dict:
        """Return cached collection-wide availability without network work.

        Only a band the scan proved absent is disabled. While the check runs,
        or when it stopped before seeing every item, bands stay usable: the
        search result items are checked again before anything is loaded.
        """
        asset_cache = self._collection_asset_cache
        names = asset_cache.get(collection_id)
        if names is None or not getattr(names, "complete", True):
            return {}

        assets = dict.fromkeys(names)
        return {band: _BAND_UNAVAILABLE_TOOLTIP for band in bands if resolve_band(band, assets) is None}

    def _request_collection_band_availability(self, collection_name: str, collection_id: str, bands: list):
        """Check collection assets once in the background and cache the result."""
        if not collection_id or not bands:
            return
        asset_cache = self._collection_asset_cache
        checks = self._collection_asset_checks
        if collection_id in asset_cache or collection_id in checks:
            return
        checks.add(collection_id)

        def _fetch():
            try:
                assets = fetch_collection_asset_names(collection_id, bands)
            except Exception:
                # Availability is unknown when offline; keep advertised bands usable.
                assets = set(bands)

            def _apply():
                checks.discard(collection_id)
                asset_cache[collection_id] = assets
                try:
                    idx = self.collection_combo.currentIndex()
                    current_name = self.collection_combo.itemData(idx, Qt.ItemDataRole.UserRole)
                except RuntimeError:
                    return
                if current_name != collection_name:
                    return
                reasons = self._collection_band_reasons(collection_id, bands)
                available = [band for band in bands if band not in reasons]
                self._update_band_list(collection_name, bands, reasons)
                self._update_preset_list(collection_name, available)

            _invoke_on_ui_thread(_apply)

        threading.Thread(target=_fetch, daemon=True).start()

    def _current_collection_name(self):
        idx = self.collection_combo.currentIndex()
        name = self.collection_combo.itemData(idx, Qt.ItemDataRole.UserRole)
        if not name:
            name = self.collection_combo.currentText().replace("[CUBE] ", "").replace("[COLLECTION] ", "")
        return name

    def _collection_presets(self, collection_name: str, bands: list):
        """Return (built_in, custom) presets as {name: [bands]} for the collection.

        ``bands`` limits both to compositions whose bands are all available.
        """
        collection_id = COLLECTIONS.get(collection_name, {}).get("id", "")
        available = set(bands)
        built_in = RGB_PRESETS.get(collection_name, {})
        if built_in:
            built_in = {name: values for name, values in built_in.items() if set(values).issubset(available)}
        else:
            built_in = self._get_dynamic_presets(collection_id, bands)
        custom = {
            name: values
            for name, values in ConfigManager.get_custom_compositions(collection_id).items()
            if set(values).issubset(available) and name not in built_in
        }
        return built_in, custom

    def _update_preset_list(self, collection_name: str, bands: list, collection_changed=False):
        """Show only presets supported by the currently available bands.

        With ``collection_changed`` a preset kept from the previous collection
        is applied to the new one, whose selected bands were just cleared.
        """
        built_in, custom = self._collection_presets(collection_name, bands)
        previous = self.preset_combo.currentText()

        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItem(tr("-- Select --"))
        entries = [(name, values, False) for name, values in built_in.items()]
        entries += [(name, values, True) for name, values in custom.items()]
        for name, values, is_custom in sorted(entries, key=lambda e: str(e[0]).casefold()):
            self.preset_combo.addItem(name)
            row = self.preset_combo.count() - 1
            self.preset_combo.setItemData(row, list(values), Qt.ItemDataRole.UserRole)
            self.preset_combo.setItemData(row, is_custom, _CUSTOM_PRESET_ROLE)
            kind = "Your composition" if is_custom else "Composition"
            self.preset_combo.setItemData(row, f"{kind}: {', '.join(values)}", Qt.ItemDataRole.ToolTipRole)
        restored = self.preset_combo.findText(previous) if previous else -1
        self.preset_combo.setCurrentIndex(restored if restored > 0 else 0)
        self.preset_combo.blockSignals(False)
        self._update_composition_buttons()
        if collection_changed and restored > 0 and self.selected_bands.count() == 0:
            self.apply_preset(self.preset_combo.currentText())

    def _update_composition_buttons(self, *_args):
        """Enable delete only for a composition saved by the user."""
        btn = getattr(self, "delete_composition_btn", None)
        if btn is None:
            return
        idx = self.preset_combo.currentIndex()
        btn.setEnabled(idx > 0 and bool(self.preset_combo.itemData(idx, _CUSTOM_PRESET_ROLE)))

    def _selected_band_names(self):
        names = []
        for row in range(self.selected_bands.count()):
            item = self.selected_bands.item(row)
            names.append(item.data(Qt.ItemDataRole.UserRole) or item.text())
        return names

    def _enabled_bands(self):
        """(band id, label) pairs of the bands the current selection offers."""
        pairs = []
        for row in range(self.available_bands.count()):
            item = self.available_bands.item(row)
            if item.flags() & Qt.ItemFlag.ItemIsEnabled:
                pairs.append((item.data(Qt.ItemDataRole.UserRole) or item.text(), item.text()))
        return pairs

    def _save_composition(self):
        """Ask for the bands and name of a new composition and save it for the current collection."""
        collection_name = self._current_collection_name()
        collection_id = COLLECTIONS.get(collection_name, {}).get("id", "")
        bands = self._enabled_bands()
        if not collection_id or not bands:
            QMessageBox.information(self, "New composition", "Select a collection with available bands first.")
            return

        built_in, _ = self._collection_presets(collection_name, COLLECTIONS.get(collection_name, {}).get("bands", []))
        dialog = CompositionDialog(
            bands,
            built_in,
            ConfigManager.get_custom_compositions(collection_id),
            initial=self._selected_band_names(),
            collection_label=collection_id,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name = dialog.name()
        replaced = dialog.replaced_name()
        if replaced and replaced != name:
            ConfigManager.delete_custom_composition(collection_id, replaced)
        ConfigManager.save_custom_composition(collection_id, name, dialog.bands())

        self._sync_bands_with_selected_items()
        idx = self.preset_combo.findText(name)
        if idx > 0:
            self.preset_combo.blockSignals(True)
            self.preset_combo.setCurrentIndex(idx)
            self.preset_combo.blockSignals(False)
            self.apply_preset(name)
        self._set_status(f'Composition "{name}" saved.', "success")

    def _delete_composition(self):
        """Delete the selected user composition after confirmation."""
        idx = self.preset_combo.currentIndex()
        if idx <= 0 or not self.preset_combo.itemData(idx, _CUSTOM_PRESET_ROLE):
            return
        collection_id = COLLECTIONS.get(self._current_collection_name(), {}).get("id", "")
        name = self.preset_combo.itemText(idx)
        reply = QMessageBox.question(
            self,
            "Delete composition",
            f'Delete your composition "{name}"?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        ConfigManager.delete_custom_composition(collection_id, name)
        self.preset_combo.setCurrentIndex(0)
        self._sync_bands_with_selected_items()
        self._set_status(f'Composition "{name}" deleted.', "info")

    def _schedule_band_availability_update(self, *_args):
        """Debounce band updates triggered by result checkbox changes."""
        if not hasattr(self, "_band_availability_timer"):
            self._band_availability_timer = QTimer(self)
            self._band_availability_timer.setSingleShot(True)
            self._band_availability_timer.timeout.connect(self._sync_bands_with_selected_items)
        self._band_availability_timer.start(0)

    def _sync_bands_with_selected_items(self):
        """Disable collection bands not provided by the current result scope."""
        timer = getattr(self, "_band_availability_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()

        collection_name = self._current_collection_name()

        config = COLLECTIONS.get(collection_name, {})
        collection_bands = config.get("bands", [])
        selected_items = self.get_selected_items()
        availability_items = selected_items
        if not availability_items:
            availability_items = [widget.item for widget in self.result_widgets if widget.isVisible()]
        if availability_items:
            bands = available_bands_for_items(collection_bands, availability_items)
            unavailable_reasons = unavailable_band_reasons(collection_bands, availability_items)
        else:
            unavailable_reasons = self._collection_band_reasons(
                config.get("id", ""),
                collection_bands,
            )
            bands = [band for band in collection_bands if band not in unavailable_reasons]

        selected = []
        for row in range(self.selected_bands.count()):
            item = self.selected_bands.item(row)
            selected.append(item.data(Qt.ItemDataRole.UserRole) if item.data(Qt.ItemDataRole.UserRole) else item.text())
        # A band this method drops is the plugin's choice, not the user's: results
        # that matched the panel keep matching it.
        adopt = self._results_fresh and self._searched_params is not None

        self._update_band_list(collection_name, collection_bands, unavailable_reasons)
        self.selected_bands.clear()
        band_info = BAND_INFO.get(config.get("id", ""), {})
        for band in selected:
            if band not in bands:
                continue
            common = band_info.get(band, {}).get("common_name")
            label = f"{band} ({common})" if common and common != band else band
            item = QListWidgetItem(tr(label))
            item.setData(Qt.ItemDataRole.UserRole, band)
            self.selected_bands.addItem(item)

        self._update_preset_list(collection_name, bands)
        self.update_bands_status()
        if adopt:
            self._searched_params["bands"] = tuple(self._selected_band_names())

    def _get_dynamic_presets(self, collection_id: str, bands: list) -> dict:
        """RGB presets the collection's bands can form, cached per collection and band set."""
        if not bands:
            return {}
        cache_key = (collection_id, tuple(sorted(bands)))
        if not hasattr(self, "_preset_cache"):
            self._preset_cache = {}
        if cache_key not in self._preset_cache:
            self._preset_cache[cache_key] = dynamic_presets(bands, BAND_INFO.get(collection_id, {}))
        return self._preset_cache[cache_key]

    def _check_stac_status(self):
        """Check STAC connection using requests in a thread (non-blocking UI)."""
        import time

        import requests as _req

        def _check():
            try:
                t0 = time.perf_counter()
                r = _req.get(STAC_URL, timeout=PING_S)
                ms = int((time.perf_counter() - t0) * 1000)
                return r.status_code < 400, ms
            except Exception as _e:
                from ..logger import warning as _w

                _w(f"STAC health check failed: {_e}")
                return False, 0

        def _done(online, ms):
            try:
                from qgis.PyQt import sip

                if sip.isdeleted(self):
                    return
                self._stac_response_time_ms = ms
                self._set_stac_status(online)
                if online:
                    QTimer.singleShot(COLLECTION_PERIODS_MS, self._fetch_collection_temporals)
            except (RuntimeError, ReferenceError) as exc:
                from ..logger import warning as _w

                _w(f"STAC status callback failed: {exc}")

        def _run():
            online, ms = _check()
            _invoke_on_ui_thread(lambda o=online, m=ms: _done(o, m))

        # Guard against overlapping ping threads (e.g. if a check hangs > 60s)
        if getattr(self, "_stac_ping_running", False):
            return
        self._stac_ping_running = True

        def _guarded():
            try:
                _run()
            finally:
                self._stac_ping_running = False

        threading.Thread(target=_guarded, daemon=True).start()

    def _set_stac_status(self, online: bool):
        """Update the visual STAC status indicator with details.

        When going offline for the first time, starts a background ping timer
        (every 60 s) and says in the status line that search uses the downloaded
        images. When recovering, stops the timer and notifies the user.
        """
        was_offline = self._stac_online is False
        self._stac_online = online
        rt = self._stac_response_time_ms
        if online:
            # Stop the periodic ping timer if running
            if hasattr(self, "_stac_ping_timer") and self._stac_ping_timer.isActive():
                self._stac_ping_timer.stop()

            if rt > 3000:
                dot_color = "#f39c12"
                text_color = "#f39c12"
                status_text = f"STAC: Slow ({rt}ms)"
                tooltip_text = (
                    f"STAC BDC responded in {rt}ms (slow).\nServer may be overloaded.\nClick to open: {STAC_URL}"
                )
            else:
                dot_color = "#27ae60"
                text_color = "#27ae60"
                status_text = f"STAC: Online ({rt}ms)"
                tooltip_text = f"STAC BDC online. Response in {rt}ms.\nClick to open: {STAC_URL}"
            self.stac_status_dot.setStyleSheet(f"background-color: {dot_color}; border-radius: 5px;")
            self.stac_status_label.setText(
                tr(f"<span style='color: {text_color}; font-size: 9px;'>{status_text}</span>")
            )
            self.set_tooltip(self.stac_status_container, tr(tooltip_text))
            self.set_tooltip(self.stac_status_dot, tooltip_text)
            self.set_tooltip(self.stac_status_label, tooltip_text)

            # Notify recovery if previously offline
            if was_offline:
                self._notify_stac_recovered(rt)
        else:
            self.stac_status_dot.setStyleSheet("background-color: #e74c3c; border-radius: 5px;")
            self.stac_status_label.setText(
                tr("<span style='color: #e74c3c; font-size: 9px;'>Offline: local data</span>")
            )
            tooltip_text = (
                "The BDC cannot be reached.\n"
                "Search lists the images downloaded on this computer, and they load from disk.\n"
                "Collections come from the list bundled with the plugin and may be outdated.\n"
                f"The connection is checked every minute. Click to check now: {STAC_URL}"
            )
            self.set_tooltip(self.stac_status_container, tr(tooltip_text))
            self.set_tooltip(self.stac_status_dot, tooltip_text)
            self.set_tooltip(self.stac_status_label, tooltip_text)

            # Start periodic background ping (every 60 s) to detect recovery
            self._start_stac_ping_timer()
            if not was_offline:
                self._set_status(
                    "<b>Offline:</b> the BDC cannot be reached. Search lists the images downloaded on "
                    "this computer; online search resumes when the connection returns.",
                    "warning",
                )

    # ------------------------------------------------------------------
    # Periodic ping & recovery
    # ------------------------------------------------------------------
    def _start_stac_ping_timer(self):
        """Start a repeating timer that checks STAC connectivity in background."""
        if not hasattr(self, "_stac_ping_timer"):
            self._stac_ping_timer = QTimer(self)
            self._stac_ping_timer.timeout.connect(self._check_stac_status)
        if not self._stac_ping_timer.isActive():
            self._stac_ping_timer.start(60_000)  # 60 seconds

    def _notify_stac_recovered(self, ms):
        """Show a non-intrusive QGIS message bar notification on recovery."""
        try:
            from qgis.core import Qgis

            self.iface.messageBar().pushMessage(
                "BDC Loader",
                tr(f"The BDC is back online ({ms} ms). Collections updated."),
                level=Qgis.MessageLevel.Success,
                duration=8,
            )
        except Exception:
            pass

    def _show_stac_offline_dialog(self):
        """Show the STAC offline dialog with auto-ping and test link."""
        from ..ui.stac_offline_dialog import StacOfflineDialog

        def _on_recovered(ms):
            self._stac_response_time_ms = ms
            self._set_stac_status(True)
            QTimer.singleShot(COLLECTION_PERIODS_MS, self._fetch_collection_temporals)

        dlg = StacOfflineDialog(parent=self, on_recovered=_on_recovered)
        dlg.exec()

    def _fetch_collection_temporals(self):
        """Fetch updated temporal extents from STAC API (background thread)."""

        def _fetch():
            try:
                from ..stac.client import _fetch_all_stac_collections

                all_cols = _fetch_all_stac_collections(STAC_URL + "collections")
                data = {"collections": all_cols}
                _invoke_on_ui_thread(lambda d=data: self._process_collections_data(d))
            except Exception as exc:
                from ..logger import warning

                warning(f"STAC collections refresh failed: {exc}")

        threading.Thread(target=_fetch, daemon=True).start()

    def _process_collections_data(self, collections_data):
        """Replace the collection catalogue with the STAC answer and refresh the dialog."""
        try:
            image_collections = [c for c in collections_data.get("collections", []) if is_supported_image_collection(c)]
            if not image_collections:
                return
            _warn_stale_fallback()
            fallback_by_id = {v["id"]: v for v in FALLBACK_COLLECTIONS.values()}
            new_collections = {}
            for coll in image_collections:
                coll_id = coll.get("id", "")
                display_name, config, stac_interval, eo_bands = _collection_entry(coll, fallback_by_id.get(coll_id, {}))
                if stac_interval:
                    self._stac_temporal_cache[coll_id] = stac_interval
                new_collections[display_name] = config
                if eo_bands:
                    _merge_eo_band_info(BAND_INFO.setdefault(coll_id, {}), eo_bands, config["bands"])
            COLLECTIONS.clear()
            COLLECTIONS.update(new_collections)
            self._refresh_collection_combo()
            self._apply_current_collection_period()
            self._show_stac_online(len(COLLECTIONS))
        except Exception as _e:
            from ..logger import warning as _warn

            _warn(f"_process_collections_data error: {_e}")

    def _refresh_collection_combo(self):
        """Repopulate the combo under the active type filter, keeping the selected collection."""
        current_selection = None
        if self.collection_combo.currentIndex() >= 0:
            current_selection = self.collection_combo.itemData(
                self.collection_combo.currentIndex(), Qt.ItemDataRole.UserRole
            )
        for button, filter_type in (
            (self.filter_all_btn, "all"),
            (self.filter_cube_btn, "cube"),
            (self.filter_collection_btn, "collection"),
            (self.filter_mosaic_btn, "mosaic"),
        ):
            if button.isChecked():
                self._populate_collections(filter_type)
                break
        else:
            self._populate_collections("all")
        if current_selection:
            for i in range(self.collection_combo.count()):
                if self.collection_combo.itemData(i, Qt.ItemDataRole.UserRole) == current_selection:
                    self.collection_combo.setCurrentIndex(i)
                    break

    def _apply_current_collection_period(self):
        """Set the period slider to the STAC extent of the selected collection, when known."""
        coll_id = COLLECTIONS.get(self._current_collection_name(), {}).get("id", "")
        if coll_id not in self._stac_temporal_cache:
            return
        start_text, end_text = self._stac_temporal_cache[coll_id]
        start = QDate.fromString(start_text, "yyyy-MM-dd")
        end = QDate.fromString(end_text, "yyyy-MM-dd")
        if start.isValid() and end.isValid():
            self.range_slider.set_date_range(start, end)

    def _show_stac_online(self, count):
        self.stac_status_label.setText(
            tr(f"<span style='color: #27ae60; font-size: 9px;'>STAC: Online ({count} collections)</span>")
        )
        self.stac_status_dot.setStyleSheet("background-color: #27ae60; border-radius: 5px;")
        tooltip_text = f"STAC BDC online. {count} collections loaded dynamically."
        for widget in (self.stac_status_container, self.stac_status_dot, self.stac_status_label):
            self.set_tooltip(widget, tooltip_text)

    def add_band(self):
        if self.selected_bands.count() >= 3:
            return

        for item in self.available_bands.selectedItems():
            band_real = item.data(Qt.ItemDataRole.UserRole) if item.data(Qt.ItemDataRole.UserRole) else item.text()
            band_label = item.text()
            # Check if the band is already selected
            already = False
            for i in range(self.selected_bands.count()):
                existing = self.selected_bands.item(i)
                existing_real = (
                    existing.data(Qt.ItemDataRole.UserRole)
                    if existing.data(Qt.ItemDataRole.UserRole)
                    else existing.text()
                )
                if existing_real == band_real:
                    already = True
                    break
            if not already:
                new_item = QListWidgetItem(band_label)
                new_item.setData(Qt.ItemDataRole.UserRole, band_real)
                self.selected_bands.addItem(new_item)
                if self.selected_bands.count() >= 3:
                    break
        self.update_bands_status()
        self._update_downloaded_status()

    def remove_band(self):
        for item in self.selected_bands.selectedItems():
            self.selected_bands.takeItem(self.selected_bands.row(item))
        self.update_bands_status()
        self._update_downloaded_status()

    def apply_preset(self, preset_name: str):
        self._update_composition_buttons()
        if not preset_name or preset_name.startswith("--"):
            return

        bands = self.preset_combo.itemData(self.preset_combo.currentIndex(), Qt.ItemDataRole.UserRole)
        if not bands:
            collection_name = self._current_collection_name()
            built_in, custom = self._collection_presets(
                collection_name, COLLECTIONS.get(collection_name, {}).get("bands", [])
            )
            bands = {**built_in, **custom}.get(preset_name, [])
        if bands:
            collection_id = COLLECTIONS.get(self._current_collection_name(), {}).get("id", "")
            band_info = BAND_INFO.get(collection_id, {})
            self.selected_bands.clear()
            for band in bands:
                common = band_info.get(band, {}).get("common_name")
                item = QListWidgetItem(tr(f"{band} ({common})" if common and common != band else band))
                item.setData(Qt.ItemDataRole.UserRole, band)
                self.selected_bands.addItem(item)
            self.update_bands_status()
