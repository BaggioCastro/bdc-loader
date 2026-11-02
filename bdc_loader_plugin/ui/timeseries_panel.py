# -*- coding: utf-8 -*-
"""
BDC Time Series Panel — pixel time-series extraction and visualization.

Structure
---------
This module provides a QDockWidget panel that allows the user to:

  1. Pick one or more points on the map canvas (PointPickerTool)
  2. Select collections and bands from the STAC catalog
  3. Extract time-series data via COG/VRT or the WTSS web service
  4. Plot interactive line charts and RGB composite previews
  5. Export results as CSV, GeoPackage, or vector layers

Key classes:
  - BDCTimeSeriesPanel   — the dock widget (public entry point)

The class is assembled via core modules:
  - TSCollectionManager  — STAC collection loading, filtering, combo population
  - TSBandManager        — band resolution, vegetation indices, RGB combo logic
  - TSPointManager       — map picker, coordinate input, vector file loading
  - TSLayerManager       — temporary point layer on the map canvas
  - TSHistoryManager     — extraction history list and settings
  - TSExtractionEngine   — STAC search & time-series extraction (WTSS + VRT)
  - TSVisualization      — chart dock, plotting, VRT loading, navigation, exports

Dependencies:
  - chart.dock.ChartDock — matplotlib-based charting panel
  - extraction.point_series / extraction.wtss_extractor — data backends
  - widgets.point_picker.PointPickerTool — coordinate capture on canvas
"""

import logging
import threading

_logger = logging.getLogger("bdc_loader")

from qgis.core import QgsApplication, QgsProject
from qgis.PyQt.QtCore import QSize, Qt, QTimer
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QDockWidget,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..core.ts_bands import TSBandManager
from ..core.ts_collections import TSCollectionManager
from ..core.ts_constants import _BandsResizeHandle
from ..core.ts_extraction import TSExtractionEngine
from ..core.ts_history import TSHistoryManager
from ..core.ts_layer import TSLayerManager
from ..core.ts_points import TSPointManager
from ..core.ts_visualization import TSVisualization
from ..extraction.wtss_extractor import WTSS_BASE
from ..timing import PANEL_WTSS_CHECK_MS
from ..vendored import ensure_pystac_client
from ..widgets.collection_badge import CollectionBadgeDelegate
from ..widgets.icons import copy_icon, crosshair_icon
from ..widgets.range_slider import TSRangeSlider
from ..widgets.sizing import fix_label_width_for_texts, fix_width_for_texts, keep_space_when_hidden

pystac_client = ensure_pystac_client()


_SHOW_CHART_BTN_STYLE = """
    QPushButton {
        background-color: #3498db; color: white;
        border: none; border-radius: 3px;
        padding: 1px 8px; font-size: 9px; font-weight: bold;
    }
    QPushButton:hover { background-color: #2980b9; }
    QPushButton:checked { background-color: #27ae60; }
"""
_FILTER_BTN_STYLE = """
    QPushButton {
        background-color: #3498db; color: white;
        border: none; border-radius: 3px;
        font-size: 12px; font-weight: bold;
    }
    QPushButton:hover { background-color: #2980b9; }
"""
_PTS_INFO_BTN_STYLE = """
    QPushButton {
        background: transparent; border: 1px solid #bdc3c7;
        border-radius: 9px; color: #3498db; font-weight: bold; font-size: 10px;
    }
    QPushButton:hover { background-color: #e8f4f8; border-color: #3498db; }
"""
_PICK_BTN_STYLE = """
    QPushButton {
        border: 1px solid #bdc3c7; border-radius: 3px;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #f8f9fa, stop:1 #e9ecef);
    }
    QPushButton:hover {
        border-color: #3498db;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #ffffff, stop:1 #eaf2f8);
    }
    QPushButton:checked {
        border: 2px solid #2980b9;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #d6eaf8, stop:1 #aed6f1);
    }
"""
_POINTS_LIST_STYLE = """
    QListWidget {
        font-size: 9px; border: 1px solid #ddd; border-radius: 3px;
        background-color: #fff;
    }
    QListWidget::item { border-bottom: 1px solid #f0f0f0; padding: 1px; }
    QListWidget::item:selected { background-color: #d6eaf8; }
    QListWidget::item:hover { background-color: #eaf2f8; }
"""
_LOAD_SHP_BTN_STYLE = """
    QPushButton {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #f8f9fa, stop:1 #e9ecef);
        border: 1px solid #bdc3c7; border-radius: 3px;
        font-size: 9px; font-weight: bold; color: #555; padding: 0 8px;
    }
    QPushButton:hover {
        border-color: #3498db; color: #2980b9;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #ffffff, stop:1 #f0f4f8);
    }
"""
_CLEAR_PTS_BTN_STYLE = """
    QPushButton {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #bdc3c7, stop:1 #95a5a6);
        color: white; border: none; border-radius: 3px;
        font-size: 10px; font-weight: bold; padding: 0 14px;
    }
    QPushButton:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #95a5a6, stop:1 #7f8c8d);
    }
"""
_EXTRACT_BTN_STYLE = """
    QPushButton {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #3498db, stop:1 #2980b9);
        color: white; border: none; border-radius: 3px;
        font-size: 10px; font-weight: bold; padding: 0 14px;
    }
    QPushButton:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2980b9, stop:1 #2471a3);
    }
    QPushButton:disabled { background-color: #bdc3c7; color: #ecf0f1; }
"""
_HIST_SETTINGS_BTN_STYLE = """
    QPushButton {
        background-color: transparent; border: none;
        font-size: 14px; color: #777;
    }
    QPushButton:hover { color: #333; }
"""
_CANCEL_BTN_STYLE = """
    QPushButton {
        background-color: #e74c3c; color: white; border: none; border-radius: 3px; font-size: 9px; font-weight: bold; padding: 0 8px;
    }
    QPushButton:hover { background-color: #c0392b; }
"""


class BDCTimeSeriesPanel(
    TSCollectionManager,
    TSBandManager,
    TSPointManager,
    TSLayerManager,
    TSHistoryManager,
    TSExtractionEngine,
    TSVisualization,
    QDockWidget,
):
    """Time series dock panel."""

    def __init__(self, iface_ref, parent=None):
        super().__init__("", parent)
        self.iface = iface_ref
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)

        self._stac_client = None
        self._collections = {}
        self._band_info = {}
        self._visible_ids = set()
        self._current_points = []
        self._picker_tool = None
        self._previous_tool = None
        self._multi_point_mode = False
        self._history = []
        self._history_counter = 0
        self._current_viz_index = -1
        self._auto_center = False
        self._temp_layer = None

        self._hist_settings = {
            "point_size": 2.8,
            "point_color": "#e74c3c",
            "color_mode": "single",
            "visible": True,
            "show_labels": False,
            "vrt_mode": "rgb",
            "vrt_r_band": "",
            "vrt_g_band": "",
            "vrt_b_band": "",
            "vrt_single_band": "",
        }

        self.chart_dock = None
        self._cancel_extraction = threading.Event()
        self._rgb_bands_downloading = False
        self._rgb_fetch_active = None
        self._rgb_fetch_pending = None
        # Item lists of searched points, so a band added later needs no new search.
        self._point_items_cache = {}
        self._wtss_ping_running = False
        self._chart_vrt_running = False
        self._chart_vrt_pending = None
        self._ts_closing = False
        self._project_signals_connected = False

        self._setup_ui()
        self._load_collections_from_plugin()
        self._connect_project_signals()

    def _connect_project_signals(self):
        if self._project_signals_connected:
            return
        try:
            QgsProject.instance().layerRemoved.connect(self._on_layer_removed)
            QgsProject.instance().layersAdded.connect(self._on_layers_added)
            self._project_signals_connected = True
        except Exception as _e:
            _logger.debug("Failed to connect QGIS project signals: %s", _e)

    def _disconnect_project_signals(self):
        if not self._project_signals_connected:
            return
        self._project_signals_connected = False
        for signal, slot in (
            (QgsProject.instance().layerRemoved, self._on_layer_removed),
            (QgsProject.instance().layersAdded, self._on_layers_added),
        ):
            try:
                signal.disconnect(slot)
            except Exception as _e:
                _logger.debug("Failed to disconnect QGIS project signal: %s", _e)

    def showEvent(self, event):
        # The dock's close button only hides the panel; reopening it must resume
        # the async callbacks and project signals that closeEvent stopped.
        self._ts_closing = False
        self._connect_project_signals()
        super().showEvent(event)

    # What the tutorial reads and does on the panel.
    def history_entries(self):
        return list(self._history)

    def current_entry(self):
        """The history entry on the chart, or None."""
        if 0 <= self._current_viz_index < len(self._history):
            return self._history[self._current_viz_index]
        return None

    def picked_points(self):
        """[(lon, lat, label)] waiting to be extracted."""
        return list(self._current_points)

    def rgb_bands_pending(self):
        """Whether the bands of the RGB chart are still being downloaded."""
        return self._rgb_bands_downloading

    def check_bands(self, bands):
        for checkbox in self._band_checkboxes:
            checkbox.setChecked(checkbox.property("band_name") in bands)

    def open_chart(self):
        self._ensure_chart_dock()

    def clear_points(self):
        self._clear_points()

    def _setup_ui(self):
        main_widget = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(2)

        self._build_header(main_layout)
        QTimer.singleShot(PANEL_WTSS_CHECK_MS, self._check_wtss_status)

        # Scrollable content area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")
        scroll_content = QWidget()
        scroll_lay = QVBoxLayout(scroll_content)
        scroll_lay.setSpacing(4)
        scroll_lay.setContentsMargins(2, 2, 2, 2)

        self._build_collection_section(scroll_lay)
        self._build_period_section(scroll_lay)
        self._build_bands_section(scroll_lay)
        self._build_points_section(scroll_lay)
        self._build_history_section(scroll_lay)
        scroll_lay.addStretch()
        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll, stretch=1)

        self._build_progress_row(main_layout)
        self._build_status_label(main_layout)
        main_widget.setLayout(main_layout)
        self.setWidget(main_widget)
        self.setMinimumWidth(180)

    def _build_header(self, main_layout):
        """Dark title bar with the Chart button and the WTSS status indicator."""
        header = QWidget()
        header.setStyleSheet("background-color: #2c3e50; padding: 2px;")
        header.setFixedHeight(28)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 2, 8, 2)

        title_lbl = QLabel("BDC Satellite Image Time Series")
        title_lbl.setStyleSheet("color: white; font-weight: bold; font-size: 11px;")
        header_layout.addWidget(title_lbl)
        header_layout.addStretch()

        self.show_chart_btn = QPushButton("Chart")
        self.show_chart_btn.setFixedHeight(20)
        self.show_chart_btn.setCheckable(True)
        self.show_chart_btn.setChecked(False)
        self.show_chart_btn.setStyleSheet(_SHOW_CHART_BTN_STYLE)
        self.show_chart_btn.clicked.connect(self._toggle_chart_dock)
        header_layout.addWidget(self.show_chart_btn)

        # WTSS status indicator
        _sep = QFrame()
        _sep.setFrameShape(QFrame.Shape.VLine)
        _sep.setStyleSheet("color: rgba(255,255,255,40);")
        _sep.setFixedHeight(16)
        header_layout.addWidget(_sep)

        self._wtss_container = QWidget()
        self._wtss_container.setCursor(Qt.CursorShape.PointingHandCursor)
        self._wtss_container.setToolTip("Click to open WTSS in browser")
        self._wtss_container.setStyleSheet(
            "QWidget:hover { background-color: rgba(255,255,255,25); border-radius: 4px; }"
        )
        self._wtss_status_url = f"{WTSS_BASE}/v4/list_coverages"
        self._wtss_container.mousePressEvent = self._on_wtss_status_clicked
        wtss_row = QHBoxLayout(self._wtss_container)
        wtss_row.setContentsMargins(3, 0, 3, 0)
        wtss_row.setSpacing(4)

        self._wtss_dot = QLabel()
        self._wtss_dot.setFixedSize(9, 9)
        self._wtss_dot.setStyleSheet("background-color: #95a5a6; border-radius: 4px;")
        self._wtss_dot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        wtss_row.addWidget(self._wtss_dot)

        self._wtss_lbl = QLabel("<span style='color:#bdc3c7;font-size:9px;'>WTSS: ...</span>")
        self._wtss_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        fix_label_width_for_texts(self._wtss_lbl, ("WTSS: 99999ms", "WTSS: offline", "WTSS: ..."), 9)
        wtss_row.addWidget(self._wtss_lbl)

        header_layout.addWidget(self._wtss_container)

        main_layout.addWidget(header)

    def _build_collection_section(self, scroll_lay):
        """Collection section: type radio buttons, collection combo, filter button and info line."""
        coll_frame = self._create_section("Collection")
        coll_lay = coll_frame.layout()

        type_row = QGridLayout()
        type_row.setHorizontalSpacing(6)
        type_row.setVerticalSpacing(2)
        type_lbl = QLabel("Type:")
        type_lbl.setStyleSheet("border:none; background:transparent; font-size:9px; color:#666; font-weight:bold;")
        type_row.addWidget(type_lbl, 0, 0)

        _radio_style = """
            QRadioButton { font-size: 9px; color: #444; }
            QRadioButton::indicator { width: 10px; height: 10px; }
        """
        self._coll_type_group = QButtonGroup()
        self._type_all_btn = QRadioButton("All")
        self._type_all_btn.setStyleSheet(_radio_style)
        self._type_all_btn.setChecked(True)
        self._type_cube_btn = QRadioButton("Cubes")
        self._type_cube_btn.setStyleSheet(_radio_style)
        self._type_coll_btn = QRadioButton("Collections")
        self._type_coll_btn.setStyleSheet(_radio_style)
        self._coll_type_group.addButton(self._type_all_btn, 0)
        self._coll_type_group.addButton(self._type_cube_btn, 1)
        self._coll_type_group.addButton(self._type_coll_btn, 2)
        self._type_all_btn.toggled.connect(self._filter_ts_collections)
        self._type_cube_btn.toggled.connect(self._filter_ts_collections)
        self._type_coll_btn.toggled.connect(self._filter_ts_collections)
        type_row.addWidget(self._type_all_btn, 0, 1)
        type_row.addWidget(self._type_cube_btn, 0, 2)
        type_row.addWidget(self._type_coll_btn, 0, 3)
        type_row.setColumnStretch(4, 1)
        coll_lay.addLayout(type_row)

        coll_row = QHBoxLayout()
        coll_row.setSpacing(2)
        self.ts_collection_combo = QComboBox()
        self.ts_collection_combo.setToolTip("Select BDC collection")
        self.ts_collection_combo.setStyleSheet("font-size: 10px;")
        self.ts_collection_combo.setMinimumWidth(50)
        self.ts_collection_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.ts_collection_combo.setItemDelegate(CollectionBadgeDelegate(self.ts_collection_combo))
        self.ts_collection_combo.currentIndexChanged.connect(self._on_collection_changed)

        coll_row.addWidget(self.ts_collection_combo, stretch=1)

        self.filter_btn = QPushButton("\u2630")
        self.filter_btn.setFixedSize(24, 22)
        self.filter_btn.setToolTip("Filter visible collections")
        self.filter_btn.setStyleSheet(_FILTER_BTN_STYLE)
        self.filter_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.filter_btn.clicked.connect(self._show_collection_filter)
        coll_row.addWidget(self.filter_btn)
        coll_lay.addLayout(coll_row)

        self.ts_collection_info = QLabel("")
        self.ts_collection_info.setStyleSheet(
            "font-size: 9px; color: #666; padding: 1px; border: none; background: transparent;"
        )
        self.ts_collection_info.setWordWrap(True)
        coll_lay.addWidget(self.ts_collection_info)
        scroll_lay.addWidget(coll_frame)

    def _build_period_section(self, scroll_lay):
        """Period section: the date range slider."""
        period_frame = self._create_section("Period")
        period_lay = period_frame.layout()
        self.range_slider = TSRangeSlider()
        period_lay.addWidget(self.range_slider)
        scroll_lay.addWidget(period_frame)

    def _build_bands_section(self, scroll_lay):
        """Bands section: filter field, All/None buttons and the resizable band grid."""
        bands_frame = QFrame()
        bands_frame.setFrameShape(QFrame.Shape.StyledPanel)
        bands_frame.setStyleSheet("QFrame { border: 1px solid #ddd; border-radius: 3px; background-color: #fafafa; }")
        bands_bar_lay = QVBoxLayout(bands_frame)
        bands_bar_lay.setContentsMargins(5, 3, 5, 3)
        bands_bar_lay.setSpacing(2)

        bands_top_row = QHBoxLayout()
        bands_top_row.setSpacing(3)
        bands_lbl = QLabel("Bands")
        bands_lbl.setStyleSheet("font-weight: bold; font-size: 10px; border: none; background: transparent;")
        bands_top_row.addWidget(bands_lbl)

        self._band_filter_input = QLineEdit()
        self._band_filter_input.setPlaceholderText("Filter...")
        self._band_filter_input.setFixedHeight(20)
        self._band_filter_input.setStyleSheet(
            "font-size: 9px; border: 1px solid #ccc; border-radius: 3px; padding: 1px 4px;"
        )
        self._band_filter_input.textChanged.connect(self._filter_bands)
        bands_top_row.addWidget(self._band_filter_input, stretch=1)

        self._band_filter_clear_btn = QPushButton("\u2715")
        self._band_filter_clear_btn.setFixedSize(18, 18)
        self._band_filter_clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._band_filter_clear_btn.setStyleSheet("""
            QPushButton { background: transparent; border: none; color: #999; font-size: 10px; font-weight: bold; }
            QPushButton:hover { color: #e74c3c; }
        """)
        self._band_filter_clear_btn.clicked.connect(lambda: self._band_filter_input.clear())
        bands_top_row.addWidget(self._band_filter_clear_btn)

        _band_btn_style = """
            QPushButton {
                background-color: #ecf0f1; color: #2c3e50;
                border: 1px solid #bdc3c7; border-radius: 3px;
                font-size: 9px; font-weight: bold; padding: 1px 8px;
            }
            QPushButton:hover { background-color: #d5dbdb; border-color: #95a5a6; }
            QPushButton:pressed { background-color: #bdc3c7; }
        """
        self.select_all_bands_btn = QPushButton("All")
        self.select_all_bands_btn.setFixedHeight(18)
        self.select_all_bands_btn.setStyleSheet(_band_btn_style)
        self.select_all_bands_btn.clicked.connect(lambda: self._set_all_bands(True))
        self.deselect_all_bands_btn = QPushButton("None")
        self.deselect_all_bands_btn.setFixedHeight(18)
        self.deselect_all_bands_btn.setStyleSheet(_band_btn_style)
        self.deselect_all_bands_btn.clicked.connect(lambda: self._set_all_bands(False))
        bands_top_row.addWidget(self.select_all_bands_btn)
        bands_top_row.addWidget(self.deselect_all_bands_btn)
        bands_bar_lay.addLayout(bands_top_row)

        self._bands_scroll = QScrollArea()
        self._bands_scroll.setWidgetResizable(True)
        self._bands_scroll.setFixedHeight(140)
        self._bands_scroll.setMinimumHeight(50)
        self._bands_scroll.setStyleSheet("QScrollArea { border: none; }")
        self._bands_grid_widget = QWidget()
        self._bands_grid_layout = QGridLayout(self._bands_grid_widget)
        self._bands_grid_layout.setContentsMargins(0, 0, 0, 0)
        self._bands_grid_layout.setSpacing(2)
        self._band_checkboxes = []
        self._bands_scroll.setWidget(self._bands_grid_widget)
        bands_bar_lay.addWidget(self._bands_scroll)

        self._bands_resize_handle = _BandsResizeHandle(self._bands_scroll, bands_frame)
        bands_bar_lay.addWidget(self._bands_resize_handle)
        scroll_lay.addWidget(bands_frame)

    def _build_points_section(self, scroll_lay):
        """Points section: map picking, coordinates, WKT, point list, file import and Extract."""
        points_frame = QFrame()
        points_frame.setFrameShape(QFrame.Shape.StyledPanel)
        points_frame.setStyleSheet("QFrame { border: 1px solid #ddd; border-radius: 3px; background-color: #fafafa; }")
        pts_lay = QVBoxLayout(points_frame)
        pts_lay.setContentsMargins(5, 4, 5, 4)
        pts_lay.setSpacing(3)

        pts_title_row = QHBoxLayout()
        pts_title_lbl = QLabel("Points")
        pts_title_lbl.setStyleSheet("font-weight: bold; font-size: 10px; border: none; background: transparent;")
        pts_title_row.addWidget(pts_title_lbl)
        pts_title_row.addStretch()
        self._pts_info_btn = QPushButton("\u2139")
        self._pts_info_btn.setFixedSize(18, 18)
        self._pts_info_btn.setToolTip("How to add points")
        self._pts_info_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pts_info_btn.setStyleSheet(_PTS_INFO_BTN_STYLE)
        self._pts_info_btn.clicked.connect(self._show_points_help)
        pts_title_row.addWidget(self._pts_info_btn)
        pts_lay.addLayout(pts_title_row)

        self._build_pick_row(pts_lay)
        self._build_coordinate_row(pts_lay)
        self._build_wkt_row(pts_lay)
        self._build_points_list(pts_lay)
        self._build_file_import_row(pts_lay)
        self._build_point_actions(pts_lay)
        scroll_lay.addWidget(points_frame)

    def _build_pick_row(self, pts_lay):
        """Pick-on-map button and the Single/Multi point mode toggle."""
        row0 = QHBoxLayout()
        row0.setSpacing(4)

        self.pick_btn = QPushButton()
        self.pick_btn.setFixedSize(30, 28)
        self.pick_btn.setCheckable(True)
        self.pick_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pick_btn.setToolTip("Click map to select pixel (ESC to cancel)")
        _pick_icon = None
        try:
            _pick_icon = QgsApplication.getThemeIcon("/mActionCapturePoint.svg")
            if _pick_icon.isNull():
                _pick_icon = QgsApplication.getThemeIcon("/mCrossHair.svg")
        except Exception as _e:
            _logger.debug("Failed to load pick button icon: %s", _e)
        # The QGIS theme icons can be missing from minimal installs; fall back to a drawn icon.
        if _pick_icon is None or _pick_icon.pixmap(16, 16).isNull():
            _pick_icon = crosshair_icon()
        self.pick_btn.setIcon(_pick_icon)
        self.pick_btn.setStyleSheet(_PICK_BTN_STYLE)
        self.pick_btn.clicked.connect(self._toggle_picker)
        row0.addWidget(self.pick_btn)

        _mode_checked = """
            QPushButton {
                font-size: 11px; font-weight: bold; border: none;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                            stop:0 #3498db, stop:1 #2980b9);
                color: white; border-radius: 4px; padding: 3px 10px;
            }
        """
        _mode_unchecked = """
            QPushButton {
                font-size: 11px; font-weight: bold;
                border: 1px solid #bdc3c7;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                            stop:0 #f8f9fa, stop:1 #e9ecef);
                color: #555; border-radius: 4px; padding: 3px 10px;
            }
            QPushButton:hover {
                border-color: #3498db; color: #2980b9;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                            stop:0 #ffffff, stop:1 #f0f4f8);
            }
        """
        self._mode_checked_ss = _mode_checked
        self._mode_unchecked_ss = _mode_unchecked
        self.point_mode_group = QButtonGroup()
        self.single_point_btn = QPushButton("Single")
        self.single_point_btn.setFixedHeight(22)
        self.single_point_btn.setCheckable(True)
        self.single_point_btn.setChecked(True)
        self.single_point_btn.setToolTip("Click map \u2192 auto-extract for 1 point")
        self.single_point_btn.setStyleSheet(_mode_checked)
        self.multi_point_btn = QPushButton("Multi")
        self.multi_point_btn.setFixedHeight(22)
        self.multi_point_btn.setCheckable(True)
        self.multi_point_btn.setToolTip("Pick multiple points, then Extract")
        self.multi_point_btn.setStyleSheet(_mode_unchecked)
        self.point_mode_group.addButton(self.single_point_btn, 1)
        self.point_mode_group.addButton(self.multi_point_btn, 0)
        self.point_mode_group.setExclusive(True)
        self.multi_point_btn.toggled.connect(self._on_point_mode_changed)

        row0.addWidget(self.single_point_btn)
        row0.addWidget(self.multi_point_btn)
        row0.addStretch()
        pts_lay.addLayout(row0)

    def _build_coordinate_row(self, pts_lay):
        """Longitude and latitude fields with the add and copy buttons."""
        coord_row = QHBoxLayout()
        coord_row.setSpacing(2)
        self.lon_input = QLineEdit()
        self.lon_input.setPlaceholderText("Lon")
        self.lon_input.setStyleSheet("font-size: 10px; border: 1px solid #ddd; border-radius: 3px; padding: 2px 4px;")
        self.lon_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        coord_row.addWidget(self.lon_input)

        self.lat_input = QLineEdit()
        self.lat_input.setPlaceholderText("Lat")
        self.lat_input.setStyleSheet("font-size: 10px; border: 1px solid #ddd; border-radius: 3px; padding: 2px 4px;")
        self.lat_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        coord_row.addWidget(self.lat_input)

        add_coord_btn = QPushButton("+")
        add_coord_btn.setFixedSize(22, 22)
        add_coord_btn.setToolTip("Add point")
        add_coord_btn.setStyleSheet("""
            QPushButton { background-color: #3498db; color: white; border: none; border-radius: 3px; font-weight: bold; font-size: 11px; }
            QPushButton:hover { background-color: #2980b9; }
        """)
        add_coord_btn.clicked.connect(self._add_point_from_coords)
        coord_row.addWidget(add_coord_btn)

        self.copy_coord_btn = QPushButton()
        self.copy_coord_btn.setIcon(copy_icon("#ffffff"))
        self.copy_coord_btn.setIconSize(QSize(13, 13))
        self.copy_coord_btn.setFixedSize(22, 22)
        self.copy_coord_btn.setToolTip("Copy coordinates")
        self.copy_coord_btn.setStyleSheet("""
            QPushButton { background-color: #95a5a6; color: white; border: none; border-radius: 3px; font-size: 11px; }
            QPushButton:hover { background-color: #7f8c8d; }
        """)
        self.copy_coord_btn.clicked.connect(self._copy_coords)
        coord_row.addWidget(self.copy_coord_btn)
        pts_lay.addLayout(coord_row)

    def _build_wkt_row(self, pts_lay):
        """WKT field with its add button."""
        import_row = QHBoxLayout()
        import_row.setSpacing(2)
        self.wkt_input = QLineEdit()
        self.wkt_input.setPlaceholderText("POINT(-47.9 -15.8)")
        self.wkt_input.setStyleSheet("font-size: 9px; border: 1px solid #ddd; border-radius: 3px; padding: 2px 4px;")
        self.wkt_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        import_row.addWidget(self.wkt_input, stretch=1)

        add_wkt_btn = QPushButton("WKT")
        add_wkt_btn.setFixedHeight(22)
        add_wkt_btn.setMinimumWidth(44)
        add_wkt_btn.setStyleSheet("""
            QPushButton { background-color: #7f8c8d; color: white; border: none; border-radius: 3px; font-size: 10px; font-weight: bold; padding: 0 10px; }
            QPushButton:hover { background-color: #636e72; }
        """)
        add_wkt_btn.clicked.connect(self._add_point_from_wkt)
        import_row.addWidget(add_wkt_btn)
        pts_lay.addLayout(import_row)

    def _build_points_list(self, pts_lay):
        """List of the points to extract."""
        self.points_list = QListWidget()
        self.points_list.setMaximumHeight(80)
        self.points_list.setMinimumHeight(40)
        self.points_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.points_list.setStyleSheet(_POINTS_LIST_STYLE)
        self.points_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.points_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.points_list.customContextMenuRequested.connect(self._points_context_menu)
        self.points_list.itemDoubleClicked.connect(self._on_point_double_clicked)
        self.points_list.installEventFilter(self)
        pts_lay.addWidget(self.points_list)

    def _build_file_import_row(self, pts_lay):
        """Button that imports points from a SHP or GPKG file."""
        file_import_row = QHBoxLayout()
        file_import_row.setSpacing(2)
        load_shp_btn = QPushButton("SHP / GPKG")
        load_shp_btn.setFixedHeight(22)
        load_shp_btn.setToolTip("Load points from SHP or GPKG file")
        load_shp_btn.setStyleSheet(_LOAD_SHP_BTN_STYLE)
        load_shp_btn.clicked.connect(self._load_vector)
        file_import_row.addWidget(load_shp_btn)
        file_import_row.addStretch()
        pts_lay.addLayout(file_import_row)

    def _build_point_actions(self, pts_lay):
        """Clear and Extract buttons."""
        btn_action_lay = QHBoxLayout()
        btn_action_lay.setSpacing(4)

        self.clear_pts_btn = QPushButton("Clear")
        self.clear_pts_btn.setFixedHeight(26)
        self.clear_pts_btn.setStyleSheet(_CLEAR_PTS_BTN_STYLE)
        self.clear_pts_btn.clicked.connect(self._clear_points)
        btn_action_lay.addWidget(self.clear_pts_btn)

        btn_action_lay.addStretch()

        self.extract_btn = QPushButton(" Extract")
        self.extract_btn.setFixedHeight(26)
        # QGIS's own temporal icon, present from QGIS 3.22 to 4.x.
        self.extract_btn.setIcon(QgsApplication.getThemeIcon("/propertyicons/temporal.svg"))
        self.extract_btn.setStyleSheet(_EXTRACT_BTN_STYLE)
        self.extract_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.extract_btn.clicked.connect(self._extract_time_series)
        btn_action_lay.addWidget(self.extract_btn)
        pts_lay.addLayout(btn_action_lay)

    def _build_history_section(self, scroll_lay):
        """History section: extracted series list with its settings and Clear buttons."""
        hist_frame = QFrame()
        hist_frame.setFrameShape(QFrame.Shape.StyledPanel)
        hist_frame.setStyleSheet("QFrame { border: 1px solid #ddd; border-radius: 3px; background-color: #fafafa; }")
        hist_inner = QVBoxLayout(hist_frame)
        hist_inner.setContentsMargins(5, 4, 5, 4)
        hist_inner.setSpacing(3)

        hist_title_row = QHBoxLayout()
        hist_lbl = QLabel("History")
        hist_lbl.setStyleSheet("font-weight: bold; font-size: 10px; border: none; background: transparent;")
        hist_title_row.addWidget(hist_lbl)
        hist_title_row.addStretch()
        self.hist_settings_btn = QPushButton("\u2699")
        self.hist_settings_btn.setFixedSize(22, 22)
        self.hist_settings_btn.setToolTip("Map point settings")
        self.hist_settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hist_settings_btn.setStyleSheet(_HIST_SETTINGS_BTN_STYLE)
        self.hist_settings_btn.clicked.connect(self._show_history_settings)
        hist_title_row.addWidget(self.hist_settings_btn)
        hist_inner.addLayout(hist_title_row)

        self.history_list = QListWidget()
        self.history_list.setMaximumHeight(120)
        self.history_list.setStyleSheet("font-size: 9px;")
        self.history_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.history_list.currentRowChanged.connect(self._on_history_selected)
        self.history_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_list.customContextMenuRequested.connect(self._history_context_menu)
        hist_inner.addWidget(self.history_list)

        hist_btn_row = QHBoxLayout()
        self.clear_hist_btn = QPushButton("Clear History")
        self.clear_hist_btn.setFixedHeight(20)
        self.clear_hist_btn.setStyleSheet("font-size: 9px;")
        self.clear_hist_btn.clicked.connect(self._clear_history)
        hist_btn_row.addWidget(self.clear_hist_btn)
        hist_btn_row.addStretch()
        hist_inner.addLayout(hist_btn_row)
        scroll_lay.addWidget(hist_frame)

    def _build_progress_row(self, main_layout):
        """Progress bar with the Cancel button, hidden until an extraction runs."""
        self.progress_container = QWidget()
        prog_lay = QVBoxLayout(self.progress_container)
        prog_lay.setContentsMargins(4, 4, 4, 4)
        prog_lay.setSpacing(4)

        bar_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(12)
        self.progress_bar.setStyleSheet("""
            QProgressBar { border: 1px solid #bdc3c7; border-radius: 4px; text-align: center; font-size: 9px; }
            QProgressBar::chunk { background-color: #27ae60; border-radius: 3px; }
        """)
        self.progress_bar.setTextVisible(True)
        bar_row.addWidget(self.progress_bar, stretch=1)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFixedHeight(16)
        self.cancel_btn.setStyleSheet(_CANCEL_BTN_STYLE)
        self.cancel_btn.clicked.connect(self._on_cancel_extraction)
        bar_row.addWidget(self.cancel_btn)
        fix_width_for_texts(self.cancel_btn, ("Cancel", "Cancelling..."))

        prog_lay.addLayout(bar_row)
        keep_space_when_hidden(self.progress_container)
        self.progress_container.setVisible(False)
        main_layout.addWidget(self.progress_container)

    def _build_status_label(self, main_layout):
        """Status line at the bottom of the panel."""
        self.status_label = QLabel("")
        self.status_label.setFixedHeight(18)
        self.status_label.setStyleSheet(
            "font-size: 9px; color: #7f8c8d; font-weight: bold; "
            "background-color: #ecf0f1; border: 1px solid #ddd; "
            "border-radius: 3px; padding: 1px 6px;"
        )
        self.status_label.setWordWrap(True)
        main_layout.addWidget(self.status_label)

    def _create_section(self, title):
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setStyleSheet("QFrame { border: 1px solid #ddd; border-radius: 3px; background-color: #fafafa; }")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(5, 4, 5, 4)
        layout.setSpacing(3)
        lbl = QLabel(title)
        lbl.setStyleSheet("font-weight: bold; font-size: 10px; border: none; background: transparent;")
        layout.addWidget(lbl)
        return frame

    def closeEvent(self, event):
        self._ts_closing = True
        self._cancel_extraction.set()
        self._rgb_fetch_active = None
        self._rgb_fetch_pending = None
        self._chart_vrt_pending = None
        if self._picker_tool:
            self._picker_tool.cancel("close")
            self._picker_tool = None
        if self.chart_dock:
            self.chart_dock.close()
        self._disconnect_project_signals()
        super().closeEvent(event)
