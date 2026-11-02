"""Widgets of the main window, one method per section.

Header, left panel with the search inputs, right panel with the results and
the footer, with the stylesheets they use.
"""

import os

from qgis.core import (
    QgsSettings,
)
from qgis.gui import (
    QgsCollapsibleGroupBox,
)
from qgis.PyQt.QtCore import QSize, Qt
from qgis.PyQt.QtGui import QPixmap
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
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
    QSpinBox,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..config import PLUGIN_VERSION
from ..i18n import both, language, set_text
from ..widgets.collection_badge import CollectionBadgeDelegate
from ..widgets.extent_group import ExtentGroup
from ..widgets.group_title import hand_cursor_on_title
from ..widgets.icons import copy_icon, download_icon, flag_icon, plus_icon, trash_icon, zoom_icon
from ..widgets.range_slider import JumpSlider, RangeSlider
from ..widgets.sizing import (
    FixedLinesLabel,
    fix_label_width_for_texts,
    fix_width_for_texts,
    keep_scroll_min_width,
    keep_space_when_hidden,
)
from .main_styles import (
    _ABOUT_BTN_STYLE,
    _BDC_PROJ_BUTTON_STYLE,
    _CANCEL_DOWNLOAD_BTN_STYLE,
    _CLEAR_BTN_STYLE,
    _CLOUD_SLIDER_STYLE,
    _CLOUD_SPIN_STYLE,
    _COLL_FILTER_BTN_STYLE,
    _CONFIG_BTN_STYLE,
    _DISABLED_GROUP_STYLE,
    _DOCS_BUTTON_STYLE,
    _DOWNLOAD_SELECTED_BTN_STYLE,
    _EXPORT_QUERY_BTN_STYLE,
    _IMPORT_QUERY_BTN_BAR_STYLE,
    _LOAD_BTN_STYLE,
    _PROGRESS_BAR_STYLE,
    _RESET_BUTTON_STYLE,
    _SEARCH_BTN_STYLE,
    _STATUS_FRAME_STYLE,
    _STATUS_ICON_STYLE,
    _STATUS_LABEL_STYLE,
    _TILE_FILTER_BUTTON_STYLE,
)

_FLAG_BUTTON_STYLE = (
    "QToolButton { border: 1px solid transparent; border-radius: 4px; background: transparent; padding: 0; } "
    "QToolButton:hover { border-color: rgba(255, 255, 255, 90); } "
    "QToolButton:checked { border-color: #ffffff; background: rgba(255, 255, 255, 40); }"
)


def _labelled_switch(text, switch):
    """White header label followed by its switch button, as one widget."""
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    label = QLabel(text)
    label.setStyleSheet("font-size: 9px; font-weight: bold; color: white;")
    fix_label_width_for_texts(label, both(text), 9)
    # The width fits the longer of the two languages; the text stays next to its switch.
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    layout.addWidget(label)
    layout.addWidget(switch)
    return container


class MainDialogLayout:
    """Widgets of the main window: header, left panel with the search inputs, right panel with the results, and the footer. Each section is built by its own method."""

    def setup_ui(self):
        self.setWindowTitle(f"BDC Loader v{PLUGIN_VERSION}")
        self.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.WindowMinMaxButtonsHint | Qt.WindowType.WindowCloseButtonHint
        )

        # Reset download confirmation flag each session
        QgsSettings().setValue("bdc_loader/skip_download_confirm", False)

        main_layout = QVBoxLayout()
        main_layout.setSpacing(6)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # Build UI sections
        header = self._setup_header()
        main_layout.addWidget(header)

        # Main content splitter
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(8)
        self.splitter.setStyleSheet("""
            QSplitter::handle { background-color: #bdc3c7; border-radius: 4px; }
            QSplitter::handle:hover { background-color: #3498db; }
        """)

        left_widget = self._setup_left_panel()
        self.splitter.addWidget(left_widget)

        right_widget = self._setup_right_panel()
        self.splitter.addWidget(right_widget)

        self.splitter.setChildrenCollapsible(False)
        self.splitter.setSizes([450, 550])
        main_layout.addWidget(self.splitter)

        self._setup_footer(main_layout)

    def _setup_header(self):
        """Build the header bar with logo, status, and controls."""
        header = QFrame()
        header.setStyleSheet("background-color: #2c3e50; border-radius: 4px;")
        header.setFixedHeight(40)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 4, 10, 4)

        logo_label = QLabel()
        icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "icon.png")
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path)
            logo_label.setPixmap(
                pixmap.scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
        header_layout.addWidget(logo_label)

        title_label = QLabel(
            f"<span style='color: white; font-size: 12px;'><b>Brazil Data Cube</b> - Loader v{PLUGIN_VERSION}</span>"
        )
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        self._build_stac_indicator(header_layout)

        # BDC documentation link
        doc_btn = QPushButton("Docs")
        doc_btn.setFixedSize(36, 22)
        doc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        doc_btn.setStyleSheet(_DOCS_BUTTON_STYLE)
        self.set_tooltip(doc_btn, "Explore INPE data, BDC data cubes, services, and technical references")
        doc_btn.clicked.connect(self._show_docs_dialog)
        header_layout.addWidget(doc_btn)

        self.tour_btn = QPushButton("Tour")
        self.tour_btn.setFixedSize(36, 22)
        self.tour_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tour_btn.setStyleSheet(_DOCS_BUTTON_STYLE)
        self.set_tooltip(self.tour_btn, "Guided tour of the plugin, step by step")
        self.tour_btn.clicked.connect(self.start_tour)
        header_layout.addWidget(self.tour_btn)

        # BDC projection button
        proj_btn = QPushButton("BDC Proj")
        proj_btn.setFixedSize(52, 22)
        proj_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        proj_btn.setStyleSheet(_BDC_PROJ_BUTTON_STYLE)
        self.set_tooltip(
            proj_btn,
            "Click to set the project CRS to SIRGAS 2000 / Brazil Albers\n"
            "(EPSG:10857 when available; compatible fallback on older QGIS versions)",
        )
        proj_btn.clicked.connect(self._apply_bdc_projection)
        header_layout.addWidget(proj_btn)

        self._build_panel_toggles(header_layout)
        self._build_header_buttons(header_layout)
        return header

    def _build_stac_indicator(self, header_layout):
        """Clickable STAC connection dot and label."""
        self.stac_status_container = QWidget()
        stac_status_layout = QHBoxLayout(self.stac_status_container)
        stac_status_layout.setContentsMargins(4, 0, 4, 0)
        stac_status_layout.setSpacing(4)
        self.stac_status_container.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stac_status_container.setStyleSheet(
            "QWidget:hover { background-color: rgba(255,255,255,30); border-radius: 4px; }"
        )
        self.stac_status_container.mousePressEvent = self._on_stac_status_clicked
        self.set_tooltip(self.stac_status_container, "Click to open BDC STAC catalog in browser")

        self.stac_status_dot = QLabel()
        self.stac_status_dot.setFixedSize(10, 10)
        self.stac_status_dot.setStyleSheet("background-color: #95a5a6; border-radius: 5px;")
        self.stac_status_dot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        stac_status_layout.addWidget(self.stac_status_dot)

        self.stac_status_label = QLabel("<span style='color: #bdc3c7; font-size: 9px;'>STAC: ...</span>")
        self.stac_status_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        fix_label_width_for_texts(
            self.stac_status_label,
            ("STAC: Online (99999ms)", "STAC: Slow (99999ms)", "Offline: local data", "STAC: Online (999 collections)"),
            9,
        )
        stac_status_layout.addWidget(self.stac_status_label)

        header_layout.addWidget(self.stac_status_container)

    def _build_panel_toggles(self, header_layout):
        """Switches that show the time series panel and the timeline toolbar."""
        self.ts_btn = QPushButton()
        self.ts_btn.setFixedSize(44, 24)
        self.ts_btn.setCheckable(True)
        self.ts_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_ts_toggle_style(False)
        self.set_tooltip(self.ts_btn, "Open/Close BDC Time Series panel")
        self.ts_btn.clicked.connect(self._toggle_timeseries_panel)
        header_layout.addWidget(_labelled_switch("Time Series", self.ts_btn))

        self.tl_btn = QPushButton()
        self.tl_btn.setFixedSize(44, 24)
        self.tl_btn.setCheckable(True)
        self.tl_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        tl_visible = self._timeline_toolbar.isVisible() if self._timeline_toolbar else False
        self.tl_btn.setChecked(tl_visible)
        self._update_tl_toggle_style(tl_visible)
        self.set_tooltip(self.tl_btn, "Open/Close Timeline Toolbar")
        self.tl_btn.clicked.connect(self._toggle_timeline_toolbar)
        header_layout.addWidget(_labelled_switch("Timeline Panel", self.tl_btn))
        if self._timeline_toolbar:
            self._timeline_toolbar.visibilityChanged.connect(self._on_tl_toolbar_visibility_changed)

    def _build_header_buttons(self, header_layout):
        """Log, settings and About buttons."""
        from .log_panel import LogButton

        self._log_btn = LogButton(self)
        self.set_tooltip(self._log_btn, "Activity log — click to open/close")
        header_layout.addWidget(self._log_btn)

        self.config_btn = QPushButton("\u2699")
        self.config_btn.setFixedSize(28, 22)
        self.config_btn.setStyleSheet(_CONFIG_BTN_STYLE)
        self.set_tooltip(self.config_btn, "Plugin settings (folders, performance, storage, tutorial)")
        self.config_btn.clicked.connect(self._open_settings)
        header_layout.addWidget(self.config_btn)

        about_btn = QPushButton("About")
        about_btn.setFixedHeight(26)
        about_btn.setMinimumWidth(72)
        about_btn.setStyleSheet(_ABOUT_BTN_STYLE)
        self.set_tooltip(about_btn, "About this plugin")
        about_btn.clicked.connect(self.show_about)
        header_layout.addWidget(about_btn)
        self._build_language_switch(header_layout)

    def _build_language_switch(self, header_layout):
        """Brazilian and United States flags that switch the interface language."""
        group = QButtonGroup(self)
        group.setExclusive(True)
        self.language_buttons = {}
        for lang, name in (("pt", "Português (Brasil)"), ("en", "English")):
            button = QToolButton()
            button.setCheckable(True)
            button.setIcon(flag_icon(lang))
            button.setIconSize(QSize(24, 16))
            button.setFixedSize(30, 24)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(name)
            button.setStyleSheet(_FLAG_BUTTON_STYLE)
            button.setChecked(lang == language())
            button.clicked.connect(lambda _checked=False, lang=lang: self._set_language(lang))
            group.addButton(button)
            self.language_buttons[lang] = button
            header_layout.addWidget(button)

    def _setup_left_panel(self):
        """Build the left panel with collection, bands, spatial filters."""
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setSpacing(6)
        left_layout.setContentsMargins(0, 0, 0, 0)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setStyleSheet("QScrollArea { border: none; }")
        left_scroll_widget = QWidget()
        left_scroll_layout = QVBoxLayout(left_scroll_widget)
        left_scroll_layout.setSpacing(6)

        self._build_collection_group(left_scroll_layout)
        self._build_period_group(left_scroll_layout)

        # One fixed line says which area filter is in use and how to switch;
        # it changes text only, so nothing below it moves.
        self._spatial_hint = FixedLinesLabel(lines=2)
        self._spatial_hint.setStyleSheet("font-size: 9px; font-style: italic; color: #57606a; padding: 0 8px;")
        left_scroll_layout.addWidget(self._spatial_hint)

        self._build_extent_group(left_scroll_layout)
        self._build_tiles_group(left_scroll_layout)
        self._build_vector_group(left_scroll_layout)
        hand_cursor_on_title(self.extent_box, self.tiles_group, self.shape_group)
        # The spatial toggles reach all three groups, so they connect once the groups exist.
        self.extent_box.activeChanged.connect(self._on_extent_toggled)
        # Closing the group of the filter in use releases it, like its clear button.
        self.tiles_group.collapsedStateChanged.connect(self._on_tiles_collapsed)
        self.shape_group.collapsedStateChanged.connect(self._on_shape_collapsed)

        # Internal state for shapefile
        self._shape_vector_layer = None  # QgsVectorLayer loaded from file
        self._shape_features = []  # list of (fid, name, geometry_wkt)
        self._shape_file_path = None
        self._shape_project_layer = None
        self._apply_spatial_locks()

        self._build_bands_group(left_scroll_layout)
        self._build_output_group(left_scroll_layout)
        self._build_options_row(left_scroll_layout)
        left_scroll_layout.addStretch()
        left_scroll.setWidget(left_scroll_widget)
        self._left_scroll_keeper = keep_scroll_min_width(left_scroll)
        left_layout.addWidget(left_scroll)

        self._build_actions_bar(left_layout)
        return left_widget

    def _build_collection_group(self, left_scroll_layout):
        """Collection group: type filter, collection combo with its filter button, and info line."""
        coll_group = QgsCollapsibleGroupBox("Collection")
        coll_layout = QVBoxLayout()
        coll_layout.setContentsMargins(8, 8, 8, 8)

        # Collection type filter
        filter_layout = QGridLayout()
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setHorizontalSpacing(6)
        filter_layout.setVerticalSpacing(2)
        _type_label = QLabel("Type:")
        _type_label.setStyleSheet("font-size: 10px;")
        filter_layout.addWidget(_type_label, 0, 0)

        _filter_radio_style = """
            QRadioButton { font-size: 10px; }
            QRadioButton::indicator { width: 11px; height: 11px; }
        """
        self.filter_buttons = QButtonGroup()
        self.filter_all_btn = QRadioButton("All")
        self.filter_cube_btn = QRadioButton("Cubes")
        self.filter_collection_btn = QRadioButton("Collections")
        self.filter_mosaic_btn = QRadioButton("Mosaics")
        for _btn in (self.filter_all_btn, self.filter_cube_btn, self.filter_collection_btn, self.filter_mosaic_btn):
            _btn.setStyleSheet(_filter_radio_style)

        self.filter_all_btn.setChecked(True)
        self.filter_buttons.addButton(self.filter_all_btn, 0)
        self.filter_buttons.addButton(self.filter_cube_btn, 1)
        self.filter_buttons.addButton(self.filter_collection_btn, 2)
        self.filter_buttons.addButton(self.filter_mosaic_btn, 3)

        self.filter_all_btn.toggled.connect(self._filter_collections)
        self.filter_cube_btn.toggled.connect(self._filter_collections)
        self.filter_collection_btn.toggled.connect(self._filter_collections)
        self.filter_mosaic_btn.toggled.connect(self._filter_collections)

        filter_layout.addWidget(self.filter_all_btn, 0, 1)
        filter_layout.addWidget(self.filter_cube_btn, 0, 2)
        filter_layout.addWidget(self.filter_collection_btn, 0, 3)
        filter_layout.addWidget(self.filter_mosaic_btn, 0, 4)
        filter_layout.setColumnStretch(5, 1)
        coll_layout.addLayout(filter_layout)

        # Collection combo + individual filter button
        coll_combo_row = QHBoxLayout()
        self.collection_combo = QComboBox()
        # Cap the requested width so long collection names elide instead of forcing
        # a horizontal scrollbar on the left panel; the popup still shows full names.
        self.collection_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.collection_combo.setMinimumContentsLength(12)
        self._populate_collections()
        self.collection_combo.setItemDelegate(CollectionBadgeDelegate(self.collection_combo))
        self.collection_combo.currentTextChanged.connect(self.on_collection_changed)
        coll_combo_row.addWidget(self.collection_combo, stretch=1)

        self.coll_filter_btn = QPushButton("\u2630")  # Hamburger menu
        self.coll_filter_btn.setFixedSize(28, 24)
        self.set_tooltip(self.coll_filter_btn, "Toggle individual collections")
        self.coll_filter_btn.setStyleSheet(_COLL_FILTER_BTN_STYLE)
        self.coll_filter_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.coll_filter_btn.clicked.connect(self._show_collection_filter_dialog)
        coll_combo_row.addWidget(self.coll_filter_btn)
        coll_layout.addLayout(coll_combo_row)

        # Selected collection info
        self.collection_info_label = QLabel()
        self.collection_info_label.setStyleSheet("font-size: 9px; color: #666; padding: 2px;")
        self.collection_info_label.setWordWrap(True)
        self.collection_info_label.setFrameShape(QFrame.Shape.NoFrame)
        coll_layout.addWidget(self.collection_info_label)

        coll_group.setLayout(coll_layout)
        left_scroll_layout.addWidget(coll_group)

    def _build_period_group(self, left_scroll_layout):
        """Period group: the date range slider."""
        date_group = QgsCollapsibleGroupBox("Period")
        date_layout = QVBoxLayout()
        date_layout.setContentsMargins(8, 8, 8, 8)
        self.range_slider = RangeSlider()
        date_layout.addWidget(self.range_slider)
        date_group.setLayout(date_layout)
        left_scroll_layout.addWidget(date_group)

    def _build_extent_group(self, left_scroll_layout):
        """Extent group with the mode selector, bbox text and clear button."""
        self.extent_box = ExtentGroup("Extent")
        self.extent_box.setStyleSheet(_DISABLED_GROUP_STYLE)
        self.extent_box.setCollapsed(True)
        self.prepare_extent_box()
        self.extent_box.extentChanged.connect(self._on_extent_changed)
        self.extent_box.collapsedStateChanged.connect(self._on_extent_expanded)
        left_scroll_layout.addWidget(self.extent_box)

        # Extent mode, bbox text and clear button
        self._extent_mode_frame = QFrame()
        _mode_layout = QHBoxLayout()
        _mode_layout.setContentsMargins(0, 0, 0, 0)
        _mode_layout.setSpacing(6)
        _mode_layout.addWidget(QLabel("Mode:"))
        self._extent_mode_group = QButtonGroup(self)
        self._extent_mode_intersect = QRadioButton("Search Tiles")
        self._extent_mode_intersect.setToolTip(
            "Search tiles that intersect the drawn extent.\nNo clipping — loads entire tiles."
        )
        self._extent_mode_crop = QRadioButton("Crop")
        self._extent_mode_crop.setToolTip(
            "Search intersecting tiles, merge by date, and\nclip the layers to the exact drawn extent."
        )
        self._extent_mode_group.addButton(self._extent_mode_intersect, 0)
        self._extent_mode_group.addButton(self._extent_mode_crop, 1)
        self._extent_mode_intersect.setChecked(True)
        _mode_layout.addWidget(self._extent_mode_intersect)
        _mode_layout.addWidget(self._extent_mode_crop)

        self._extent_bbox_edit = QLineEdit()
        self._extent_bbox_edit.setPlaceholderText("xmin,ymin,xmax,ymax")
        self._extent_bbox_edit.setStyleSheet("font-size: 10px; font-family: monospace; padding: 1px 3px;")
        # Size exactly to fit a typical bbox string like -65.3104,-11.9440,-62.9683,-9.7253
        from qgis.PyQt.QtGui import QFontMetrics

        _fm = QFontMetrics(self._extent_bbox_edit.font())
        _text_w = _fm.horizontalAdvance("-65.3104,-11.9440,-62.9683,-9.7253") + 12
        self._extent_bbox_edit.setFixedWidth(_text_w)
        self._extent_bbox_edit.setToolTip(
            "Bounding box in EPSG:4326 (xmin,ymin,xmax,ymax).\nDrawn automatically or type manually and press Enter."
        )
        self._extent_bbox_edit.returnPressed.connect(self._apply_manual_bbox)
        _mode_layout.addWidget(self._extent_bbox_edit)

        self._extent_copy_btn = QPushButton()
        self._extent_copy_btn.setIcon(copy_icon())
        self._extent_copy_btn.setIconSize(QSize(14, 14))
        self._extent_copy_btn.setFixedSize(24, 24)
        self._extent_copy_btn.setToolTip("Copy bbox to clipboard")
        self._extent_copy_btn.clicked.connect(self._copy_bbox_to_clipboard)
        _mode_layout.addWidget(self._extent_copy_btn)

        self._extent_center_btn = QPushButton()
        self._extent_center_btn.setIcon(zoom_icon())
        self._extent_center_btn.setIconSize(QSize(14, 14))
        self._extent_center_btn.setFixedSize(24, 24)
        self._extent_center_btn.setToolTip("Zoom to bbox")
        self._extent_center_btn.clicked.connect(self._center_on_bbox)
        _mode_layout.addWidget(self._extent_center_btn)

        _mode_layout.addStretch()
        clear_extent_btn = QPushButton("\u2715")
        clear_extent_btn.setFixedSize(30, 26)
        clear_extent_btn.setStyleSheet(
            "QPushButton { background: #fff5f5; border: 1px solid #ffcdd2; border-radius: 4px; "
            "color: #c62828; font-size: 13px; font-weight: bold; padding: 0; } "
            "QPushButton:hover { background: #ffebee; border-color: #e53935; }"
        )
        self.set_tooltip(clear_extent_btn, "Clear extent")
        clear_extent_btn.clicked.connect(self._clear_extent)
        _mode_layout.addWidget(clear_extent_btn)
        self._extent_mode_frame.setLayout(_mode_layout)
        self.extent_box.content_layout.addWidget(self._extent_mode_frame)

    def _build_tiles_group(self, left_scroll_layout):
        """Tiles group: grid buttons and the tile list field with copy and clear buttons."""
        tiles_group = QgsCollapsibleGroupBox("Tiles")
        tiles_group.setStyleSheet(_DISABLED_GROUP_STYLE)
        tiles_group.setCollapsed(True)
        tiles_layout = QVBoxLayout()
        tiles_layout.setContentsMargins(8, 8, 8, 8)
        tiles_layout.setSpacing(6)

        self.grid_status_label = QLabel("Grid not loaded")
        self.grid_status_label.setStyleSheet("font-size: 10px;")
        tiles_layout.addWidget(self.grid_status_label)

        grid_btn_layout = QHBoxLayout()
        self.load_grid_btn = QPushButton("Load Grid")
        self.set_tooltip(self.load_grid_btn, "Load BDC tile grid on the map")
        self.load_grid_btn.clicked.connect(self.load_grid)
        self.select_tiles_btn = QPushButton("Select on Map")
        self.set_tooltip(self.select_tiles_btn, "Click tiles on the map to select")
        self.select_tiles_btn.clicked.connect(self.start_tile_selection)
        self.select_tiles_btn.setEnabled(False)
        grid_btn_layout.addWidget(self.load_grid_btn)
        grid_btn_layout.addWidget(self.select_tiles_btn)
        tiles_layout.addLayout(grid_btn_layout)

        self.finish_tiles_btn = QPushButton("Finish Selection")
        self.set_tooltip(self.finish_tiles_btn, "Finish tile selection on the map")
        self.finish_tiles_btn.setEnabled(False)
        self.finish_tiles_btn.clicked.connect(self.finish_tile_selection)
        tiles_layout.addWidget(self.finish_tiles_btn)

        tiles_input_layout = QHBoxLayout()
        tiles_input_layout.setSpacing(4)
        self.tiles_input = QLineEdit()
        self.tiles_input.setPlaceholderText("031023, 031024, ...")
        tiles_input_layout.addWidget(self.tiles_input)

        copy_tiles_btn = QPushButton()
        copy_tiles_btn.setIcon(copy_icon())
        copy_tiles_btn.setIconSize(QSize(14, 14))
        copy_tiles_btn.setFixedSize(30, 26)
        copy_tiles_btn.setStyleSheet(
            "QPushButton { background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 4px; "
            "font-size: 13px; padding: 0; } "
            "QPushButton:hover { background: #eaeef2; border-color: #0969da; }"
        )
        self.set_tooltip(copy_tiles_btn, "Copy tiles to clipboard")
        copy_tiles_btn.clicked.connect(self._copy_tiles_to_clipboard)
        tiles_input_layout.addWidget(copy_tiles_btn)

        self.clear_tiles_btn = QPushButton("\u2715")
        self.clear_tiles_btn.setFixedSize(30, 26)
        self.clear_tiles_btn.setStyleSheet(
            "QPushButton { background: #fff5f5; border: 1px solid #ffcdd2; border-radius: 4px; "
            "color: #c62828; font-size: 13px; font-weight: bold; padding: 0; } "
            "QPushButton:hover { background: #ffebee; border-color: #e53935; }"
        )
        self.set_tooltip(self.clear_tiles_btn, "Clear all tiles")
        self.clear_tiles_btn.clicked.connect(self.clear_tiles)
        tiles_input_layout.addWidget(self.clear_tiles_btn)
        tiles_layout.addLayout(tiles_input_layout)

        self.selected_tiles_list = QListWidget()
        self.selected_tiles_list.setMaximumHeight(80)
        self.selected_tiles_list.setStyleSheet(
            "QListWidget { border: 1px solid #d0d7de; border-radius: 4px; font-size: 11px; }"
            "QListWidget::item { padding: 2px 6px; }"
            "QListWidget::item:selected { background: #dbeafe; color: #1e40af; }"
        )
        tiles_layout.addWidget(self.selected_tiles_list)

        tiles_group.setLayout(tiles_layout)
        self.tiles_group = tiles_group
        left_scroll_layout.addWidget(tiles_group)
        self.tiles_input.textChanged.connect(self._on_tiles_text_changed)

    def _build_vector_group(self, left_scroll_layout):
        """Vector File group: file or project layer, name field, merge option and feature list."""
        shape_group = QgsCollapsibleGroupBox("Vector File")
        shape_group.setStyleSheet(_DISABLED_GROUP_STYLE)
        shape_group.setCollapsed(True)
        shape_layout = QVBoxLayout()
        shape_layout.setContentsMargins(8, 8, 8, 8)
        shape_layout.setSpacing(6)

        # Supported formats info
        _fmt_label = QLabel("Shapefile (.shp), GeoPackage (.gpkg) or a polygon layer of the project")
        _fmt_label.setStyleSheet("font-size: 10px; color: #57606a; font-style: italic; padding: 0 0 2px 0;")
        shape_layout.addWidget(_fmt_label)

        self._build_vector_source_row(shape_layout)
        self._build_vector_options(shape_layout)
        self._build_feature_list(shape_layout)

        shape_group.setLayout(shape_layout)
        self.shape_group = shape_group
        left_scroll_layout.addWidget(shape_group)

    def _build_vector_source_row(self, shape_layout):
        """Path field with the Browse, project Layer and clear buttons."""
        shape_file_layout = QHBoxLayout()
        shape_file_layout.setSpacing(4)
        self.shape_file_input = QLineEdit()
        self.shape_file_input.setPlaceholderText("Browse to select a vector file...")
        self.shape_file_input.setReadOnly(True)
        shape_file_layout.addWidget(self.shape_file_input, stretch=1)

        browse_shape_btn = QPushButton("Browse")
        browse_shape_btn.setFixedWidth(70)
        browse_shape_btn.setStyleSheet(
            "QPushButton { background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 4px; "
            "padding: 4px 8px; font-size: 11px; } "
            "QPushButton:hover { background: #eaeef2; border-color: #0969da; }"
        )
        browse_shape_btn.clicked.connect(self._browse_shapefile)
        shape_file_layout.addWidget(browse_shape_btn)

        self.shape_layer_btn = QPushButton("Layer")
        self.shape_layer_btn.setFixedWidth(60)
        self.shape_layer_btn.setStyleSheet(browse_shape_btn.styleSheet())
        self.set_tooltip(
            self.shape_layer_btn,
            "Use a polygon layer already in the project, such as a tile grid. "
            "Features selected on the map are the ones listed.",
        )
        self.shape_layer_btn.clicked.connect(self._choose_project_layer)
        shape_file_layout.addWidget(self.shape_layer_btn)

        clear_shape_btn = QPushButton("\u2715")
        clear_shape_btn.setFixedSize(30, 26)
        clear_shape_btn.setStyleSheet(
            "QPushButton { background: #fff5f5; border: 1px solid #ffcdd2; border-radius: 4px; "
            "color: #c62828; font-size: 13px; font-weight: bold; padding: 0; } "
            "QPushButton:hover { background: #ffebee; border-color: #e53935; }"
        )
        self.set_tooltip(clear_shape_btn, "Clear shapefile")
        clear_shape_btn.clicked.connect(self._clear_shapefile)
        shape_file_layout.addWidget(clear_shape_btn)
        shape_layout.addLayout(shape_file_layout)

    def _build_vector_options(self, shape_layout):
        """GeoPackage layer and label field combos, and the merge-all option."""
        # Layer selector, enabled for a GeoPackage with several layers
        layer_row = QHBoxLayout()
        layer_row.setSpacing(4)
        layer_row.addWidget(QLabel("Layer:"))
        self.shape_layer_combo = QComboBox()
        self.shape_layer_combo.setEnabled(False)
        self.shape_layer_combo.currentIndexChanged.connect(self._on_shape_layer_changed)
        layer_row.addWidget(self.shape_layer_combo, stretch=1)
        shape_layout.addLayout(layer_row)

        # Attribute field selector for feature names
        attr_layout = QHBoxLayout()
        attr_layout.setSpacing(4)
        attr_layout.addWidget(QLabel("Label field:"))
        self.shape_attr_combo = QComboBox()
        self.shape_attr_combo.setEnabled(False)
        self.shape_attr_combo.currentIndexChanged.connect(self._on_shape_attr_changed)
        attr_layout.addWidget(self.shape_attr_combo, stretch=1)
        shape_layout.addLayout(attr_layout)

        # Merge All option
        self.shape_merge_check = QCheckBox("Merge all (use outer boundary)")
        self.shape_merge_check.setStyleSheet("font-size: 11px;")
        self.set_tooltip(
            self.shape_merge_check,
            "Merge all features into a single boundary (e.g. entire biome instead of individual ecoregions)",
        )
        self.shape_merge_check.toggled.connect(self._on_shape_merge_toggled)
        shape_layout.addWidget(self.shape_merge_check)

    def _build_feature_list(self, shape_layout):
        """Feature list with Select All and Deselect All, and the feature count."""
        self.shape_feature_list = QListWidget()
        self.shape_feature_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.shape_feature_list.setMaximumHeight(120)
        self.shape_feature_list.setStyleSheet(
            "QListWidget { border: 1px solid #d0d7de; border-radius: 4px; font-size: 11px; }"
            "QListWidget::item { padding: 2px 6px; }"
        )
        shape_layout.addWidget(self.shape_feature_list)

        # Select all / Deselect all
        shape_sel_layout = QHBoxLayout()
        shape_sel_layout.setSpacing(4)
        shape_select_all_btn = QPushButton("Select All")
        shape_select_all_btn.setFixedHeight(24)
        shape_select_all_btn.setStyleSheet(
            "QPushButton { background: #f0f6ff; border: 1px solid #c8d8ea; border-radius: 4px; "
            "font-size: 10px; padding: 2px 8px; } "
            "QPushButton:hover { background: #dbeafe; border-color: #0969da; }"
        )
        shape_select_all_btn.clicked.connect(lambda: self._shape_select_all(True))
        shape_sel_layout.addWidget(shape_select_all_btn)

        shape_deselect_all_btn = QPushButton("Deselect All")
        shape_deselect_all_btn.setFixedHeight(24)
        shape_deselect_all_btn.setStyleSheet(
            "QPushButton { background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 4px; "
            "font-size: 10px; padding: 2px 8px; } "
            "QPushButton:hover { background: #eaeef2; border-color: #d0d7de; }"
        )
        shape_deselect_all_btn.clicked.connect(lambda: self._shape_select_all(False))
        shape_sel_layout.addWidget(shape_deselect_all_btn)
        shape_layout.addLayout(shape_sel_layout)

        # Feature count info
        self.shape_info_label = FixedLinesLabel(lines=1)
        self.shape_info_label.setStyleSheet("font-size: 9px; color: #57606a;")
        shape_layout.addWidget(self.shape_info_label)

    def _build_bands_group(self, left_scroll_layout):
        """Bands group: RGB preset combo and the available and selected band lists."""
        rgb_group = QgsCollapsibleGroupBox("Bands")
        rgb_layout = QVBoxLayout()
        rgb_layout.setContentsMargins(8, 8, 8, 8)
        rgb_layout.setSpacing(6)

        preset_layout = QHBoxLayout()
        preset_layout.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.currentTextChanged.connect(self.apply_preset)
        preset_layout.addWidget(self.preset_combo, stretch=1)

        self.save_composition_btn = QPushButton()
        self.save_composition_btn.setIcon(plus_icon())
        self.save_composition_btn.setIconSize(QSize(14, 14))
        self.save_composition_btn.setFixedSize(26, 26)
        self.save_composition_btn.setToolTip("New composition: choose its bands and name")
        self.save_composition_btn.clicked.connect(self._save_composition)
        preset_layout.addWidget(self.save_composition_btn)

        self.delete_composition_btn = QPushButton()
        self.delete_composition_btn.setIcon(trash_icon())
        self.delete_composition_btn.setIconSize(QSize(14, 14))
        self.delete_composition_btn.setFixedSize(26, 26)
        self.delete_composition_btn.setToolTip("Delete the selected composition (only compositions you saved)")
        self.delete_composition_btn.setEnabled(False)
        self.delete_composition_btn.clicked.connect(self._delete_composition)
        preset_layout.addWidget(self.delete_composition_btn)
        rgb_layout.addLayout(preset_layout)

        bands_layout = QHBoxLayout()
        self.available_bands = QListWidget()
        self.available_bands.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.available_bands.setFixedHeight(110)
        self.available_bands.setMinimumWidth(160)
        bands_layout.addWidget(self.available_bands, stretch=1)

        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(4)
        add_btn = QPushButton(">>")
        add_btn.setFixedWidth(35)
        self.set_tooltip(add_btn, "Add selected band")
        add_btn.clicked.connect(self.add_band)
        remove_btn = QPushButton("<<")
        remove_btn.setFixedWidth(35)
        self.set_tooltip(remove_btn, "Remove selected band")
        remove_btn.clicked.connect(self.remove_band)
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(remove_btn)
        btn_layout.addStretch()
        bands_layout.addLayout(btn_layout)

        self.selected_bands = QListWidget()
        self.selected_bands.setFixedHeight(110)
        self.selected_bands.setMinimumWidth(160)
        bands_layout.addWidget(self.selected_bands, stretch=1)

        rgb_layout.addLayout(bands_layout)

        rgb_group.setLayout(rgb_layout)
        left_scroll_layout.addWidget(rgb_group)

    def _build_output_group(self, left_scroll_layout):
        """Output group: the VRT folder field."""
        output_group = QgsCollapsibleGroupBox("Output")
        output_layout = QHBoxLayout()
        output_layout.setContentsMargins(8, 8, 8, 8)
        self.output_dir = QLineEdit(self._vrt_dir)
        output_btn = QPushButton("...")
        output_btn.setFixedWidth(35)
        self.set_tooltip(output_btn, "Choose folder to save VRTs")
        output_btn.clicked.connect(self.select_output_dir)
        output_layout.addWidget(self.output_dir)
        output_layout.addWidget(output_btn)
        output_group.setLayout(output_layout)
        left_scroll_layout.addWidget(output_group)

    def _build_options_row(self, left_scroll_layout):
        """Item limit and the show-on-map option."""
        options_layout = QHBoxLayout()
        options_layout.addWidget(QLabel("Limit:"))
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 200)
        self.limit_spin.setValue(50)
        self.limit_spin.setFixedWidth(60)
        options_layout.addWidget(self.limit_spin)

        self.auto_select_check = QCheckBox("Show on map when loaded")
        self.auto_select_check.setChecked(False)
        self.auto_select_check.setToolTip(
            "Checked: the first date of each series is drawn right away; the timeline steps through the others.\n"
            "Unchecked: the layers are added to the Layers panel turned off."
        )
        options_layout.addWidget(self.auto_select_check)
        options_layout.addStretch()
        left_scroll_layout.addLayout(options_layout)

    def _build_actions_bar(self, left_layout):
        """Bottom bar: Import Query, Export Code and Search STAC buttons."""
        actions_bar = QHBoxLayout()
        actions_bar.setSpacing(6)

        self.import_query_btn_bar = QPushButton("Import Query")
        self.import_query_btn_bar.setStyleSheet(_IMPORT_QUERY_BTN_BAR_STYLE)
        self.import_query_btn_bar.setToolTip("Import query parameters from JSON or YAML file")
        self.import_query_btn_bar.clicked.connect(self._open_import_query_dialog)
        actions_bar.addWidget(self.import_query_btn_bar, stretch=1)

        self.export_query_btn = QPushButton("Export Code")
        self.export_query_btn.setStyleSheet(_EXPORT_QUERY_BTN_STYLE)
        self.export_query_btn.setToolTip("Export query parameters to JSON, YAML, R, Python, or cURL")
        self.export_query_btn.clicked.connect(self._open_export_query_dialog)
        actions_bar.addWidget(self.export_query_btn, stretch=1)

        self.search_btn = QPushButton("Search STAC")
        self.search_btn.setStyleSheet(_SEARCH_BTN_STYLE)
        self.search_btn.setToolTip("Search items in the BDC STAC catalog")
        self.search_btn.clicked.connect(self.search_stac)
        actions_bar.addWidget(self.search_btn, stretch=2)

        left_layout.addLayout(actions_bar)

    def _setup_right_panel(self):
        """Build the right panel with results, filters, controls."""
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setSpacing(6)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self._build_status_area(right_layout)
        self._build_results_header(right_layout)
        self._build_result_filters(right_layout)
        self._build_results_area(right_layout)

        # VRT generation preview
        self.vrt_preview_label = FixedLinesLabel(lines=1)
        self.vrt_preview_label.setStyleSheet(
            "font-size: 9px; color: #555; padding: 2px 6px; background-color: #eef6ff; border: 1px solid #cde; border-radius: 3px;"
        )
        keep_space_when_hidden(self.vrt_preview_label)
        self.vrt_preview_label.setVisible(False)
        right_layout.addWidget(self.vrt_preview_label)

        self._build_result_actions(right_layout)
        return right_widget

    def _build_status_area(self, right_layout):
        """Fixed-height status frame: progress bar, status line and the Cancel button."""
        self._status_frame = QFrame()
        self._status_frame.setFixedHeight(80)
        self._status_frame.setObjectName("statusFrame")
        self._status_frame.setStyleSheet(_STATUS_FRAME_STYLE)
        status_frame_layout = QVBoxLayout(self._status_frame)
        status_frame_layout.setContentsMargins(10, 6, 10, 6)
        status_frame_layout.setSpacing(4)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(14)
        keep_space_when_hidden(self.progress_bar)
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet(_PROGRESS_BAR_STYLE)
        status_frame_layout.addWidget(self.progress_bar)

        # Status row + cancel button
        status_row = QHBoxLayout()
        status_row.setSpacing(8)

        self._status_icon = QLabel("\u2139")
        self._status_icon.setFixedSize(20, 20)
        self._status_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_icon.setStyleSheet(_STATUS_ICON_STYLE)
        status_row.addWidget(self._status_icon)

        self.status_label = FixedLinesLabel("Set parameters and click Search.", lines=2)
        self.status_label.setStyleSheet(_STATUS_LABEL_STYLE)
        status_row.addWidget(self.status_label, stretch=1)

        # Cancel button (initially hidden)
        self._cancel_download_btn = QPushButton("\u2715 Cancel")
        self._cancel_download_btn.setFixedHeight(26)
        keep_space_when_hidden(self._cancel_download_btn)
        self._cancel_download_btn.setVisible(False)
        self._cancel_download_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cancel_download_btn.setStyleSheet(_CANCEL_DOWNLOAD_BTN_STYLE)
        self._cancel_download_btn.clicked.connect(self._cancel_active_operation)
        status_row.addWidget(self._cancel_download_btn)
        fix_width_for_texts(self._cancel_download_btn, ("\u2715 Cancel", "Cancelling..."))

        status_frame_layout.addLayout(status_row)
        right_layout.addWidget(self._status_frame)

    def _show_cancel_button(self, on_cancel):
        """Show the status line's Cancel button; a click calls ``on_cancel()`` once."""
        self._active_cancel = on_cancel
        set_text(self._cancel_download_btn, "\u2715 Cancel")
        self._cancel_download_btn.setEnabled(True)
        self._cancel_download_btn.setVisible(True)

    def _hide_cancel_button(self):
        self._active_cancel = None
        self._cancel_download_btn.setVisible(False)

    def _cancel_active_operation(self):
        """The Cancel button: stops the download, load or grid download that showed it."""
        on_cancel, self._active_cancel = getattr(self, "_active_cancel", None), None
        if on_cancel is None:
            return
        self._cancel_download_btn.setEnabled(False)
        set_text(self._cancel_download_btn, "Cancelling...")
        on_cancel()

    def _build_results_header(self, right_layout):
        """Results header: view toggle, All/None selection and the downloaded-only switch."""
        results_header = QHBoxLayout()
        results_header.addWidget(QLabel("<b>Results</b>"))
        results_header.addStretch()

        # View toggle
        view_label = QLabel("View:")
        view_label.setStyleSheet("font-size: 12px; font-weight: bold;")
        results_header.addWidget(view_label)

        self.view_detailed_btn = QPushButton("Detailed")
        self.view_detailed_btn.setCheckable(True)
        self.view_detailed_btn.setChecked(True)
        self.view_detailed_btn.setFixedHeight(24)
        self.set_tooltip(self.view_detailed_btn, "Show cards with thumbnails")
        self.view_detailed_btn.setStyleSheet("""
            QPushButton { padding: 2px 8px; }
            QPushButton:checked { background-color: #3498db; color: white; }
        """)
        self.view_detailed_btn.clicked.connect(lambda: self.set_view_mode(False))

        self.view_compact_btn = QPushButton("Compact")
        self.view_compact_btn.setCheckable(True)
        self.view_compact_btn.setFixedHeight(24)
        self.set_tooltip(self.view_compact_btn, "Show compact list without thumbnails")
        self.view_compact_btn.setStyleSheet("""
            QPushButton { padding: 2px 8px; }
            QPushButton:checked { background-color: #3498db; color: white; }
        """)
        self.view_compact_btn.clicked.connect(lambda: self.set_view_mode(True))

        results_header.addWidget(self.view_detailed_btn)
        results_header.addWidget(self.view_compact_btn)

        results_header.addWidget(QLabel(" | "))

        self.sel_all_btn = QPushButton("All")
        self.sel_all_btn.setFixedHeight(24)
        self.set_tooltip(self.sel_all_btn, "Select all results")
        self.sel_all_btn.clicked.connect(self.select_all_items)
        sel_none_btn = QPushButton("None")
        sel_none_btn.setFixedHeight(24)
        self.set_tooltip(sel_none_btn, "Deselect all results")
        sel_none_btn.clicked.connect(self.deselect_all_items)
        results_header.addWidget(self.sel_all_btn)
        results_header.addWidget(sel_none_btn)

        # Downloaded-only toggle switch
        results_header.addWidget(QLabel(" | "))

        toggle_container = QWidget()
        toggle_layout = QHBoxLayout(toggle_container)
        toggle_layout.setContentsMargins(0, 0, 0, 0)
        toggle_layout.setSpacing(6)

        toggle_label = QLabel("Downloaded:")
        toggle_label.setStyleSheet("font-size: 10px; font-weight: bold; color: #24292f;")
        toggle_layout.addWidget(toggle_label)

        self.downloaded_toggle_btn = QPushButton()
        self.downloaded_toggle_btn.setFixedSize(44, 24)
        self.downloaded_toggle_btn.setCheckable(True)
        self.downloaded_toggle_btn.setChecked(False)
        self.downloaded_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_toggle_style(False)
        self.set_tooltip(self.downloaded_toggle_btn, "Show only items with locally downloaded images")
        self.downloaded_toggle_btn.clicked.connect(self._toggle_downloaded_filter)
        toggle_layout.addWidget(self.downloaded_toggle_btn)

        results_header.addWidget(toggle_container)

        right_layout.addLayout(results_header)

    def _build_result_filters(self, right_layout):
        """Result filters: period, maximum cloud cover, tiles and Reset."""
        filter_frame = QFrame()
        filter_frame.setStyleSheet("background-color: #f7f9fc; border: 1px solid #d0d7de; border-radius: 5px;")
        filter_main_layout = QVBoxLayout(filter_frame)
        filter_main_layout.setContentsMargins(10, 6, 10, 6)
        filter_main_layout.setSpacing(6)

        # Period filter
        period_label = QLabel("<b>Period Filter:</b>")
        period_label.setStyleSheet("font-size: 11px; color: #24292f; border: none;")
        filter_main_layout.addWidget(period_label)

        self.filter_range_slider = RangeSlider()
        self.filter_range_slider.range_bar.rangeChanged.connect(self._on_filter_range_changed)
        self.filter_range_slider.range_bar.dragFinished.connect(self._on_filter_range_drag_finished)
        self.filter_range_slider.start_date_edit.dateChanged.connect(self._on_filter_range_changed_from_edit)
        self.filter_range_slider.end_date_edit.dateChanged.connect(self._on_filter_range_changed_from_edit)
        filter_main_layout.addWidget(self.filter_range_slider)

        # Cloud cover + tiles + reset controls
        controls_row = QHBoxLayout()
        controls_row.setSpacing(12)

        self._build_cloud_filter(controls_row)

        # Vertical separator
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.VLine)
        sep1.setStyleSheet("color: #d0d7de;")
        controls_row.addWidget(sep1)

        self._build_tile_filter(controls_row)
        controls_row.addStretch()

        # Reset button
        reset_btn = QPushButton("Reset")
        reset_btn.setFixedHeight(26)
        reset_btn.setToolTip("Reset filters to search values")
        reset_btn.setStyleSheet(_RESET_BUTTON_STYLE)
        reset_btn.clicked.connect(self._clear_result_filters)
        controls_row.addWidget(reset_btn)

        filter_main_layout.addLayout(controls_row)

        right_layout.addWidget(filter_frame)

    def _build_cloud_filter(self, controls_row):
        """Maximum cloud cover as a spin box and a slider kept in sync."""
        cloud_label = QLabel("<b>Max cloud:</b>")
        cloud_label.setStyleSheet("font-size: 10px; color: #24292f; border: none;")
        controls_row.addWidget(cloud_label)

        self.filter_cloud_spin = QSpinBox()
        self.filter_cloud_spin.setRange(0, 100)
        self.filter_cloud_spin.setValue(100)
        self.filter_cloud_spin.setSuffix("%")
        self.filter_cloud_spin.setFixedWidth(60)
        self.filter_cloud_spin.setFixedHeight(26)
        self.filter_cloud_spin.setStyleSheet(_CLOUD_SPIN_STYLE)
        controls_row.addWidget(self.filter_cloud_spin)

        self.filter_cloud_slider = JumpSlider(Qt.Orientation.Horizontal)
        self.filter_cloud_slider.setRange(0, 100)
        self.filter_cloud_slider.setValue(100)
        self.filter_cloud_slider.setSingleStep(1)
        self.filter_cloud_slider.setPageStep(5)
        self.filter_cloud_slider.setTickInterval(10)
        self.filter_cloud_slider.setTickPosition(JumpSlider.TickPosition.TicksBelow)
        self.filter_cloud_slider.setMinimumWidth(100)
        self.filter_cloud_slider.setMaximumWidth(200)
        self.filter_cloud_slider.setFixedHeight(26)
        self.filter_cloud_slider.setStyleSheet(_CLOUD_SLIDER_STYLE)
        controls_row.addWidget(self.filter_cloud_slider)

        # Sync spinbox <-> slider
        self.filter_cloud_spin.valueChanged.connect(self._on_cloud_spin_changed)
        self.filter_cloud_slider.valueChanged.connect(self._on_cloud_slider_changed)

    def _build_tile_filter(self, controls_row):
        """Tiles button, which opens the tile filter, and the count of tiles shown."""
        self.tile_filter_btn = QPushButton("Tiles")
        self.tile_filter_btn.setFixedHeight(26)
        self.tile_filter_btn.setStyleSheet(_TILE_FILTER_BUTTON_STYLE)
        self.tile_filter_btn.clicked.connect(self._open_tile_filter_dialog)
        controls_row.addWidget(self.tile_filter_btn)
        fix_width_for_texts(self.tile_filter_btn, ("Tiles", "Mosaics", "Tiles (N/A)"))

        self.tile_count_label = QLabel("")
        self.tile_count_label.setStyleSheet("font-size: 9px; color: #57606a; border: none;")
        controls_row.addWidget(self.tile_count_label)

    def _build_results_area(self, right_layout):
        """Scroll area that holds the result cards."""
        self.results_scroll = QScrollArea()
        self.results_scroll.setWidgetResizable(True)
        # Always shown, so the cards keep their width as results come and go
        self.results_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.results_scroll.setStyleSheet("background-color: #fafafa; border: 1px solid #ddd; border-radius: 5px;")
        self.results_scroll.verticalScrollBar().valueChanged.connect(self._on_scroll)

        self.results_container = QWidget()
        self.results_layout = QVBoxLayout(self.results_container)
        self.results_layout.setSpacing(4)
        self.results_layout.addStretch()
        self.results_scroll.setWidget(self.results_container)
        right_layout.addWidget(self.results_scroll)

    def _build_result_actions(self, right_layout):
        """Bottom row of actions on the selected results."""
        action_layout = QHBoxLayout()
        self.load_btn = QPushButton("Load layers")
        self.load_btn.setStyleSheet(_LOAD_BTN_STYLE)
        self.set_tooltip(
            self.load_btn,
            "Add the selected results to QGIS as layers. Images you have downloaded are read "
            "from your disk; the others are streamed from the BDC without downloading them.",
        )
        self.load_btn.clicked.connect(self.generate_and_load)
        self.load_btn.setEnabled(False)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setStyleSheet(_CLEAR_BTN_STYLE)
        self.set_tooltip(self.clear_btn, "Clear all search results", background_color="#1A2D5F")
        self.clear_btn.clicked.connect(self.clear_results)
        self.download_selected_btn = QPushButton("Download selected")
        self.download_selected_btn.setIcon(download_icon())
        self.download_selected_btn.setStyleSheet(_DOWNLOAD_SELECTED_BTN_STYLE)
        self.set_tooltip(
            self.download_selected_btn, "Download every selected result with the same format and projection"
        )
        self.download_selected_btn.clicked.connect(self._download_selected)
        self.download_selected_btn.setEnabled(False)
        action_layout.addWidget(self.load_btn)
        action_layout.addWidget(self.download_selected_btn)
        action_layout.addWidget(self.clear_btn)
        right_layout.addLayout(action_layout)

    def _setup_footer(self, main_layout):
        """Build the performance status bar and finalize layout."""
        # === PERFORMANCE STATUS BAR (fixed height, bottom) ===
        self._perf_status = QLabel()
        self._perf_status.setFixedHeight(22)
        self._perf_status.setStyleSheet(
            "background-color: #f6f8fa; border-top: 1px solid #d0d7de; "
            "padding: 2px 8px; font-size: 9px; color: #57606a;"
        )
        self._perf_status.setCursor(Qt.CursorShape.PointingHandCursor)
        self._perf_status.mousePressEvent = self._on_perf_status_clicked
        self._update_perf_status_bar()
        main_layout.addWidget(self._perf_status)

        self.setLayout(main_layout)
        collection_name = self._current_collection_name()
        self.on_collection_changed(collection_name)
        self.update_grid_status()
