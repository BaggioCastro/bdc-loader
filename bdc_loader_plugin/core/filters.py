# -*- coding: utf-8 -*-
"""
Result filtering mixin for BDCLoaderDialog.

Provides:
- `ResultFilter` — mixin inherited by BDCLoaderDialog that handles:
  - Cloud cover filtering (slider + spinbox sync)
  - Tile / feature-name checkbox filtering (dictionary-based)
  - Date range filtering via a RangeSlider
  - Downloaded-only toggle (styled as BDC Explorer toggle switch)
  - VRT preview label update (items x bands → VRTs)
  - Result clearing

Dependencies:
  stac.parsers       — tile extraction and display formatting
  ui.result_widgets   — TileFilterDialog
"""

import time

from qgis.PyQt.QtCore import QDate, Qt, QTimer
from qgis.PyQt.QtWidgets import QDialog

from ..i18n import count_label, set_text, tr
from ..stac.parsers import cloud_cover
from .catalog_data import COLLECTIONS

# While the cloud slider or the date bar moves, the cards follow at most this often.
_FILTER_EVERY_MS = 40
# A typed cloud value is applied after this pause without a key.
_TYPING_PAUSE_MS = 400

# Scenes without a date are grouped under datetime.min; no BDC image is older than this.
_FIRST_IMAGE_YEAR = 1970


def _item_qdate(item):
    """The item's date as a QDate, or None when it has none."""
    dt = getattr(item, "datetime", None)
    if not dt or dt.year < _FIRST_IMAGE_YEAR:
        return None
    return QDate(dt.year, dt.month, dt.day)


class ResultFilter:
    """Provides result-filter methods for BDCLoaderDialog."""

    # ------------------------------------------------------------------
    # Cloud cover sync
    # ------------------------------------------------------------------
    def _on_cloud_spin_changed(self, value):
        """Typing in the box: the slider follows, and the filter waits for the typing to stop."""
        self.filter_cloud_slider.blockSignals(True)
        self.filter_cloud_slider.setValue(value)
        self.filter_cloud_slider.blockSignals(False)
        self._schedule_filter_update(wait_ms=_TYPING_PAUSE_MS)

    def _on_cloud_slider_changed(self, value):
        """Dragging the slider: the box follows and the cards follow live."""
        self.filter_cloud_spin.blockSignals(True)
        self.filter_cloud_spin.setValue(value)
        self.filter_cloud_spin.blockSignals(False)
        self._schedule_filter_update()

    def _schedule_filter_update(self, wait_ms=None):
        """Apply the filters now, or at most once every _FILTER_EVERY_MS while a control keeps moving.

        With ``wait_ms`` the filters wait for that long without a new change
        instead, as for typed numbers, where a first digit is not the value.
        """
        if not hasattr(self, "_filter_debounce_timer"):
            self._filter_debounce_timer = QTimer()
            self._filter_debounce_timer.setSingleShot(True)
            self._filter_debounce_timer.timeout.connect(self._apply_result_filters)
            self._last_filter_apply = 0.0
        timer = self._filter_debounce_timer
        if wait_ms is not None:
            timer.start(wait_ms)
            return
        if timer.isActive():
            return
        since_ms = (time.monotonic() - self._last_filter_apply) * 1000
        if since_ms >= _FILTER_EVERY_MS:
            self._apply_result_filters()
        else:
            timer.start(max(1, round(_FILTER_EVERY_MS - since_ms)))

    # ------------------------------------------------------------------
    # Main filter engine
    # ------------------------------------------------------------------
    def _apply_result_filters(self, refresh=False):
        """Apply tile, cloud-cover, date and downloaded filters to the results.

        ``refresh`` updates the bands and the load preview even when no card
        changed, as for a new list of results.
        """
        from ..stac.parsers import extract_tile_from_item

        cloud_max = self.filter_cloud_spin.value()

        # Checked tiles (using dictionary)
        checked_tiles = set()
        if hasattr(self, "_tile_filter_dict"):
            for tile_id, tile_data in self._tile_filter_dict.items():
                if tile_data["checked"]:
                    checked_tiles.add(tile_id)

        # Date range from the RangeSlider
        date_from = self.filter_range_slider.get_start_date()
        date_to = self.filter_range_slider.get_end_date()

        visible_count = 0
        changes = []
        for widget in self.result_widgets:
            show = True

            # Tile filter (dictionary)
            if checked_tiles:
                result_mode = self._current_result_mode
                if result_mode == "extent_crop":
                    # Filter crop mosaics: show only if at least one of
                    # its tiles is checked
                    item_tiles = set(
                        t.upper()
                        for t in (getattr(widget.item, "properties", {}) or {}).get("bdc:tiles", [])
                        if t and t != "NA"
                    )
                    if item_tiles and not item_tiles.intersection(checked_tiles):
                        show = False
                elif result_mode == "shape_mosaic":
                    feat = (getattr(widget.item, "properties", {}) or {}).get("bdc:feature_name", "")
                    if feat and feat not in checked_tiles:
                        show = False
                else:
                    tile = extract_tile_from_item(widget.item).upper()
                    if tile not in checked_tiles:
                        show = False

            # Cloud cover filter; a result without a cloud value is kept
            if show and cloud_max < 100:
                cloud = cloud_cover(widget.item)
                if cloud is not None and cloud > cloud_max:
                    show = False

            # Date range filter; a result without a usable date is kept
            if show:
                item_date = _item_qdate(widget.item)
                if item_date and (item_date < date_from or item_date > date_to):
                    show = False

            # Downloaded-only filter (toggle switch)
            if show and self._show_downloaded_only:
                if not widget._downloaded:
                    show = False

            # The filter keeps its own record: a card not shown yet already
            # reads as hidden, and the layout shows it unless it is hidden
            # explicitly.
            if getattr(widget, "_filtered_out", None) is not (not show):
                changes.append((widget, show))
            if show:
                visible_count += 1

        # Only the cards that change are touched, with the list repainted once.
        if changes:
            self.results_container.setUpdatesEnabled(False)
            for widget, show in changes:
                widget.setVisible(show)
                widget._filtered_out = not show
            self.results_container.setUpdatesEnabled(True)
        self._last_filter_apply = time.monotonic()
        # Results that no longer match the panel keep the line that says so.
        if self._results_fresh:
            self._show_result_count(visible_count)

        # The bands and the load preview follow the visible results.
        if changes or refresh:
            self._sync_bands_with_selected_items()
            self._update_vrt_preview()
        return visible_count

    def _show_result_count(self, visible, status_type="info"):
        """Status line: how many results there are and how many the filters hide."""
        total = len(self.result_widgets)
        if visible == total:
            self._set_status(f"{count_label(total, 'image', 'images')} found.", status_type)
        elif total == 1:
            self._set_status("The filters hide the only image found. Click Reset to show it.", "warning")
        elif visible == 0:
            self._set_status(f"The filters hide all {total} images found. Click Reset to show them.", "warning")
        else:
            self._set_status(f"{visible} of {total} images shown by the filters.", status_type)

    # ------------------------------------------------------------------
    # Clear / reset filters
    # ------------------------------------------------------------------
    def _clear_result_filters(self):
        """Reset filters to the search defaults."""
        self.filter_cloud_spin.blockSignals(True)
        self.filter_cloud_spin.setValue(100)
        self.filter_cloud_spin.blockSignals(False)
        self.filter_cloud_slider.blockSignals(True)
        self.filter_cloud_slider.setValue(100)
        self.filter_cloud_slider.blockSignals(False)

        # Reset RangeSlider to full range
        self.filter_range_slider.blockSignals(True)
        min_d = self.filter_range_slider._min_date
        max_d = self.filter_range_slider._max_date
        self.filter_range_slider.set_date_range(min_d, max_d)
        self.filter_range_slider.blockSignals(False)

        # Check all tiles
        if hasattr(self, "_tile_filter_dict"):
            for tile_data in self._tile_filter_dict.values():
                tile_data["checked"] = True
            self._update_tile_filter_button()

        # Reset downloaded-only toggle
        self._show_downloaded_only = False
        if hasattr(self, "downloaded_toggle_btn"):
            self.downloaded_toggle_btn.setChecked(False)
            self._update_toggle_style(False)

        # Show all result widgets
        for widget in self.result_widgets:
            widget.setVisible(True)
            widget._filtered_out = False
        if self.result_widgets:
            self._show_result_count(len(self.result_widgets))
        self._sync_bands_with_selected_items()
        self._update_vrt_preview()

    # ------------------------------------------------------------------
    # Tile filter
    # ------------------------------------------------------------------
    def _populate_tile_checkboxes(self):
        """Populate the tile filter dictionary from search results."""
        from ..stac.parsers import extract_tile_from_item, format_tile_display

        result_mode = self._current_result_mode

        # Extent-crop mode: show unique tiles from all mosaic sub-items
        if result_mode == "extent_crop":
            tiles = set()
            for widget in self.result_widgets:
                tile_list = (getattr(widget.item, "properties", {}) or {}).get("bdc:tiles", [])
                for t in tile_list:
                    if t and t != "NA":
                        tiles.add(t.upper())
            if tiles:
                self._tile_filter_dict = {}
                for tile in sorted(tiles):
                    self._tile_filter_dict[tile] = {
                        "display": format_tile_display(tile, self._current_grid_type),
                        "checked": True,
                    }
                self.tile_filter_btn.setEnabled(True)
                set_text(self.tile_filter_btn, "Tiles")
                set_text(self.tile_count_label, f"({len(tiles)} tiles)")
            else:
                self._tile_filter_dict = {}
                self.tile_filter_btn.setEnabled(False)
                set_text(self.tile_filter_btn, "Tiles")
                set_text(self.tile_count_label, f"({len(self.result_widgets)} dates)")
            return

        if result_mode == "shape_mosaic":
            features = set()
            for widget in self.result_widgets:
                feat = (getattr(widget.item, "properties", {}) or {}).get("bdc:feature_name")
                if feat:
                    features.add(feat)
            if features:
                self._tile_filter_dict = {}
                for feat in sorted(features):
                    self._tile_filter_dict[feat] = {"display": feat, "checked": True}
                self.tile_filter_btn.setEnabled(True)
                set_text(self.tile_filter_btn, "Mosaics")
                checked = len(features)
                set_text(self.tile_count_label, f"({checked} features)")
            else:
                self._tile_filter_dict = {}
                self.tile_filter_btn.setEnabled(False)
                set_text(self.tile_filter_btn, "Mosaics")
                set_text(self.tile_count_label, f"({len(self.result_widgets)} dates)")
            return

        collection_name = self._current_collection_name()
        config = COLLECTIONS.get(collection_name, {})
        if not config.get("has_tiles", True):
            self._tile_filter_dict = {}
            self._update_tile_filter_button()
            return

        self.tile_filter_btn.setEnabled(True)
        set_text(self.tile_filter_btn, "Tiles")

        # Collect unique tiles
        tiles = set()
        for widget in self.result_widgets:
            tile = extract_tile_from_item(widget.item)
            tile = tile.upper() if isinstance(tile, str) else str(tile)
            if tile:
                tiles.add(tile)

        # Create tile dictionary
        self._tile_filter_dict = {}
        for tile in sorted(tiles):
            self._tile_filter_dict[tile] = {
                "display": format_tile_display(tile, self._current_grid_type),
                "checked": True,
            }

        # Update button label
        self._update_tile_filter_button()

    def _open_tile_filter_dialog(self):
        """Open the tile selection dialog."""
        from ..ui.tile_filter_dialog import TileFilterDialog

        if not hasattr(self, "_tile_filter_dict") or not self._tile_filter_dict:
            return

        dialog = TileFilterDialog(self._tile_filter_dict, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Update dictionary with selections
            selected = dialog.get_selected_tiles()
            for tile_id in self._tile_filter_dict:
                self._tile_filter_dict[tile_id]["checked"] = tile_id in selected

            self._update_tile_filter_button()
            self._apply_result_filters()

    def _update_tile_filter_button(self):
        """Update the tile filter button text."""
        if not hasattr(self, "_tile_filter_dict"):
            return

        result_mode = self._current_result_mode
        if result_mode == "extent_crop":
            if self._tile_filter_dict:
                checked = sum(1 for t in self._tile_filter_dict.values() if t["checked"])
                total = len(self._tile_filter_dict)
                self.tile_filter_btn.setEnabled(True)
                set_text(self.tile_filter_btn, "Tiles")
                if checked == total:
                    set_text(self.tile_count_label, f"({total} tiles)")
                else:
                    set_text(self.tile_count_label, f"({checked}/{total} tiles)")
            else:
                self.tile_filter_btn.setEnabled(False)
                set_text(self.tile_filter_btn, "Tiles")
                set_text(self.tile_count_label, f"({len(self.result_widgets)} dates)")
            return
        if result_mode == "shape_mosaic":
            if self._tile_filter_dict:
                checked = sum(1 for t in self._tile_filter_dict.values() if t["checked"])
                total = len(self._tile_filter_dict)
                self.tile_filter_btn.setEnabled(True)
                set_text(self.tile_filter_btn, "Mosaics")
                if checked == total:
                    set_text(self.tile_count_label, f"({total} features)")
                else:
                    set_text(self.tile_count_label, f"({checked}/{total} features)")
            else:
                self.tile_filter_btn.setEnabled(False)
                set_text(self.tile_filter_btn, "Mosaics")
                set_text(self.tile_count_label, f"({len(self.result_widgets)} dates)")
            return

        if not self.tile_filter_btn.isEnabled():
            set_text(self.tile_filter_btn, "Tiles (N/A)")
            self.tile_count_label.setText("")
            return

        checked = sum(1 for t in self._tile_filter_dict.values() if t["checked"])
        total = len(self._tile_filter_dict)

        if checked == total:
            set_text(self.tile_count_label, f"({total} tiles)")
        else:
            set_text(self.tile_count_label, f"({checked}/{total} tiles)")

    # ------------------------------------------------------------------
    # Date range filter
    # ------------------------------------------------------------------
    def _populate_filter_range_bar(self):
        """Populate the RangeSlider with date extremes from search results."""
        if not self.result_widgets:
            return

        min_date = None
        max_date = None
        for widget in self.result_widgets:
            d = _item_qdate(widget.item)
            if d is None:
                continue
            if min_date is None or d < min_date:
                min_date = d
            if max_date is None or d > max_date:
                max_date = d

        if min_date and max_date:
            self.filter_range_slider.set_date_range(min_date, max_date)

    def _on_filter_range_changed(self, start_val, end_val):
        """Dragging the date bar: the cards follow live, at most every _FILTER_EVERY_MS."""
        self._schedule_filter_update()

    def _on_filter_range_changed_from_edit(self, date):
        """A typed date waits for the typing to stop."""
        if self.filter_range_slider.range_bar.is_dragging:
            self._schedule_filter_update()
        else:
            self._schedule_filter_update(wait_ms=_TYPING_PAUSE_MS)

    def _on_filter_range_drag_finished(self):
        """The last position of a drag is always applied."""
        self._schedule_filter_update(wait_ms=0)

    # ------------------------------------------------------------------
    # Downloaded-only toggle
    # ------------------------------------------------------------------
    # Pre-built toggle stylesheets
    _DL_TOGGLE_ON_STYLE = (
        "QPushButton { background-color: #2da44e; color: white; border: 2px solid #2da44e; "
        "border-radius: 12px; text-align: right; padding-right: 4px; font-size: 14px; } "
        "QPushButton:hover { background-color: #2c974b; border-color: #2c974b; }"
    )
    _DL_TOGGLE_OFF_STYLE = (
        "QPushButton { background-color: #d1d5da; color: white; border: 2px solid #d1d5da; "
        "border-radius: 12px; text-align: left; padding-left: 4px; font-size: 14px; } "
        "QPushButton:hover { background-color: #b1b5ba; border-color: #b1b5ba; }"
    )

    def _update_toggle_style(self, checked):
        """Update the toggle switch style (BDC Explorer style with circle)."""
        self.downloaded_toggle_btn.setText("\u25cf")
        self.downloaded_toggle_btn.setStyleSheet(self._DL_TOGGLE_ON_STYLE if checked else self._DL_TOGGLE_OFF_STYLE)

    def _toggle_downloaded_filter(self, checked):
        """Toggle: show only items already downloaded locally."""
        self._show_downloaded_only = checked
        self._update_toggle_style(checked)
        if checked:
            # Refresh filesystem check so flags are fresh before filtering
            self._update_downloaded_status()
        self._apply_result_filters()

    # ------------------------------------------------------------------
    # Load preview
    # ------------------------------------------------------------------
    def _update_vrt_preview(self):
        """Say how many layers Load layers adds and where each one is read from."""
        if not hasattr(self, "vrt_preview_label"):
            return

        # Count selected and visible items
        selected_visible = [w for w in self.result_widgets if w.isVisible() and w.is_selected()]
        count = len(selected_visible)

        # Selected bands
        num_bands = self.selected_bands.count()
        band_names = []
        for i in range(num_bands):
            item = self.selected_bands.item(i)
            band_real = item.data(Qt.ItemDataRole.UserRole) if item.data(Qt.ItemDataRole.UserRole) else item.text()
            band_names.append(band_real)

        if count == 0 or num_bands == 0:
            self.vrt_preview_label.setVisible(False)
            return

        if num_bands == 1:
            mode = f"Single band ({band_names[0]})"
        elif num_bands == 3:
            mode = f"RGB ({', '.join(band_names)})"
        else:
            self.vrt_preview_label.setText(
                tr("<span style='color:#e67e22;'>Loading needs 1 or 3 bands (Download takes any number)</span>")
            )
            self.vrt_preview_label.setVisible(True)
            return

        cropped = self._current_result_mode in ("shape_mosaic", "extent_crop")
        noun = ("cropped layer" if cropped else "layer") + ("s" if count != 1 else "")
        on_disk = sum(1 for w in selected_visible if getattr(w, "_downloaded", False))
        streamed = count - on_disk
        sources = []
        if on_disk:
            sources.append(f"{on_disk} from your downloads")
        if streamed:
            sources.append(f"{streamed} streamed from BDC")
        self.vrt_preview_label.setText(tr(f"<b>{count}</b> {noun} &middot; {mode} &middot; {', '.join(sources)}"))
        self.vrt_preview_label.setVisible(True)

    # ------------------------------------------------------------------
    # Clear results
    # ------------------------------------------------------------------
    def clear_results(self):
        for widget in self.result_widgets:
            if hasattr(widget, "cancel_thumbnail"):
                widget.cancel_thumbnail()
            # Off the layout now: deleteLater alone left old cards on screen
            # until a deferred delete ran, above the next search's results.
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        self.result_widgets.clear()
        self._searched_params = None
        self.found_items = []
        self._current_result_mode = "stac_items"
        self._tile_filter_dict = {}
        if hasattr(self, "tile_filter_btn"):
            set_text(self.tile_filter_btn, "Tiles")
            self.tile_count_label.setText("")
        self.load_btn.setEnabled(False)
        if hasattr(self, "download_selected_btn"):
            self.download_selected_btn.setEnabled(False)
        self._set_status("Image list cleared.", "info")
        # Clear tile dictionary
        if hasattr(self, "_tile_filter_dict"):
            self._tile_filter_dict.clear()
            self.tile_count_label.setText("")
        self.vrt_preview_label.setVisible(False)
        self._sync_bands_with_selected_items()
        self._show_results_fresh(True)
