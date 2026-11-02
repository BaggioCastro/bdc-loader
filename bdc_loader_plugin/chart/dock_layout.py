"""Widgets of the chart dock, one method per section: control bar, plot area with its range bars, RGB and line option strips, export row, and the signal wiring."""

import logging

_logger = logging.getLogger("bdc_loader")

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import (
    QButtonGroup,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..widgets.range_bar import AxisRangeBar
from ..widgets.range_slider import ToggleSwitch
from ..widgets.sizing import fix_width_for_texts
from . import mpl_env
from .dock_widgets import (
    _CTRL_BAR_STYLE,
    _EXPORT_CSV_BTN_STYLE,
    _EXPORT_SHP_BTN_STYLE,
    _PAGE_CHART_BTN_STYLE,
    _RANGE_LOCK_BTN_STYLE,
    _band_combo,
    _bar_separator,
    _channel_label,
)

# The RGB and line option rows take turns in one place, so the chart keeps its height.
_OPTIONS_ROW_HEIGHT = 40


class ChartDockLayout:
    """Widgets of the chart dock, one method per section: control bar, plot area with its range bars, RGB and line option strips, export row, and the signal wiring."""

    def _setup_ui(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        self._build_control_bar(layout)
        self._build_plot_area(layout)
        self._build_rgb_strip(layout)
        self._build_line_strip(layout)
        self._build_export_row(layout)
        self.setWidget(widget)
        self._connect_controls()

    def _build_control_bar(self, layout):
        """Top bar: mode, R/G/B/Y combos, pagination, auto-center and range lock."""
        ctrl_bar = QWidget()
        ctrl_bar.setStyleSheet(_CTRL_BAR_STYLE)
        ctrl_bar.setFixedHeight(38)
        ctrl_lay = QHBoxLayout(ctrl_bar)
        ctrl_lay.setContentsMargins(6, 3, 6, 3)
        ctrl_lay.setSpacing(5)

        mode_lbl = QLabel("Mode:")
        mode_lbl.setStyleSheet(
            "border: none; background: transparent; font-size: 10px; font-weight: bold; color: #444;"
        )
        ctrl_lay.addWidget(mode_lbl)

        self.viz_mode_group = QButtonGroup()
        self.line_mode_btn = QRadioButton("Line")
        self.line_mode_btn.setChecked(True)
        self.rgb_mode_btn = QRadioButton("RGB")
        self.viz_mode_group.addButton(self.line_mode_btn, 0)
        self.viz_mode_group.addButton(self.rgb_mode_btn, 1)
        self._update_mode_btn_styles()
        ctrl_lay.addWidget(self.line_mode_btn)
        ctrl_lay.addWidget(self.rgb_mode_btn)

        ctrl_lay.addWidget(_bar_separator())

        self._build_band_combos(ctrl_lay)
        self._build_chart_pagination(ctrl_lay)

        # Auto-center toggle
        self.auto_center_toggle = ToggleSwitch("Auto-center", False)
        self.auto_center_toggle.toggled.connect(self._parent_panel._on_auto_center_toggled)
        self.auto_center_toggle.setToolTip("Automatically center map rendering point when navigating charts")
        ctrl_lay.addWidget(self.auto_center_toggle)

        self.range_lock_btn = QPushButton("Dynamic range")
        self.range_lock_btn.setCheckable(True)
        self.range_lock_btn.setToolTip("Keep the current X and Y ranges when changing time series")
        self.range_lock_btn.setStyleSheet(_RANGE_LOCK_BTN_STYLE)
        self.range_lock_btn.toggled.connect(self._on_range_lock_toggled)
        ctrl_lay.addWidget(self.range_lock_btn)
        fix_width_for_texts(self.range_lock_btn, ("Dynamic range", "Range locked"))

        layout.addWidget(self._wrap_in_horizontal_scroll(ctrl_bar))

    def _build_band_combos(self, ctrl_lay):
        """R, G and B band combos, and the Y reference band of RGB mode."""
        ctrl_lay.addWidget(_channel_label("R:", "#e74c3c"))
        self.rgb_r_combo = _band_combo(72)
        ctrl_lay.addWidget(self.rgb_r_combo)

        ctrl_lay.addWidget(_channel_label("G:", "#27ae60"))
        self.rgb_g_combo = _band_combo(72)
        ctrl_lay.addWidget(self.rgb_g_combo)

        ctrl_lay.addWidget(_channel_label("B:", "#2980b9"))
        self.rgb_b_combo = _band_combo(72)
        ctrl_lay.addWidget(self.rgb_b_combo)

        # Y-reference combo for RGB mode
        ctrl_lay.addWidget(_bar_separator())

        lbl_y = _channel_label("Y:", "#e67e22")
        lbl_y.setToolTip("Reference band for Y axis rendering in RGB layout")
        ctrl_lay.addWidget(lbl_y)
        self.rgb_y_combo = _band_combo(82)
        self.rgb_y_combo.setToolTip("Select the band holding logical values for the Y axis rendering")
        ctrl_lay.addWidget(self.rgb_y_combo)

        ctrl_lay.addWidget(_bar_separator())

    def _build_chart_pagination(self, ctrl_lay):
        """Previous and next chart buttons around the page label."""
        self.prev_chart_btn = QPushButton("<")
        self.prev_chart_btn.setFixedSize(24, 24)
        self.prev_chart_btn.setStyleSheet(_PAGE_CHART_BTN_STYLE)
        self.prev_chart_btn.clicked.connect(lambda: self._parent_panel._change_viz(-1))
        self.prev_chart_btn.setEnabled(False)
        ctrl_lay.addWidget(self.prev_chart_btn)

        self.chart_page_label = QLabel("0/0")
        self.chart_page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.chart_page_label.setStyleSheet(
            "font-size: 10px; font-weight: bold; border: none; background: transparent; min-width: 38px; color: #444;"
        )
        ctrl_lay.addWidget(self.chart_page_label)

        self.next_chart_btn = QPushButton(">")
        self.next_chart_btn.setFixedSize(24, 24)
        self.next_chart_btn.setStyleSheet(_PAGE_CHART_BTN_STYLE)
        self.next_chart_btn.clicked.connect(lambda: self._parent_panel._change_viz(1))
        self.next_chart_btn.setEnabled(False)
        ctrl_lay.addWidget(self.next_chart_btn)

        ctrl_lay.addStretch()

    def _build_plot_area(self, layout):
        """The figure canvas with its Y range bar on the left and X range bar below."""
        chart_area = QHBoxLayout()
        chart_area.setSpacing(0)
        chart_area.setContentsMargins(0, 0, 0, 0)

        self.y_range_bar = AxisRangeBar(orientation="vertical", label="Y")
        self.y_range_bar.rangeChanged.connect(self._on_y_range_changed)
        chart_area.addWidget(self.y_range_bar)

        chart_stack = QVBoxLayout()
        chart_stack.setSpacing(0)

        matplotlib_classes = mpl_env.load_matplotlib()
        if matplotlib_classes:
            canvas_class, figure_class = matplotlib_classes
            self.figure = figure_class(figsize=(6, 3.5), dpi=100)
            self.figure.patch.set_facecolor("#f8f9fa")
            self.canvas_plot = canvas_class(self.figure)
            self.canvas_plot.setMinimumHeight(280)
            self.canvas_plot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            chart_stack.addWidget(self.canvas_plot, stretch=1)
            # Chart click handler
            self.canvas_plot.mpl_connect("button_press_event", self._on_chart_click)
            # Keep the range bars the same length as the plot area they control.
            self.canvas_plot.mpl_connect("draw_event", self._sync_range_bars)

            # Loading overlay
            self._loading_overlay = QLabel("Extracting RGB bands...", self.canvas_plot)
            self._loading_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._loading_overlay.setStyleSheet(
                "QLabel { background: rgba(248, 249, 250, 220); color: #2c3e50; "
                "font-size: 16px; font-weight: bold; border: 2px solid #2e7dd1; "
                "border-radius: 10px; padding: 20px; }"
            )
            self._loading_overlay.setVisible(False)
        else:
            from .mpl_missing import MatplotlibMissing

            self.matplotlib_missing = MatplotlibMissing(self)
            self.matplotlib_missing.installed.connect(lambda _version: self._parent_panel._rebuild_chart_dock())
            chart_stack.addWidget(self.matplotlib_missing, stretch=1)
            self.figure = None
            self.canvas_plot = None

        self.x_range_bar = AxisRangeBar(orientation="horizontal", label="X")
        self.x_range_bar.rangeChanged.connect(self._on_x_range_changed)
        chart_stack.addWidget(self.x_range_bar)

        chart_area.addLayout(chart_stack, stretch=1)
        layout.addLayout(chart_area, stretch=1)

    def _build_rgb_strip(self, layout):
        """RGB mode options: Auto, percentiles, Min/Max, gamma and dot size."""
        self.rgb_config_widget = QWidget()
        rgb_cfg_lay = QHBoxLayout(self.rgb_config_widget)
        rgb_cfg_lay.setContentsMargins(4, 2, 4, 2)
        rgb_cfg_lay.setSpacing(4)

        _spin_style = """
            QSpinBox {
                border: 1px solid #bdc3c7; border-radius: 3px; background: white;
                font-size: 9px; min-width: 48px; max-width: 58px; padding: 1px 2px;
            }
        """
        self.rgb_config_widget.setStyleSheet("""
            QWidget { background: #ecf0f1; border-radius: 3px; border: 1px solid #bdc3c7; }
            QLabel { border: none; background: transparent; font-size: 9px; font-weight: bold; color: #444; }
        """)
        self.rgb_config_widget.setFixedHeight(_OPTIONS_ROW_HEIGHT)
        self.rgb_config_widget.setVisible(False)

        self._rgb_user_adjusted = False

        self._rgb_auto_btn = QPushButton("Auto")
        self._rgb_auto_btn.setToolTip(
            "Automatic colors: each band stretched between the percentiles below,\n"
            "computed on the dates without clouds. Editing Min/Max fixes one range\n"
            "for the three bands, in the chart's units."
        )
        self._rgb_auto_btn.setFixedWidth(44)
        self._rgb_auto_btn.clicked.connect(self._on_rgb_auto_clicked)
        rgb_cfg_lay.addWidget(self._rgb_auto_btn)

        rgb_cfg_lay.addWidget(QLabel("P%: "))
        self._rgb_pct_low_spin = QSpinBox()
        self._rgb_pct_low_spin.setRange(0, 49)
        self._rgb_pct_low_spin.setValue(2)
        self._rgb_pct_low_spin.setSuffix("%")
        self._rgb_pct_low_spin.setStyleSheet(_spin_style)
        self._rgb_pct_low_spin.valueChanged.connect(self._on_rgb_pct_changed)
        rgb_cfg_lay.addWidget(self._rgb_pct_low_spin)

        rgb_cfg_lay.addWidget(QLabel("–"))

        self._rgb_pct_high_spin = QSpinBox()
        self._rgb_pct_high_spin.setRange(51, 100)
        self._rgb_pct_high_spin.setValue(98)
        self._rgb_pct_high_spin.setSuffix("%")
        self._rgb_pct_high_spin.setStyleSheet(_spin_style)
        self._rgb_pct_high_spin.valueChanged.connect(self._on_rgb_pct_changed)
        rgb_cfg_lay.addWidget(self._rgb_pct_high_spin)

        rgb_cfg_lay.addWidget(QLabel(" Min:"))
        self._rgb_min_spin = QSpinBox()
        self._rgb_min_spin.setRange(-10000, 50000)
        self._rgb_min_spin.setValue(0)
        self._rgb_min_spin.setStyleSheet(_spin_style)
        self._rgb_min_spin.valueChanged.connect(self._on_rgb_spin_changed)
        rgb_cfg_lay.addWidget(self._rgb_min_spin)

        rgb_cfg_lay.addWidget(QLabel("Max:"))
        self._rgb_max_spin = QSpinBox()
        self._rgb_max_spin.setRange(-10000, 50000)
        self._rgb_max_spin.setValue(10000)
        self._rgb_max_spin.setStyleSheet(_spin_style)
        self._rgb_max_spin.valueChanged.connect(self._on_rgb_spin_changed)
        rgb_cfg_lay.addWidget(self._rgb_max_spin)

        rgb_cfg_lay.addWidget(QLabel("\u03b3:"))
        self._rgb_gamma_user = False
        self._rgb_gamma_spin = QDoubleSpinBox()
        self._rgb_gamma_spin.setRange(0.3, 3.0)
        self._rgb_gamma_spin.setSingleStep(0.05)
        self._rgb_gamma_spin.setDecimals(2)
        self._rgb_gamma_spin.setValue(1.0)
        self._rgb_gamma_spin.setToolTip(
            "Brightness of the dots: below 1 brightens, above 1 darkens.\n"
            "Auto brightens series whose clear dates are dark (dense vegetation)."
        )
        self._rgb_gamma_spin.setStyleSheet(_spin_style)
        self._rgb_gamma_spin.valueChanged.connect(self._on_rgb_gamma_changed)
        rgb_cfg_lay.addWidget(self._rgb_gamma_spin)

        rgb_cfg_lay.addWidget(QLabel("Pts:"))
        self._rgb_pt_spin = QSpinBox()
        self._rgb_pt_spin.setRange(20, 500)
        self._rgb_pt_spin.setValue(120)
        self._rgb_pt_spin.setSingleStep(10)
        self._rgb_pt_spin.setStyleSheet(_spin_style)
        self._rgb_pt_spin.valueChanged.connect(self._schedule_deferred_replot)
        rgb_cfg_lay.addWidget(self._rgb_pt_spin)

        rgb_cfg_lay.addStretch()
        layout.addWidget(self.rgb_config_widget)

    def _build_line_strip(self, layout):
        """Line mode options: one checkbox per band."""
        self.line_config_widget = QWidget()
        line_cfg_lay = QHBoxLayout(self.line_config_widget)
        line_cfg_lay.setContentsMargins(4, 2, 4, 2)
        line_cfg_lay.setSpacing(4)
        self.line_config_widget.setStyleSheet("""
            QWidget { background: #ecf0f1; border-radius: 3px; border: 1px solid #bdc3c7; }
            QLabel  { border: none; background: transparent; font-size: 9px; font-weight: bold; color: #444; }
        """)
        self.line_config_widget.setFixedHeight(_OPTIONS_ROW_HEIGHT)
        self.line_config_widget.setVisible(False)

        self._hidden_bands = set()

        _bands_hdr = QLabel("Bands:")
        _bands_hdr.setStyleSheet("border:none; background:transparent; font-size:9px; font-weight:bold; color:#444;")
        line_cfg_lay.addWidget(_bands_hdr)

        # Scrollable inline band checkboxes
        self._line_bands_scroll = QScrollArea()
        self._line_bands_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._line_bands_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._line_bands_scroll.setWidgetResizable(True)
        self._line_bands_scroll.setFixedHeight(30)
        self._line_bands_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self._line_bands_inner = QWidget()
        self._line_bands_inner.setStyleSheet("background: transparent;")
        self._line_bands_hlay = QHBoxLayout(self._line_bands_inner)
        self._line_bands_hlay.setContentsMargins(2, 0, 2, 0)
        self._line_bands_hlay.setSpacing(6)
        self._line_bands_cbs = {}  # band_name -> QCheckBox
        self._line_bands_scroll.setWidget(self._line_bands_inner)
        line_cfg_lay.addWidget(self._line_bands_scroll, stretch=1)

        layout.addWidget(self.line_config_widget)

    def _build_export_row(self, layout):
        """Point label and the CSV and GPKG export buttons."""
        bottom_row = QHBoxLayout()
        self.viz_point_label = QLabel("")
        self.viz_point_label.setStyleSheet("font-size: 9px; color: #555; border: none; background: transparent;")
        bottom_row.addWidget(self.viz_point_label)
        bottom_row.addStretch()

        self.export_csv_btn = QPushButton("CSV")
        self.export_csv_btn.setFixedHeight(22)
        self.export_csv_btn.setStyleSheet(_EXPORT_CSV_BTN_STYLE)
        self.export_csv_btn.clicked.connect(self._parent_panel._export_csv)
        self.export_csv_btn.setEnabled(False)
        bottom_row.addWidget(self.export_csv_btn)

        self.export_shp_btn = QPushButton("GPKG")
        self.export_shp_btn.setFixedHeight(22)
        self.export_shp_btn.setStyleSheet(_EXPORT_SHP_BTN_STYLE)
        self.export_shp_btn.setToolTip("Export complete time series as GeoPackage")
        self.export_shp_btn.clicked.connect(self._parent_panel._export_gpkg)
        self.export_shp_btn.setEnabled(False)
        bottom_row.addWidget(self.export_shp_btn)

        layout.addLayout(bottom_row)

    def _connect_controls(self):
        """Signals of the controls and the debounce and throttle timers."""
        # Bind events — only rgb_mode_btn.toggled needed (fires for both transitions)
        self.rgb_mode_btn.toggled.connect(self._on_mode_changed)
        # RGB combos go through debounce to avoid multiple simultaneous fetch calls
        self.rgb_r_combo.currentIndexChanged.connect(self._on_rgb_combo_setting_changed)
        self.rgb_g_combo.currentIndexChanged.connect(self._on_rgb_combo_setting_changed)
        self.rgb_b_combo.currentIndexChanged.connect(self._on_rgb_combo_setting_changed)
        self.rgb_y_combo.currentIndexChanged.connect(self._on_rgb_combo_setting_changed)
        self._combo_debounce_timer = QTimer(self)
        self._combo_debounce_timer.setSingleShot(True)
        self._combo_debounce_timer.timeout.connect(self._fire_rgb_combo_changed)

        # Full plot reconstruction is relatively expensive. RGB controls use a
        # trailing debounce, while range drags use a 30 FPS throttle and update
        # only the existing axes.
        self._replot_debounce_timer = QTimer(self)
        self._replot_debounce_timer.setSingleShot(True)
        self._replot_debounce_timer.timeout.connect(self._fire_deferred_replot)
        self._axis_refresh_timer = QTimer(self)
        self._axis_refresh_timer.setSingleShot(True)
        self._axis_refresh_timer.timeout.connect(self._fire_axis_refresh)

        self._on_mode_changed()
