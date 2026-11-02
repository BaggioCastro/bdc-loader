# -*- coding: utf-8 -*-
"""BDC Loader Plugin — Settings dialog (extracted from loader_dialog.py)."""

import os

from qgis.core import QgsSettings
from qgis.PyQt.QtCore import QTimer, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..i18n import TRANSLATE_ITEMS, tr
from ..timing import SETTINGS_DOWNLOADS_LIST_MS, SETTINGS_STORAGE_LIST_MS
from .settings_downloads import DownloadsTab
from .settings_storage import StorageTab
from .settings_widgets import (
    _SAVE_BUTTON_STYLE,
    _SECONDARY_BUTTON_STYLE,
    _add_toggle,
    _dialog_button,
    _scrollable,
    _spin_row,
)


class BDCSettingsDialog(DownloadsTab, StorageTab, QDialog):
    """Plugin settings dialog."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tutorial_requested = False
        self.setWindowTitle("Settings - BDC Loader")
        self.setModal(True)
        self.setMinimumSize(550, 480)
        self._load_settings()
        self.setup_ui()

    def _load_settings(self):
        """Load saved settings via QgsSettings."""
        settings = QgsSettings()
        self._vrt_dir = settings.value("bdc_loader/vrt_dir", os.path.expanduser("~/bdc_vrt/"), type=str)
        self._download_dir = settings.value("bdc_loader/download_dir", os.path.expanduser("~/bdc_downloads/"), type=str)
        self._generate_ovr = settings.value("bdc_loader/generate_ovr", True, type=bool)
        self._warn_non_cog = settings.value("bdc_loader/warn_non_cog", True, type=bool)
        self._layer_naming_format = settings.value("bdc_loader/layer_naming_format", "stac", type=str)
        # Storage warning thresholds (MB)
        self._threshold_vrt_mb = settings.value("bdc_loader/threshold_vrt_mb", 500, type=int)
        self._threshold_ovr_mb = settings.value("bdc_loader/threshold_ovr_mb", 1000, type=int)
        self._threshold_dl_mb = settings.value("bdc_loader/threshold_dl_mb", 5000, type=int)
        self._threshold_tmp_mb = settings.value("bdc_loader/threshold_tmp_mb", 100, type=int)

    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # Header
        header_label = QLabel("<b style='font-size: 14px;'>Settings</b>")
        layout.addWidget(header_label)

        # Tabs
        tabs = QTabWidget()
        tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #d0d7de; border-radius: 4px; padding: 8px; }
            QTabBar::tab { padding: 6px 16px; font-size: 11px; font-weight: bold; }
            QTabBar::tab:selected { background-color: #0969da; color: white; border-radius: 4px 4px 0 0; }
            QTabBar::tab:!selected { background-color: #f6f8fa; color: #24292f; }
            QTabBar::tab:hover:!selected { background-color: #eaeef2; }
        """)

        self._build_folders_tab(tabs)
        self._build_downloads_tab(tabs)
        self._build_performance_tab(tabs)
        self._build_storage_tab(tabs)
        self._storage_tabs = tabs  # keep reference for switching

        layout.addWidget(tabs, stretch=1)
        self._build_button_row(layout)
        self.setLayout(layout)
        self._fit_to_tabs(tabs)

        QTimer.singleShot(SETTINGS_DOWNLOADS_LIST_MS, self._refresh_downloads_list)
        QTimer.singleShot(SETTINGS_STORAGE_LIST_MS, self._refresh_storage_info)

    def _build_folders_tab(self, tabs):
        """Folders tab: VRT and download folders, overview and non-COG toggles, layer naming."""
        folders_tab = QWidget()
        folders_layout = QVBoxLayout(folders_tab)
        folders_layout.setSpacing(12)
        folders_layout.setContentsMargins(8, 12, 8, 8)

        self.vrt_dir_input = self._add_folder_group(
            folders_layout, "VRT Output Folder", self._vrt_dir, "Folder where VRTs will be saved"
        )
        self.download_dir_input = self._add_folder_group(
            folders_layout, "Image Download Folder", self._download_dir, "Folder where images will be downloaded"
        )
        self.generate_ovr_check = _add_toggle(
            folders_layout,
            "Generate overviews (.ovr) automatically",
            self._generate_ovr,
            "Overviews are reduced-resolution copies of remote VRTs that QGIS uses "
            "for fast rendering at zoom-out levels. Without them, QGIS must fetch "
            "full-resolution data from all remote tiles every time you pan or zoom, "
            "which can be very slow. Disabling this saves disk space but may degrade "
            "rendering performance for remote layers.",
        )
        self.warn_non_cog_check = _add_toggle(
            folders_layout,
            "Warn before loading collections that are not cloud-optimized",
            self._warn_non_cog,
            "Collections served as plain GeoTIFF have no internal overviews, so QGIS "
            "streams whole scenes to draw them and no overview or contrast stretch is "
            "generated. The warning offers to cancel and download instead. Dismissing "
            "it with 'Don't show this warning again' clears this box.",
        )
        folders_layout.addWidget(self._build_naming_group())

        info_label = QLabel(
            "<span style='color: #57606a; font-size: 10px;'>"
            "The VRT folder stores .vrt and .ovr files generated by the plugin.<br>"
            "The download folder stores COG images downloaded via the download button."
            "</span>"
        )
        info_label.setWordWrap(True)
        folders_layout.addWidget(info_label)
        folders_layout.addStretch()

        tabs.addTab(_scrollable(folders_tab), "Folders")

    def _add_folder_group(self, layout, title, path, placeholder):
        """Add a folder box (path field, browse and Open buttons) to `layout`; return the field."""
        group = QGroupBox(title)
        group.setStyleSheet("QGroupBox { font-weight: bold; font-size: 11px; }")
        group_layout = QHBoxLayout()
        group_layout.setContentsMargins(8, 8, 8, 8)
        path_input = QLineEdit(path)
        path_input.setPlaceholderText(placeholder)
        path_input.setStyleSheet("""
            QLineEdit { font-size: 11px; padding: 4px 8px; border: 1px solid #d0d7de; border-radius: 4px; }
            QLineEdit:focus { border-color: #1f6feb; }
        """)
        browse_btn = QPushButton("...")
        browse_btn.setFixedWidth(35)
        browse_btn.setStyleSheet("QPushButton { font-weight: bold; }")
        browse_btn.clicked.connect(lambda: self._browse_folder(path_input))
        open_btn = QPushButton("Open")
        open_btn.setStyleSheet("""
            QPushButton { background-color: #f6f8fa; border: 1px solid #d0d7de; border-radius: 4px; font-size: 10px; padding: 3px 10px; }
            QPushButton:hover { background-color: #eaeef2; }
        """)
        open_btn.clicked.connect(lambda: self._open_folder(path_input.text()))
        group_layout.addWidget(path_input)
        group_layout.addWidget(browse_btn)
        group_layout.addWidget(open_btn)
        group.setLayout(group_layout)
        layout.addWidget(group)
        return path_input

    def _build_naming_group(self):
        """Layer name format combo with a preview of the resulting name."""
        naming_group = QGroupBox("Layer Naming")
        naming_group.setStyleSheet("QGroupBox { font-weight: bold; font-size: 11px; }")
        naming_gl = QVBoxLayout()
        naming_gl.setContentsMargins(8, 8, 8, 8)
        naming_row = QHBoxLayout()
        naming_row.addWidget(QLabel("Format:"))
        self.layer_naming_combo = QComboBox()
        self.layer_naming_combo.addItem("STAC item ID", "stac")
        self.layer_naming_combo.addItem("Compact", "compact")
        self.layer_naming_combo.setProperty(TRANSLATE_ITEMS, True)
        self.layer_naming_combo.setStyleSheet("""
            QComboBox { font-size: 11px; padding: 4px 8px; border: 1px solid #d0d7de; border-radius: 4px; }
        """)
        idx = self.layer_naming_combo.findData(self._layer_naming_format)
        if idx >= 0:
            self.layer_naming_combo.setCurrentIndex(idx)
        naming_row.addWidget(self.layer_naming_combo, stretch=1)
        naming_gl.addLayout(naming_row)

        self.naming_preview = QLabel()
        self.naming_preview.setStyleSheet("""
            QLabel {
                border-left: 3px solid #d0d7de; padding: 2px 8px; margin-top: 2px;
                color: #57606a; font-family: monospace; font-size: 10px;
            }
        """)
        self.layer_naming_combo.currentIndexChanged.connect(self._update_naming_preview)
        self._update_naming_preview()
        naming_gl.addWidget(self.naming_preview)

        naming_group.setLayout(naming_gl)
        return naming_group

    def _build_performance_tab(self, tabs):
        """Performance tab: the profile choice and the detailed limits."""
        perf_tab = QWidget()
        perf_layout = QVBoxLayout(perf_tab)
        perf_layout.setSpacing(10)
        perf_layout.setContentsMargins(8, 12, 8, 8)

        from ..config import detect_system_profile, get_performance_config

        perf_layout.addWidget(self._build_profile_group(detect_system_profile()))
        perf_layout.addWidget(self._build_detail_group(get_performance_config()))

        self._perf_warning_label = QLabel("")
        self._perf_warning_label.setWordWrap(True)
        self._perf_warning_label.setStyleSheet("font-size: 10px;")
        perf_layout.addWidget(self._perf_warning_label)
        self._update_perf_warning()

        self.spin_max_threads.valueChanged.connect(self._update_perf_warning)
        self.spin_wtss_workers.valueChanged.connect(self._update_perf_warning)

        perf_layout.addStretch()
        tabs.addTab(_scrollable(perf_tab), "Performance")

    def _build_profile_group(self, detected_profile):
        """Profile combo (Auto, the fixed profiles, Custom) and the detected hardware."""
        from ..config import PERFORMANCE_PROFILES

        profile_group = QGroupBox("Performance Profile")
        profile_group.setStyleSheet("QGroupBox { font-weight: bold; font-size: 11px; }")
        profile_gl = QVBoxLayout()
        profile_gl.setContentsMargins(8, 8, 8, 8)
        profile_gl.setSpacing(6)

        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Profile:"))
        self.perf_profile_combo = QComboBox()
        self.perf_profile_combo.addItem(f"Auto ({PERFORMANCE_PROFILES[detected_profile]['label']})", "auto")
        for key, info in PERFORMANCE_PROFILES.items():
            self.perf_profile_combo.addItem(info["label"], key)
        self.perf_profile_combo.addItem("Custom", "custom")

        saved_profile = QgsSettings().value("bdc_loader/perf_profile", "auto", type=str)
        idx = self.perf_profile_combo.findData(saved_profile)
        if idx >= 0:
            self.perf_profile_combo.setCurrentIndex(idx)

        self.perf_profile_combo.setStyleSheet("""
            QComboBox { font-size: 11px; padding: 4px 8px; border: 1px solid #d0d7de; border-radius: 4px; }
        """)
        self.perf_profile_combo.currentIndexChanged.connect(self._on_perf_profile_changed)
        profile_row.addWidget(self.perf_profile_combo, stretch=1)
        profile_gl.addLayout(profile_row)

        detected_label = QLabel(
            f"<span style='color: #57606a; font-size: 10px;'>"
            f"Detected: {os.cpu_count() or '?'} CPU cores, "
            f"{self._format_ram()} RAM → profile <b>{detected_profile}</b></span>"
        )
        detected_label.setWordWrap(True)
        profile_gl.addWidget(detected_label)
        profile_group.setLayout(profile_gl)
        return profile_group

    def _build_detail_group(self, config):
        """One spin box per performance limit, each with its label and hint."""
        from ..config import PERF_LIMITS
        from ..core import download_engine
        from ..core.download import download_connections

        detail_group = QGroupBox("Detailed Settings")
        detail_group.setStyleSheet("QGroupBox { font-weight: bold; font-size: 11px; }")
        grid = QGridLayout()
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setSpacing(6)

        self.spin_max_threads = _spin_row(
            grid,
            0,
            "Max Threads:",
            PERF_LIMITS["max_threads"],
            config.get("max_threads", 16),
            "Files read at once for a time series taken from the COGs",
            "Time series from COGs: all bands and dates",
        )
        self.spin_wtss_workers = _spin_row(
            grid,
            1,
            "WTSS Workers:",
            PERF_LIMITS["wtss_workers"],
            config.get("wtss_workers", 3),
            "Parallel WTSS point queries",
            "Parallel WTSS extractions",
        )
        self.spin_gdal_cache = _spin_row(
            grid,
            2,
            "GDAL Cache (MB):",
            PERF_LIMITS["gdal_cache_mb"],
            config.get("gdal_cache_mb", 10),
            "Cache of the data read for a time series taken from the COGs",
            "VSI curl cache size",
        )
        self.spin_http_timeout = _spin_row(
            grid,
            3,
            "HTTP Timeout (s):",
            PERF_LIMITS["http_timeout"],
            config.get("http_timeout", 10),
            "Connection timeout when reading a time series from the COGs",
            "Increase on slow connections",
        )
        self.spin_download_connections = _spin_row(
            grid,
            4,
            "Download Connections:",
            (download_engine.MIN_WORKERS, download_engine.MAX_WORKERS_LIMIT),
            download_connections(),
            f"Simultaneous connections to the BDC server when downloading (default "
            f"{download_engine.DEFAULT_MAX_WORKERS}). More is faster on a fast network; if the server "
            "answers 'too many requests', the plugin lowers the number by itself for the rest of the session.",
            "Lowered automatically if the server refuses",
        )

        detail_group.setLayout(grid)
        return detail_group

    def _build_button_row(self, layout):
        """Show tutorial on the left; Restore Defaults, Cancel and Save on the right."""
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        tutorial_btn = _dialog_button("Show tutorial", _SECONDARY_BUTTON_STYLE, self._request_tutorial)
        tutorial_btn.setToolTip("Close Settings without saving and start the tutorial")
        buttons.addWidget(tutorial_btn)
        buttons.addStretch()
        buttons.addWidget(_dialog_button("Restore Defaults", _SECONDARY_BUTTON_STYLE, self._restore_defaults))
        buttons.addWidget(_dialog_button("Cancel", _SECONDARY_BUTTON_STYLE, self.reject, width=100))
        buttons.addWidget(_dialog_button("Save", _SAVE_BUTTON_STYLE, self._save_and_close, width=100))
        layout.addLayout(buttons)

    def _request_tutorial(self):
        self.tutorial_requested = True
        self.reject()

    def _fit_to_tabs(self, tabs):
        """Grow, once shown, to the tallest tab at its real width (within the screen)."""
        self._tabs_to_fit = tabs

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_tabs_to_fit", None) is not None:
            QTimer.singleShot(0, self._grow_to_fit_tabs)

    def _grow_to_fit_tabs(self):
        tabs, self._tabs_to_fit = self._tabs_to_fit, None
        if tabs is None:
            return
        try:
            from qgis.PyQt.QtWidgets import QApplication

            deficit = 0
            for index in range(tabs.count()):
                scroll = tabs.widget(index)
                page = scroll.widget()
                layout = page.layout()
                width = scroll.viewport().width()
                needed = layout.heightForWidth(width) if layout.hasHeightForWidth() else -1
                needed = max(needed, page.minimumSizeHint().height())
                deficit = max(deficit, needed - scroll.viewport().height())
            if deficit > 0:
                screen = (self.screen() or QApplication.primaryScreen()).availableGeometry()
                self.resize(self.width(), min(self.height() + deficit, int(screen.height() * 0.9)))
                # Growing pushes the bottom edge down; keep the buttons on screen.
                frame = self.frameGeometry()
                x = min(max(frame.left(), screen.left()), screen.right() - frame.width())
                y = min(max(frame.top(), screen.top()), screen.bottom() - frame.height())
                if (x, y) != (frame.left(), frame.top()):
                    self.move(max(x, screen.left()), max(y, screen.top()))
        except Exception:
            pass

    def _browse_folder(self, line_edit):
        current = line_edit.text()
        if not os.path.isdir(current):
            current = os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(self, "Select Folder", current)
        if folder:
            line_edit.setText(folder)

    def _open_folder(self, path):
        if os.path.isdir(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            QMessageBox.information(self, "Info", f"Folder does not exist: {path}")

    def _update_naming_preview(self):
        example = {
            "stac": "LT05_L2SP_228061_20081121_20200828_02_T1_red-green-blue",
            "compact": "landsat-2_228061_2008-11-21_red-green-blue",
        }[self.layer_naming_combo.currentData()]
        self.naming_preview.setText(f"{example}")

    def _format_ram(self):
        try:
            from ..config import _get_total_ram_gb

            gb = _get_total_ram_gb()
            if gb:
                return f"{gb:.1f} GB"
        except Exception:
            pass
        return "? GB"

    def _on_perf_profile_changed(self, _index):
        from ..config import PERFORMANCE_PROFILES, detect_system_profile

        profile_key = self.perf_profile_combo.currentData()
        if profile_key == "custom":
            return
        resolved = profile_key if profile_key != "auto" else detect_system_profile()
        if resolved in PERFORMANCE_PROFILES:
            p = PERFORMANCE_PROFILES[resolved]
            self.spin_max_threads.setValue(p["max_threads"])
            self.spin_wtss_workers.setValue(p["wtss_workers"])
            self.spin_gdal_cache.setValue(p["gdal_cache_mb"])
            self.spin_http_timeout.setValue(p["http_timeout"])
        self._update_perf_warning()

    def _update_perf_warning(self):
        threads = self.spin_max_threads.value()
        if threads > 24:
            self._perf_warning_label.setText(
                tr(
                    f"<span style='color: #cf222e;'>\u26a0 {threads} threads. "
                    f"High values may freeze QGIS on weaker machines.</span>"
                )
            )
        elif threads > 16:
            self._perf_warning_label.setText(
                tr(
                    f"<span style='color: #9a6700;'>\u26a1 {threads} threads. "
                    f"Moderate \u2014 should work on most machines.</span>"
                )
            )
        else:
            self._perf_warning_label.setText(
                tr(f"<span style='color: #1a7f37;'>\u2713 {threads} threads. Safe for most machines.</span>")
            )

    def _restore_defaults(self):
        self.vrt_dir_input.setText(os.path.expanduser("~/bdc_vrt/"))
        self.download_dir_input.setText(os.path.expanduser("~/bdc_downloads/"))
        self.generate_ovr_check.setChecked(True)
        self.warn_non_cog_check.setChecked(True)
        self.layer_naming_combo.setCurrentIndex(self.layer_naming_combo.findData("stac"))
        self.perf_profile_combo.setCurrentIndex(0)
        # Reset storage thresholds
        defaults = {"vrt": 500, "ovr": 1000, "downloads": 5000, "temp": 100}
        for key, val in defaults.items():
            self._storage_rows[key][2].setValue(val)

    def _save_and_close(self):
        settings = QgsSettings()
        settings.setValue("bdc_loader/vrt_dir", self.vrt_dir_input.text())
        settings.setValue("bdc_loader/download_dir", self.download_dir_input.text())
        settings.setValue("bdc_loader/generate_ovr", self.generate_ovr_check.isChecked())
        settings.setValue("bdc_loader/warn_non_cog", self.warn_non_cog_check.isChecked())
        settings.setValue("bdc_loader/layer_naming_format", self.layer_naming_combo.currentData())
        # Storage thresholds
        settings.setValue("bdc_loader/threshold_vrt_mb", self._storage_rows["vrt"][2].value())
        settings.setValue("bdc_loader/threshold_ovr_mb", self._storage_rows["ovr"][2].value())
        settings.setValue("bdc_loader/threshold_dl_mb", self._storage_rows["downloads"][2].value())
        settings.setValue("bdc_loader/threshold_tmp_mb", self._storage_rows["temp"][2].value())
        # Performance
        profile_key = self.perf_profile_combo.currentData()
        settings.setValue("bdc_loader/perf_profile", profile_key)
        settings.setValue("bdc_loader/perf_max_threads", self.spin_max_threads.value())
        settings.setValue("bdc_loader/perf_wtss_workers", self.spin_wtss_workers.value())
        settings.setValue("bdc_loader/perf_gdal_cache_mb", self.spin_gdal_cache.value())
        settings.setValue("bdc_loader/perf_http_timeout", self.spin_http_timeout.value())
        settings.setValue("bdc_loader/download_connections", self.spin_download_connections.value())
        self.accept()

    def get_vrt_dir(self):
        return self.vrt_dir_input.text()

    def get_download_dir(self):
        return self.download_dir_input.text()

    # ── Storage tab helpers ──────────────────────────────────────
