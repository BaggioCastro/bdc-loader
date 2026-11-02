# -*- coding: utf-8 -*-
"""
TSVisualization — Chart dock, plotting, VRT loading, and export logic.

Handles chart dock lifecycle, plotting (line/RGB), VRT on-click loading,
navigation between history entries, and CSV/vector export delegation.
"""

import logging
import os
import threading
import webbrowser

_logger = logging.getLogger("bdc_loader")

from osgeo import gdal
from qgis.core import QgsProject, QgsRasterLayer, QgsSettings
from qgis.PyQt.QtCore import Qt, QTimer

from ..chart.dock import ChartDock
from ..chart.export import export_csv, export_timeseries_gpkg
from ..chart.plot import apply_axis_ranges, plot_line_chart, plot_rgb_dots
from ..extraction.wtss_extractor import get_wtss_status
from ..i18n import failure_text, language, set_text, tr, translate_tree
from ..paths import usable_folder
from ..ui.thumbnails import _invoke_on_ui_thread
from ..widgets import cursors
from .gdal_env import uses_gdal
from .layer_names import _ts_points_layer_pos, build_vrt_layer_name, build_vrt_layer_name_candidates


def _settings_vrt_bands(settings):
    """Bands the history settings pick for an image: one band, or R, G and B when all three are set."""
    if settings.get("vrt_mode", "rgb") == "single":
        band = settings.get("vrt_single_band", "").strip()
        return [band] if band else []
    rgb = [settings.get(f"vrt_{channel}_band", "").strip() for channel in "rgb"]
    return rgb if all(rgb) else []


def _naive(moment):
    """``moment`` without its time zone, so aware and naive dates compare."""
    return moment.replace(tzinfo=None) if getattr(moment, "tzinfo", None) else moment


def _nearest_series_date(data, bands, clicked_date, intersect):
    """Series date closest to ``clicked_date``, or None when the series has no date.

    With ``intersect`` only dates every band in ``bands`` has count; otherwise
    any date of any band in ``data``.
    """
    if intersect:
        dates = set.intersection(*({row[0] for row in data.get(band, [])} for band in bands))
    else:
        dates = {dt for band_data in data.values() for dt, _val in band_data}
    if not dates:
        return None
    clicked = _naive(clicked_date)
    return min(dates, key=lambda d: abs((_naive(d) - clicked).total_seconds()))


class TSVisualization:
    """Chart dock management, plotting, VRT loading, navigation, and exports."""

    # ================================================================
    # CHART DOCK MANAGEMENT
    # ================================================================

    def _ensure_chart_dock(self):
        created_new = False
        if self.chart_dock is not None:
            try:
                _ = self.chart_dock.isVisible()
            except RuntimeError:
                self.chart_dock = None
        if self.chart_dock is None:
            self.chart_dock = ChartDock(self, self.iface.mainWindow())
            self.chart_dock.visibilityChanged.connect(self._on_chart_visibility_changed)
            self.chart_dock.destroyed.connect(self._on_chart_destroyed)
            self.iface.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.chart_dock)
            if language() != "en":
                translate_tree(self.chart_dock)
            cursors.watch(self.chart_dock)
            created_new = True
        self.chart_dock._restore_from_collapse()
        self.chart_dock.setVisible(True)
        self.chart_dock.raise_()
        self.show_chart_btn.setChecked(True)
        if created_new and 0 <= self._current_viz_index < len(self._history):
            self._update_rgb_combos(
                self._history[self._current_viz_index]["bands"],
                self._history[self._current_viz_index].get("collection", ""),
            )
            self._plot_result(self._history[self._current_viz_index])

    def _rebuild_chart_dock(self):
        """Replace the chart dock with a new one, after matplotlib became available."""
        old = self.chart_dock
        self.chart_dock = None
        if old is not None:
            try:
                old.destroyed.disconnect(self._on_chart_destroyed)
            except (RuntimeError, TypeError):
                pass
            self.iface.removeDockWidget(old)
            old.deleteLater()
        self._ensure_chart_dock()

    def _toggle_chart_dock(self, checked):
        if checked:
            self._ensure_chart_dock()
        else:
            if self.chart_dock:
                self.chart_dock.setVisible(False)

    def _on_chart_visibility_changed(self, visible):
        self.show_chart_btn.setChecked(visible)

    def _on_chart_destroyed(self):
        self.chart_dock = None
        self.show_chart_btn.setChecked(False)

    def _on_auto_center_toggled(self, checked):
        self._auto_center = checked

    def _replot_current(self):
        if self._current_viz_index >= 0 and self._current_viz_index < len(self._history):
            self._plot_result(self._history[self._current_viz_index])

    def _refresh_chart_ranges(self):
        """Apply range changes to the current axes without rebuilding the plot."""
        if not self.chart_dock or not self.chart_dock.figure:
            return
        axes = self.chart_dock.figure.axes
        if not axes:
            self._replot_current()
            return
        apply_axis_ranges(axes[0], self.chart_dock)
        self.chart_dock.canvas_plot.draw_idle()

    # ================================================================
    # STATUS & WTSS
    # ================================================================

    def _set_status(self, text, level="info", duration_ms=2500):
        """Display a status message with visual level coding."""
        _styles = {
            "info": ("\u25cf", "#1a5276", "#eaf2f8", "#aed6f1"),
            "success": ("\u2714", "#1e8449", "#eafaf1", "#a9dfbf"),
            "error": ("\u2716", "#922b21", "#fdedec", "#f5b7b1"),
            "warning": ("\u25b2", "#784212", "#fef9e7", "#f9e79f"),
            "loading": ("\u21bb", "#6c3483", "#f4ecf7", "#d2b4de"),
            "pending": ("\u25c9", "#2c3e50", "#ecf0f1", "#bdc3c7"),
        }
        icon, fg, bg, border = _styles.get(level, _styles["info"])
        full_text = f"{icon}  {tr(text)}" if text else ""
        self.status_label.setText(full_text)
        if text:
            self.status_label.setStyleSheet(
                f"color: {fg}; background-color: {bg}; "
                f"border: 1px solid {border}; "
                "font-size: 9px; font-weight: bold; "
                "border-radius: 3px; padding: 1px 6px;"
            )
        else:
            self._reset_status_style()
        if text and duration_ms > 0:
            QTimer.singleShot(duration_ms, lambda t=full_text: self._clear_status_if_unchanged(t))

    def _clear_status_if_unchanged(self, text):
        """Reset the status style unless a newer message replaced ``text``.

        The timer can fire after the panel was closed or the plugin reloaded,
        when the label no longer exists.
        """
        from qgis.PyQt import sip

        label = getattr(self, "status_label", None)
        if label is None or sip.isdeleted(label) or sip.isdeleted(self):
            return
        if label.text() == text:
            self._reset_status_style()

    def _on_wtss_status_clicked(self, event):
        if event is not None:
            event.accept()
        webbrowser.open(self._wtss_status_url)

    def _check_wtss_status(self):
        """Check WTSS health asynchronously and update indicator."""
        if getattr(self, "_wtss_ping_running", False):
            return
        self._wtss_ping_running = True

        def _run():
            try:
                online, ms = get_wtss_status()
            except Exception:
                _logger.warning("WTSS status check failed", exc_info=True)
                online, ms = False, 0.0

            def _done():
                self._wtss_ping_running = False
                if getattr(self, "_ts_closing", False):
                    return
                self._set_wtss_indicator(online, ms)

            _invoke_on_ui_thread(_done)

        threading.Thread(target=_run, daemon=True, name="bdc-wtss-health").start()

    def _set_wtss_indicator(self, online: bool, latency_ms: float = 0.0):
        if not hasattr(self, "_wtss_dot"):
            return
        if online:
            color = "#27ae60"
            text = f"WTSS: {latency_ms:.0f}ms"
            tip = f"WTSS online — {latency_ms:.0f} ms"
        else:
            color = "#e74c3c"
            text = "WTSS: offline"
            tip = "WTSS unavailable — using STAC+VRT as fallback"
        self._wtss_dot.setStyleSheet(f"background-color: {color}; border-radius: 4px;")
        self._wtss_lbl.setText(f"<span style='color:{color};font-size:9px;'>{tr(text)}</span>")
        set_text(self._wtss_dot, tip, "tip")
        set_text(self._wtss_lbl, tip, "tip")

    # ================================================================
    # NAVIGATION
    # ================================================================

    def _update_viz_navigation(self):
        if not self.chart_dock:
            return
        total = len(self._history)
        if total == 0:
            self.chart_dock.chart_page_label.setText("0/0")
            self.chart_dock.prev_chart_btn.setEnabled(False)
            self.chart_dock.next_chart_btn.setEnabled(False)
            self.chart_dock.viz_point_label.setText("")
            return
        idx = self._current_viz_index
        self.chart_dock.chart_page_label.setText(f"{idx + 1}/{total}")
        self.chart_dock.prev_chart_btn.setEnabled(idx > 0)
        self.chart_dock.next_chart_btn.setEnabled(idx < total - 1)
        entry = self._history[idx]
        self.chart_dock.viz_point_label.setText(
            f"#{entry['id']} | {entry['label']} ({entry['lon']:.4f}, {entry['lat']:.4f})"
        )

    def _change_viz(self, delta):
        new_idx = self._current_viz_index + delta
        if new_idx < 0 or new_idx >= len(self._history):
            return
        self._current_viz_index = new_idx
        self._update_viz_navigation()
        entry = self._history[new_idx]
        self._update_rgb_combos(entry["bands"], entry.get("collection", ""))
        self.chart_dock.reset_axis_ranges()
        self._plot_result(entry)
        self.history_list.blockSignals(True)
        self.history_list.setCurrentRow(new_idx)
        self.history_list.blockSignals(False)
        if self._auto_center:
            self._zoom_to_point(entry["lon"], entry["lat"])

    # ================================================================
    # PLOTTING
    # ================================================================

    def _plot_result(self, hist_entry):
        if not self.chart_dock or not self.chart_dock.figure:
            return
        if self.chart_dock.line_mode_btn.isChecked():
            plot_line_chart(self.chart_dock, hist_entry)
        else:
            r_band = self.chart_dock.rgb_r_combo.currentData()
            g_band = self.chart_dock.rgb_g_combo.currentData()
            b_band = self.chart_dock.rgb_b_combo.currentData()
            rgb_bands = [b for b in [r_band, g_band, b_band] if b]

            # Auto-fetch bands missing from this entry (e.g. when navigating to a
            # series extracted without RGB bands). Guard with _rgb_bands_downloading
            # to avoid re-entrant calls from within _fetch_additional_bands itself.
            if not self._rgb_bands_downloading and rgb_bands:
                missing = [b for b in rgb_bands if b not in hist_entry.get("data", {})]
                if missing:
                    self._fetch_additional_bands(hist_entry, missing)
                    return

            plot_rgb_dots(self.chart_dock, hist_entry)

    # ================================================================
    # CHART CLICK — VRT LOADING
    # ================================================================

    def _on_chart_date_clicked(self, clicked_date):
        """Load the image of the series date nearest to the click, built in the background."""
        if self._current_viz_index < 0 or self._current_viz_index >= len(self._history):
            return

        entry = self._history[self._current_viz_index]
        is_rgb_mode = self.chart_dock and self.chart_dock.rgb_mode_btn.isChecked()
        bands_to_load = self._chart_vrt_bands(entry, is_rgb_mode)
        if not bands_to_load:
            return
        # An RGB composite needs a date all three bands have.
        intersect = bool(is_rgb_mode and len(bands_to_load) == 3)
        nearest_date = _nearest_series_date(entry.get("data", {}), bands_to_load, clicked_date, intersect)
        if nearest_date is None:
            return

        if getattr(self, "_chart_vrt_running", False):
            self._chart_vrt_pending = clicked_date
            return
        self._start_chart_vrt_request(entry, nearest_date.strftime("%Y-%m-%d"), bands_to_load, clicked_date)

    def _chart_vrt_bands(self, entry, is_rgb_mode):
        """Bands of the image to load for a clicked date.

        In order: the chart's R, G and B choice in RGB mode, the collection's
        RGB preset, the history settings, then the first extracted band. A
        choice is used only when the series has every band it names.
        """
        data = entry.get("data", {})
        if is_rgb_mode:
            combos = (self.chart_dock.rgb_r_combo, self.chart_dock.rgb_g_combo, self.chart_dock.rgb_b_combo)
            combo_bands = [band for band in (combo.currentData() for combo in combos) if band]
            if len(combo_bands) == 3 and all(band in data for band in combo_bands):
                return combo_bands

        rgb = self._get_rgb_for_collection(entry.get("collection", ""), entry.get("bands", []))
        if rgb:
            r, g, b = rgb
            if r in data and g in data and b in data:
                return [r, g, b]
        return _settings_vrt_bands(self._hist_settings) or entry.get("bands", [])[:1]

    def _start_chart_vrt_request(self, entry, date_str, bands_to_load, clicked_date):
        """Search the item and build its VRT in a worker; _finish_chart_vrt_request adds the layer."""
        cid = entry.get("collection", "")
        lon = entry.get("lon", 0.0)
        lat = entry.get("lat", 0.0)
        existing_names = {lyr.name() for lyr in QgsProject.instance().mapLayers().values()}
        settings = QgsSettings()
        vrt_dir, _problem = usable_folder(
            settings.value("bdc_loader/vrt_dir", os.path.expanduser("~/bdc_vrt/"), type=str), "vrt"
        )
        naming_format = settings.value("bdc_loader/layer_naming_format", "stac", type=str)
        self._chart_vrt_running = True
        self._chart_vrt_pending = None
        self._set_status(f"Opening the image of {date_str}...", "loading", 0)

        def _run():
            try:
                result = self._build_chart_vrt_request(
                    cid,
                    lon,
                    lat,
                    date_str,
                    list(bands_to_load),
                    existing_names,
                    vrt_dir,
                    naming_format,
                )
            except Exception as exc:
                _logger.warning("Chart VRT request failed", exc_info=True)
                result = {"status": "error", "message": str(exc)}
            result.setdefault("date_str", date_str)
            _invoke_on_ui_thread(lambda: self._finish_chart_vrt_request(clicked_date, result))

        threading.Thread(target=_run, daemon=True, name="bdc-chart-vrt").start()

    @uses_gdal
    def _build_chart_vrt_request(
        self,
        cid,
        lon,
        lat,
        date_str,
        bands_to_load,
        existing_names,
        vrt_dir,
        naming_format,
    ):
        """Search the selected date and build its VRT outside the Qt thread."""
        items = self._search_items(cid, lon, lat, date_str, date_str, 1)
        if not items:
            return {"status": "no_items", "date_str": date_str}

        item = items[0]
        from ..stac.parsers import extract_tile_from_item

        tile_safe = extract_tile_from_item(item).replace("/", "-")
        num_bands = len(bands_to_load)
        effective_bands = bands_to_load if num_bands == 3 else bands_to_load[:1]
        name_candidates = build_vrt_layer_name_candidates(
            item.id,
            cid,
            tile_safe,
            date_str,
            effective_bands,
        )
        existing_name = next((name for name in name_candidates if name in existing_names), None)
        if existing_name is not None:
            return {"status": "existing", "layer_name": existing_name}

        layer_name = build_vrt_layer_name(
            item.id, cid, tile_safe, date_str, effective_bands, naming_format=naming_format
        )

        def _find_asset(band_name):
            if band_name in item.assets:
                return item.assets[band_name]
            band_lower = band_name.lower()
            return next((asset for key, asset in item.assets.items() if key.lower() == band_lower), None)

        hrefs = []
        for band in effective_bands:
            asset = _find_asset(band)
            if not asset:
                return {"status": "missing_band", "band": band}
            hrefs.append(f"/vsicurl/{asset.href}")

        os.makedirs(vrt_dir, exist_ok=True)
        vrt_path = os.path.join(vrt_dir, f"{layer_name}.vrt")
        if num_bands == 3:
            options = gdal.BuildVRTOptions(resampleAlg="nearest", separate=True)
        else:
            options = gdal.BuildVRTOptions(resampleAlg="nearest")
        vrt = gdal.BuildVRT(vrt_path, hrefs, options=options)
        if not vrt:
            return {"status": "build_failed", "layer_name": layer_name}
        vrt = None
        return {
            "status": "built",
            "vrt_path": vrt_path,
            "layer_name": layer_name,
            "cid": cid,
            "tile_safe": tile_safe,
        }

    def _finish_chart_vrt_request(self, clicked_date, result):
        """Apply a chart VRT result on the UI thread and execute the latest queued click."""
        self._chart_vrt_running = False
        if getattr(self, "_ts_closing", False):
            self._chart_vrt_pending = None
            return

        pending = getattr(self, "_chart_vrt_pending", None)
        self._chart_vrt_pending = None
        if pending is not None and pending != clicked_date:
            self._on_chart_date_clicked(pending)
            return

        status = result.get("status")
        if status == "no_items":
            self._set_status(f"No image found for {result['date_str']}.", "warning")
            return
        if status == "missing_band":
            self._set_status(f"Band {result['band']} is not available.", "warning")
            return
        if status == "existing":
            self._show_existing_layer(result["layer_name"])
            return
        process = f"Opening the image of {result['date_str']}"
        if status == "build_failed":
            self._flash_status(failure_text(process, f"{result['layer_name']} could not be built"), success=False)
            return
        if status != "built":
            self._flash_status(failure_text(process, result.get("message", "unknown error")), success=False)
            return

        vrt_path = result["vrt_path"]
        layer_name = result["layer_name"]
        cid = result["cid"]
        tile_safe = result["tile_safe"]
        layer = QgsRasterLayer(vrt_path, layer_name)
        if layer.isValid():
            root = QgsProject.instance().layerTreeRoot()
            self._chart_hidden_layers = []
            for tree_lyr in root.findLayers():
                node_layer = tree_lyr.layer()
                if node_layer and isinstance(node_layer, QgsRasterLayer) and tree_lyr.isVisible():
                    tree_lyr.setItemVisibilityChecked(False)
                    self._chart_hidden_layers.append(tree_lyr)

            group_name = f"{cid} / {tile_safe}"
            grp = root.findGroup(group_name)
            if not grp:
                grp = root.insertGroup(_ts_points_layer_pos(root), group_name)
            QgsProject.instance().addMapLayer(layer, False)
            grp.addLayer(layer)
            layer_node = grp.findLayer(layer.id())
            if layer_node:
                layer_node.setExpanded(False)
            self._move_temp_layer_to_top()
            self.iface.setActiveLayer(layer)
            self.iface.mapCanvas().refresh()
            if self.chart_dock and self.chart_dock.line_mode_btn.isChecked():
                self.chart_dock.line_mode_btn.blockSignals(True)
                self.chart_dock.rgb_mode_btn.blockSignals(True)
                self.chart_dock.line_mode_btn.setChecked(False)
                self.chart_dock.rgb_mode_btn.setChecked(True)
                self.chart_dock.line_mode_btn.blockSignals(False)
                self.chart_dock.rgb_mode_btn.blockSignals(False)
                self.chart_dock._on_mode_changed()
                self._replot_current()
            self._flash_status(f"Layer {layer_name} added to the map.", success=True)
        else:
            self._flash_status(failure_text(process, f"QGIS could not read {layer_name}"), success=False)

    def _show_existing_layer(self, layer_name):
        root = QgsProject.instance().layerTreeRoot()
        for tree_lyr in root.findLayers():
            node_layer = tree_lyr.layer()
            if node_layer and isinstance(node_layer, QgsRasterLayer) and tree_lyr.isVisible():
                tree_lyr.setItemVisibilityChecked(False)
        for lyr in QgsProject.instance().mapLayers().values():
            if lyr.name() == layer_name:
                tree_node = root.findLayer(lyr.id())
                if tree_node:
                    tree_node.setItemVisibilityChecked(True)
                self.iface.setActiveLayer(lyr)
                break
        self.iface.mapCanvas().refresh()
        self._flash_status(f"Layer {layer_name} shown on the map.", success=True)

    def _flash_status(self, message, success=True):
        level = "success" if success else "error"
        self._set_status(message, level=level, duration_ms=4000)

    def _reset_status_style(self):
        self.status_label.setText("")
        self.status_label.setStyleSheet(
            "font-size: 9px; color: #7f8c8d; font-weight: bold; "
            "background-color: #ecf0f1; border: 1px solid #ddd; "
            "border-radius: 3px; padding: 1px 6px;"
        )

    # ================================================================
    # EXPORTS
    # ================================================================

    def _export_csv(self):
        export_csv(self, self._history, self.status_label)

    def _export_gpkg(self):
        export_timeseries_gpkg(self, self._history, self.status_label)
