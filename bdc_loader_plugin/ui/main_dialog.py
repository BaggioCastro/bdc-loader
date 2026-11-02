# -*- coding: utf-8 -*-
"""
Main window of the BDC Loader plugin.

BDCLoaderDialog combines mixins, each owning one part of the window:

  MainDialogLayout  (ui/main_layout.py)       widgets of every section
  VrtGenerator      (core/vrt_generator.py)   loading results as VRT layers
  SearchEngine      (core/search.py)          STAC search
  ResultFilter      (core/filters.py)         period, cloud and tile filters
  CatalogManager    (core/catalog.py)         collections, bands and presets
  DownloadManager   (core/download.py)        downloads of the selected results
  ShapefileHandler  (core/shapefile.py)       vector files as the search area
  GridManager       (core/grid.py)            tile grids and tile picking

This module keeps the window's own behaviour: the extent box, panel toggles,
status line and settings. The collection catalogue the mixins read is in
core/catalog_data.py.
"""

import os
import time
import webbrowser

from ..i18n import OFFLINE_PREFIX, LanguageWatcher, language, set_language, set_text, tr, translate_tree
from ..logger import error as _log_error
from ..logger import info as _log_info
from ..logger import warning as _log_warning
from ..paths import grids_dir, usable_folder
from ..vendored import ensure_pystac_client

pystac_client = ensure_pystac_client()
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsSettings,
)
from qgis.gui import (
    QgsRubberBand,
)
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
)

from ..core.catalog import CatalogManager
from ..core.download import DownloadManager
from ..core.filters import ResultFilter
from ..core.grid import GridManager
from ..core.search import SearchEngine
from ..core.shapefile import ShapefileHandler
from ..core.vrt_generator import VrtGenerator
from ..stac.client import STAC_URL
from ..timing import (
    BBOX_FLASH_MS,
    EXTENT_CAPTURE_SETTLE_MS,
    STARTUP_STAC_CHECK_MS,
    STARTUP_STORAGE_CHECK_MS,
    STARTUP_TOUR_MS,
    THUMBNAILS_AFTER_LAYOUT_MS,
)
from ..widgets import cursors
from .bdc_projection import apply_bdc_projection
from .main_layout import MainDialogLayout
from .result_widgets import ResultItemWidget
from .settings_dialog import BDCSettingsDialog


class BDCLoaderDialog(
    MainDialogLayout,
    VrtGenerator,
    SearchEngine,
    ResultFilter,
    CatalogManager,
    DownloadManager,
    ShapefileHandler,
    GridManager,
    QDialog,
):
    def __init__(self, iface, timeline_toolbar=None):
        super().__init__()
        self.iface = iface
        self._timeline_toolbar = timeline_toolbar
        self.client = None
        self.found_items = []
        self.result_widgets = []
        self.tile_select_tool = None
        self.previous_tool = None
        self.grid_layer = None
        self.compact_view = False
        self._generating_vrt = False
        self._current_collection_id = ""
        self._current_grid_type = ""
        self._current_result_mode = "stac_items"
        self._stac_online = None  # None = not checked, True/False = live status
        self._stac_response_time_ms = 0
        self._stac_temporal_cache = {}  # {collection_id: temporal_extent}
        self._collection_asset_cache = {}  # {collection_id: current item asset names}
        self._collection_asset_checks = set()
        self._tile_filter_dict = {}  # {tile_id: {'display': str, 'checked': bool}}
        self._show_downloaded_only = False
        self._hidden_collections = set()
        self.grids_dir = grids_dir()
        self._ts_panel = None
        self._download_cancelled = False
        self._download_in_progress = False
        self._vrt_cancelled = False
        self._vrt_executor = None
        self._extent_signal_ready = False
        self._extent_restore_pending = False
        self._search_in_progress = False
        self._searched_params = None  # the parameters of the results on screen
        self._results_fresh = True
        self._load_path_settings()
        self.setup_ui()
        self._report_folder_problems()
        self._watch_search_params()
        self._language_watcher = LanguageWatcher(self)
        self._language_watcher.watch(self)
        cursors.watch(self)
        if language() != "en":
            self._apply_language()
        self.center_on_screen()
        QTimer.singleShot(0, self._enable_extent_signals)
        QTimer.singleShot(STARTUP_STAC_CHECK_MS, self._check_stac_status)
        QTimer.singleShot(STARTUP_STORAGE_CHECK_MS, self._check_storage_usage)
        self._tour = None
        QTimer.singleShot(STARTUP_TOUR_MS, self._start_tour_on_first_use)

    def _on_stac_status_clicked(self, event):
        """Open the STAC offline dialog if offline, otherwise open the URL."""
        if event is not None:
            event.accept()
        if self._stac_online is False:
            self._show_stac_offline_dialog()
        else:
            webbrowser.open(STAC_URL)

    def _on_perf_status_clicked(self, event):
        """Open the settings dialog from the performance status bar."""
        if event is not None:
            event.accept()
        self._open_settings()

    def _toggle_timeseries_panel(self, checked):
        """Toggle the WTSS time-series dock panel."""
        self._update_ts_toggle_style(checked)
        from .timeseries_panel import BDCTimeSeriesPanel

        if checked:
            if not self._ts_panel:
                self._ts_panel = BDCTimeSeriesPanel(self.iface, self.iface.mainWindow())
                self._ts_panel.visibilityChanged.connect(self._on_ts_panel_visibility_changed)
                self._language_watcher.watch(self._ts_panel)
                cursors.watch(self._ts_panel)
                if language() != "en":
                    translate_tree(self._ts_panel)
                self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._ts_panel)
            else:
                self._ts_panel.setVisible(True)
                self._ts_panel.raise_()
        else:
            if self._ts_panel:
                self._ts_panel.setVisible(False)

    def _on_ts_panel_visibility_changed(self, visible):
        """Sync the TS toggle button when the panel is closed by the user."""
        if hasattr(self, "ts_btn"):
            self.ts_btn.setChecked(visible)
            self._update_ts_toggle_style(visible)

    def _toggle_timeline_toolbar(self, checked):
        """Toggle the Timeline Toolbar visibility."""
        self._update_tl_toggle_style(checked)
        if self._timeline_toolbar:
            self._timeline_toolbar.setVisible(checked)

    def _enable_extent_signals(self):
        self._extent_signal_ready = True

    def _restore_dialog_focus(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_extent_changed(self, *_args):
        """A complete extent makes Extent the area filter in use.

        A half-typed one is left alone; only the clear button releases Extent.
        """
        if not self._extent_signal_ready or not hasattr(self, "extent_box"):
            return
        if not self.extent_box.hasExtent():
            return
        extent = self.extent_box.outputExtent()
        if extent.width() < 1e-12 or extent.height() < 1e-12:
            return
        self.extent_box.setActive(True)
        self._update_extent_bbox_label()
        if self._extent_restore_pending or not self.extent_box.wasDrawn():
            return
        self._extent_restore_pending = True
        QTimer.singleShot(EXTENT_CAPTURE_SETTLE_MS, self._finalize_extent_capture)

    def _update_extent_bbox_label(self):
        """Update the bbox coordinates field next to the mode selector."""
        if not hasattr(self, "_extent_bbox_edit"):
            return
        bbox = self.get_bbox_from_extent()
        if bbox:
            self._extent_bbox_edit.setText(f"{bbox[0]:.4f},{bbox[1]:.4f},{bbox[2]:.4f},{bbox[3]:.4f}")
        else:
            self._extent_bbox_edit.setText("")

    def _apply_manual_bbox(self):
        """Parse bbox from the text field and update the extent box."""
        text = self._extent_bbox_edit.text().strip()
        if not text:
            return
        try:
            parts = [float(x.strip()) for x in text.split(",")]
            if len(parts) != 4:
                self._set_status("Invalid bbox: type xmin,ymin,xmax,ymax.", "warning")
                return
            xmin, ymin, xmax, ymax = parts
            if xmin >= xmax or ymin >= ymax:
                self._set_status("Invalid bbox: the minimum must be less than the maximum.", "warning")
                return
            rect = QgsRectangle(xmin, ymin, xmax, ymax)
            crs = QgsCoordinateReferenceSystem("EPSG:4326")
            self.extent_box.setOutputExtentFromUser(rect, crs)
            self.extent_box.setActive(True)
            self.extent_box.setCollapsed(False)
            self._set_status("Extent set from manual bbox.", "success")
        except ValueError:
            self._set_status("Invalid bbox: use numbers, for example -65.31,-11.94,-62.97,-9.73.", "warning")

    def _copy_bbox_to_clipboard(self):
        """Copy the bbox text to system clipboard."""
        text = self._extent_bbox_edit.text().strip()
        if text:
            QApplication.clipboard().setText(text)
            self._set_status("Bbox copied to the clipboard.", "success")

    def _center_on_bbox(self):
        """Zoom the map canvas to the current bbox and flash the rectangle."""
        text = self._extent_bbox_edit.text().strip()
        if not text:
            self._set_status("No bbox to center on.", "warning")
            return
        try:
            parts = [float(x.strip()) for x in text.split(",")]
            if len(parts) != 4:
                return
            xmin, ymin, xmax, ymax = parts
            rect = QgsRectangle(xmin, ymin, xmax, ymax)
            src_crs = QgsCoordinateReferenceSystem("EPSG:4326")
            canvas = self.iface.mapCanvas()
            dst_crs = canvas.mapSettings().destinationCrs()
            if src_crs != dst_crs:
                xform = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())
                rect = xform.transformBoundingBox(rect)
            canvas.setExtent(rect)
            canvas.refresh()
            self._flash_bbox_on_canvas(rect)
        except Exception:
            import logging

            logging.getLogger("bdc_loader").debug("Zoom-to-bbox failed", exc_info=True)

    def _flash_bbox_on_canvas(self, rect):
        """Draw a dashed bbox on the canvas that disappears after 3 seconds."""
        canvas = self.iface.mapCanvas()
        rb = QgsRubberBand(canvas, False)
        rb.setColor(QColor(255, 50, 50, 200))
        rb.setWidth(2)
        rb.setLineStyle(Qt.PenStyle.DashLine)
        rb.addPoint(QgsPointXY(rect.xMinimum(), rect.yMinimum()), False)
        rb.addPoint(QgsPointXY(rect.xMaximum(), rect.yMinimum()), False)
        rb.addPoint(QgsPointXY(rect.xMaximum(), rect.yMaximum()), False)
        rb.addPoint(QgsPointXY(rect.xMinimum(), rect.yMaximum()), False)
        rb.addPoint(QgsPointXY(rect.xMinimum(), rect.yMinimum()), True)
        rb.show()
        QTimer.singleShot(BBOX_FLASH_MS, lambda: (rb.hide(), canvas.scene().removeItem(rb)))

    def _finalize_extent_capture(self):
        self._extent_restore_pending = False
        bbox = self.get_bbox_from_extent()
        if not bbox:
            return
        try:
            self.iface.actionPan().trigger()
        except Exception:
            pass
        try:
            self.iface.messageBar().clearWidgets()
        except Exception:
            pass
        self._restore_dialog_focus()
        self._set_status("Extent captured from map.", "success")
        self._update_extent_bbox_label()

    def _on_tl_toolbar_visibility_changed(self, visible):
        """Sync the TL toggle when the toolbar is closed externally."""
        if hasattr(self, "tl_btn"):
            self.tl_btn.setChecked(visible)
            self._update_tl_toggle_style(visible)

    # Pre-built toggle stylesheets (avoid rebuilding on every click)
    _TOGGLE_OFF_STYLE = (
        "QPushButton { background-color: #d1d5da; color: white; border: 2px solid #d1d5da; "
        "border-radius: 12px; text-align: left; padding-left: 4px; font-size: 14px; } "
        "QPushButton:hover { background-color: #b1b5ba; border-color: #b1b5ba; }"
    )
    _TL_TOGGLE_ON_STYLE = (
        "QPushButton { background-color: #27ae60; color: white; border: 2px solid #27ae60; "
        "border-radius: 12px; text-align: right; padding-right: 4px; font-size: 14px; } "
        "QPushButton:hover { background-color: #229954; border-color: #229954; }"
    )
    _TS_TOGGLE_ON_STYLE = (
        "QPushButton { background-color: #8e44ad; color: white; border: 2px solid #8e44ad; "
        "border-radius: 12px; text-align: right; padding-right: 4px; font-size: 14px; } "
        "QPushButton:hover { background-color: #7d3c98; border-color: #7d3c98; }"
    )

    def _update_tl_toggle_style(self, checked):
        """Update the Timeline toggle switch style."""
        self.tl_btn.setText("\u25cf")
        self.tl_btn.setStyleSheet(self._TL_TOGGLE_ON_STYLE if checked else self._TOGGLE_OFF_STYLE)

    def _update_ts_toggle_style(self, checked):
        """Update the TS toggle switch style."""
        self.ts_btn.setText("\u25cf")
        self.ts_btn.setStyleSheet(self._TS_TOGGLE_ON_STYLE if checked else self._TOGGLE_OFF_STYLE)

    def _load_path_settings(self):
        """Load VRT and download paths from persistent settings.

        A chosen folder that cannot hold files is replaced by one under the
        QGIS profile for this session; _report_folder_problems says so.
        """
        settings = QgsSettings()
        self._folder_problems = []
        folders = []
        for key, default, fallback in (
            ("vrt_dir", "~/bdc_vrt/", "vrt"),
            ("download_dir", "~/bdc_downloads/", "downloads"),
        ):
            chosen = settings.value(f"bdc_loader/{key}", os.path.expanduser(default), type=str)
            folder, problem = usable_folder(chosen, fallback)
            if problem is not None:
                _log_warning(f"Folder {chosen} cannot be used ({problem}); using {folder} in this session.")
                self._folder_problems.append((chosen, folder))
            folders.append(folder)
        self._vrt_dir, self._download_dir = folders

    def _report_folder_problems(self):
        for chosen, folder in self._folder_problems:
            self._set_status(
                f"Folder {chosen} is not available; files go to {folder} in this session. Change it in Settings.",
                "warning",
            )

    def _check_storage_usage(self):
        """Warn user if generated files exceed per-folder thresholds."""
        settings = QgsSettings()
        folders = [
            (self._vrt_dir, settings.value("bdc_loader/threshold_vrt_mb", 500, type=int)),
            (self._download_dir, settings.value("bdc_loader/threshold_dl_mb", 5000, type=int)),
        ]
        total = 0
        over_threshold = False
        for folder, threshold_mb in folders:
            if not os.path.isdir(folder):
                continue
            folder_bytes = 0
            for dirpath, _dirs, files in os.walk(folder):
                for f in files:
                    try:
                        folder_bytes += os.path.getsize(os.path.join(dirpath, f))
                    except OSError:
                        pass
            total += folder_bytes
            if folder_bytes > threshold_mb * 1024 * 1024:
                over_threshold = True
        if not over_threshold:
            return
        size_mb = total / (1024 * 1024)
        self._set_status(
            f"Generated files take {size_mb:.0f} MB of disk. To free space, open the Storage tab in Settings.",
            "warning",
        )

    def _open_settings(self):
        """Open the plugin settings dialog."""
        dialog = BDCSettingsDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._load_path_settings()
            self.output_dir.setText(self._vrt_dir)
            self._reload_runtime_config()
            self._set_status("Settings saved.", "success")
            self._report_folder_problems()
            self._update_perf_status_bar()
        if dialog.tutorial_requested:
            QTimer.singleShot(0, self.start_tour)

    def _reload_runtime_config(self):
        """Immediately reapply saved performance settings to active components."""
        try:
            from ..extraction.wtss_extractor import reset_request_semaphore

            reset_request_semaphore()
        except Exception as exc:
            _log_warning(f"The new WTSS worker count could not be applied until restart: {exc}")
        try:
            from ..core.download_engine import reset_throttling

            reset_throttling()
        except Exception as exc:
            _log_warning(f"The download connection limit could not be reset: {exc}")

    def _update_perf_status_bar(self):
        """Update the fixed performance status bar at the bottom."""
        try:
            from ..config import detect_system_profile, get_performance_config

            profile = detect_system_profile()
            perf = get_performance_config()
            cpus = os.cpu_count() or "?"
            # RAM detection
            ram_str = "?"
            try:
                from ..config import _get_total_ram_gb

                ram = _get_total_ram_gb()
                if ram:
                    ram_str = f"{ram:.0f}"
            except Exception:
                pass
            mt = perf.get("max_threads", "?")
            self._perf_status.setText(
                tr(
                    f"⚡ {cpus} cores, {ram_str} GB RAM → <b>{profile.upper()}</b> "
                    f"({mt} threads) · "
                    f"<span style='text-decoration: underline;'>Change in Settings ⚙</span>"
                )
            )
        except Exception:
            self._perf_status.setText(tr("⚡ Performance: click to configure"))

    def center_on_screen(self):
        """Center on the screen that shows the QGIS window, inside its free area.

        The free area excludes system panels and docks, and its origin is kept so
        the dialog lands on the right monitor in multi-screen setups.
        """
        screen = None
        main_window = self.iface.mainWindow() if self.iface else None
        if main_window is not None:
            screen = QApplication.screenAt(main_window.geometry().center())
        area = (screen or QApplication.primaryScreen()).availableGeometry()
        minimum = self.minimumSizeHint()
        width = min(area.width(), max(int(area.width() * 0.75), minimum.width()))
        height = min(area.height(), max(int(area.height() * 0.85), minimum.height()))
        x = area.x() + (area.width() - width) // 2
        y = area.y() + (area.height() - height) // 2
        self.setGeometry(x, y, width, height)

    def _cancel_vrt_generation(self):
        """Cancel an in-progress VRT generation."""
        self._vrt_cancelled = True
        self._set_status("Cancelling layer loading...", "warning")
        # shutdown(cancel_futures=True) requires Python 3.9+
        if self._vrt_executor:
            try:
                self._vrt_executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                self._vrt_executor.shutdown(wait=False)

    def _set_language(self, lang):
        """Switch the interface language from the header flags."""
        if lang != language():
            set_language(lang)
            self._apply_language()

    def _apply_language(self):
        """Show every open part of the plugin in the chosen language."""
        lang = language()
        panel = self._ts_panel
        for root in (self, self._timeline_toolbar, panel, getattr(panel, "chart_dock", None)):
            translate_tree(root, lang)
        if panel is not None and getattr(panel, "chart_dock", None) is not None and getattr(panel, "_history", None):
            panel._replot_current()  # axis titles of the chart
        buttons = getattr(self, "language_buttons", {})
        if lang in buttons:
            buttons[lang].setChecked(True)
        # The language is applied while the dialog is built, before it has a tour.
        tour = getattr(self, "_tour", None)
        if tour is not None:
            tour.tour.refresh()

    def start_tour(self):
        """Show the guided tour from its first step."""
        from .tour_steps import PluginTour

        if self._tour is None:
            self._tour = PluginTour(self)
        if not self._tour.tour.running:
            self._tour.start()

    def _start_tour_on_first_use(self):
        """Offer the tour the first time the plugin window is shown."""
        from .tour_steps import tour_seen

        if self.isVisible() and not tour_seen():
            self.start_tour()

    def closeEvent(self, event):
        """Ensure a clean executor shutdown when the dialog is closed."""
        if self._tour is not None:
            self._tour.tour.delete()
            self._tour = None
        if self._vrt_executor:
            self._vrt_cancelled = True
            try:
                self._vrt_executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                self._vrt_executor.shutdown(wait=False)
            self._vrt_executor = None
        super().closeEvent(event)

    _STATUS_LOG_THROTTLE_S = 2.0

    def _set_status(self, text, status_type="info"):
        """Update the status area with an icon and styled message, and mirror
        it into the persistent activity log (Log button/window).

        A long download or crop fires this every ~100ms with just the
        percentage changing; logging every one of those would flood the log
        with thousands of near-identical lines. Instead this always logs the
        first message of a new status_type (so every operation's start and
        outcome \u2014 success/warning/error \u2014 is captured) and otherwise logs at
        most once every _STATUS_LOG_THROTTLE_S seconds while status_type
        stays the same, giving a periodic heartbeat during long transfers.
        """
        _STYLES = {
            "info": ("\u2139", "#3498db"),
            "success": ("\u2714", "#2ecc71"),
            "warning": ("\u26a0", "#f39c12"),
            "error": ("\u2718", "#e74c3c"),
            "download": ("\u2b07", "#9b59b6"),
        }
        icon, color = _STYLES.get(status_type, _STYLES["info"])
        # While the BDC is unreachable every message says so, so the mode stays visible.
        if self._stac_online is False and not text.startswith("<b>Offline"):
            text = OFFLINE_PREFIX + text
        self._status_icon.setText(icon)
        self._status_icon.setStyleSheet(f"""
            QLabel {{
                color: {color};
                font-size: 14px;
                font-weight: bold;
                background: rgba(255, 255, 255, 0.1);
                border-radius: 10px;
            }}
        """)
        set_text(self.status_label, text)

        now = time.monotonic()
        last_type = getattr(self, "_last_logged_status_type", None)
        last_time = getattr(self, "_last_logged_status_time", 0.0)
        if status_type != last_type or (now - last_time) >= self._STATUS_LOG_THROTTLE_S:
            log_fn = {"error": _log_error, "warning": _log_warning}.get(status_type, _log_info)
            log_fn(text)
            self._last_logged_status_type = status_type
            self._last_logged_status_time = now

    def set_tooltip(self, widget, text, background_color=None):
        """Configure tooltip with a 2-second delay and optional background color."""
        widget.setToolTip(text)
        widget.setToolTipDuration(2000)
        if background_color:
            widget.setStyleSheet(
                widget.styleSheet()
                + f"""
                QToolTip {{
                    background-color: {background_color};
                    color: white;
                    border: 1px solid {background_color};
                    padding: 5px;
                    border-radius: 3px;
                }}
            """
            )

    def set_view_mode(self, compact):
        """Switch between detailed and compact result view modes."""
        self.compact_view = compact
        self.view_detailed_btn.setChecked(not compact)
        self.view_compact_btn.setChecked(compact)

        # Rebuild if results exist
        if self.found_items:
            self._rebuild_result_widgets()

    def _rebuild_result_widgets(self):
        """Rebuild result widgets with the current view mode."""
        # Save selection state
        selected_ids = {w.item.id for w in self.result_widgets if w.is_selected()}

        # Extract current collection_id and grid_type
        collection_id = self._current_collection_id
        grid_type = self._current_grid_type

        # Suspend layout updates while rebuilding
        self.results_container.setUpdatesEnabled(False)

        # Remove old widgets
        for widget in self.result_widgets:
            widget.setParent(None)
            widget.deleteLater()
        self.result_widgets.clear()

        # Recreate widgets
        for item in self.found_items:
            selected = item.id in selected_ids
            widget = ResultItemWidget(
                item, collection_id=collection_id, grid_type=grid_type, selected=selected, compact=self.compact_view
            )
            widget._download_callback = self._download_item
            widget.selectionChanged.connect(self._schedule_band_availability_update)
            self.result_widgets.append(widget)
            self.results_layout.insertWidget(self.results_layout.count() - 1, widget)
            cursors.apply_click_cursors(widget)

        self.results_container.setUpdatesEnabled(True)

        QTimer.singleShot(THUMBNAILS_AFTER_LAYOUT_MS, lambda: self._load_visible_thumbnails(preload_buffer=500))
        self._update_downloaded_status()

        # Reapply active filters
        self._apply_result_filters()

    def _on_scroll(self, value):
        """Lazy-load thumbnails as the user scrolls the result list (debounced)."""
        if self._generating_vrt:
            return
        if not hasattr(self, "_scroll_timer"):
            self._scroll_timer = QTimer()
            self._scroll_timer.setSingleShot(True)
            self._scroll_timer.timeout.connect(lambda: self._load_visible_thumbnails(preload_buffer=300))
        self._scroll_timer.start(150)

    def select_output_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Folder", self.output_dir.text())
        if dir_path:
            self.output_dir.setText(dir_path)

    def select_all_items(self):
        for widget in self.result_widgets:
            if widget.isVisible():
                widget.set_selected(True)
        self._sync_bands_with_selected_items()
        self._update_vrt_preview()

    def deselect_all_items(self):
        for widget in self.result_widgets:
            widget.set_selected(False)
        self._sync_bands_with_selected_items()
        self._update_vrt_preview()

    def show_about(self):
        """Shows the About dialog."""
        from .about_dialog import show_about_dialog

        show_about_dialog(parent=self)

    def _show_docs_dialog(self):
        """Shows the BDC documentation dialog with categorized links."""
        from .docs_dialog import show_docs_dialog

        show_docs_dialog(parent=self)

    def _apply_bdc_projection(self):
        """Set the QGIS project CRS to BDC Albers Equal-Area Conic."""
        apply_bdc_projection(self, self.iface)

    def _open_export_query_dialog(self):
        """Open the QueryExportDialog to export current UI query to code/formats."""
        from ..core.query_spec import build_ui_query_spec
        from .query_dialog import QueryExportDialog

        spec = build_ui_query_spec(self)
        dialog = QueryExportDialog(spec, parent=self)
        dialog.exec()

    def _open_import_query_dialog(self):
        """Open the QueryImportDialog to import JSON/YAML query parameters."""
        from ..core.query_spec import apply_ui_query_spec, build_ui_query_spec
        from .query_dialog import QueryImportDialog

        def _on_apply(spec_dict):
            apply_ui_query_spec(self, spec_dict)

        def _get_current():
            return build_ui_query_spec(self)

        dialog = QueryImportDialog(parent=self, on_apply_callback=_on_apply, get_current_spec_callback=_get_current)
        dialog.exec()
