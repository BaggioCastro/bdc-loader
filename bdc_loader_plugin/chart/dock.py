"""Chart dock widget for BDC time series visualization."""

import logging

_logger = logging.getLogger("bdc_loader")

from qgis.PyQt.QtCore import QPoint, QSize, Qt, QTimer
from qgis.PyQt.QtGui import QCursor
from qgis.PyQt.QtWidgets import (
    QApplication,
    QCheckBox,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
)

from ..i18n import set_text
from ..widgets.cursors import apply_click_cursors
from ..widgets.icons import close_icon, dock_icon, float_icon, minimize_icon, restore_icon
from .dock_layout import ChartDockLayout
from .dock_widgets import (
    _MODE_BTN_CHECKED,
    _MODE_BTN_UNCHECKED,
    _TITLE_BAR_STYLE,
    _DraggableDockTitleBar,
)
from .plot import BAND_COLORS


class ChartDock(ChartDockLayout, QDockWidget):
    """
    A separate QDockWidget containing the visual plots, movable and resizable.
    Keeps an explicit reference to its parent panel to invoke replots and updates.
    """

    def __init__(self, parent_panel, parent=None):
        super().__init__("BDC Chart", parent)
        self._parent_panel = parent_panel
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.BottomDockWidgetArea
            | Qt.DockWidgetArea.TopDockWidgetArea
        )
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.setMinimumSize(250, 150)
        self._y_range = None
        self._x_range = None
        self._y_user_adjusted = False
        self._x_user_adjusted = False
        self._range_locked = False
        self._collapsed = False

        self._setup_custom_title_bar()
        self._setup_ui()

    def closeEvent(self, event):
        """Override close to hide instead of destroy."""
        self.setVisible(False)
        event.ignore()

    def _setup_custom_title_bar(self):
        title_bar = _DraggableDockTitleBar(self)
        title_bar.setObjectName("bdcChartTitleBar")
        # Paint the bar itself; a plain "QWidget" rule would paint each child instead.
        title_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        title_bar.setStyleSheet(_TITLE_BAR_STYLE)
        title_lay = QHBoxLayout(title_bar)
        title_lay.setContentsMargins(10, 4, 4, 4)
        title_lay.setSpacing(4)
        lbl = QLabel("BDC Time Series — Chart")
        lbl.setStyleSheet("color: white; font-weight: bold; font-size: 11px; background: transparent;")
        lbl.setMinimumWidth(40)
        lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        title_lay.addWidget(lbl, stretch=1)

        _title_btn_style = """
            QPushButton {{
                background: {bg}; border: none; border-radius: 3px;
                min-width: 22px; max-width: 22px; min-height: 18px; max-height: 18px;
            }}
            QPushButton:hover {{ background: {hover}; }}
        """

        def _title_button(icon, tooltip, bg, hover, slot):
            btn = QPushButton()
            btn.setIcon(icon)
            btn.setIconSize(QSize(12, 12))
            btn.setToolTip(tooltip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(_title_btn_style.format(bg=bg, hover=hover))
            btn.clicked.connect(slot)
            title_lay.addWidget(btn)
            return btn

        self._minimize_btn = _title_button(minimize_icon(), "Minimize", "#57606a", "#484f58", self._minimize_dock)
        self._float_btn = _title_button(float_icon(), "Float", "#57606a", "#484f58", self._toggle_float)
        self._close_btn = _title_button(close_icon(), "Close", "#c0392b", "#e74c3c", self.close)
        self.topLevelChanged.connect(self._update_float_button)

        self.setTitleBarWidget(title_bar)

    @staticmethod
    def _wrap_in_horizontal_scroll(bar):
        """Let a fixed-height control bar scroll sideways instead of forcing the dock's minimum width.

        The scroll area grows by the scroll bar height only while the bar is wider
        than the dock, so a wide dock looks the same as without it.
        """
        scroll = QScrollArea()
        scroll.setWidget(bar)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        bar_height = bar.height() if bar.minimumHeight() == bar.maximumHeight() else bar.sizeHint().height()
        scrollbar = scroll.horizontalScrollBar()

        def _fit_height(_minimum=0, maximum=0):
            extra = scrollbar.sizeHint().height() if maximum > 0 else 0
            scroll.setFixedHeight(bar_height + extra)

        scrollbar.rangeChanged.connect(_fit_height)
        _fit_height()
        return scroll

    def _update_float_button(self, floating):
        self._float_btn.setIcon(dock_icon() if floating else float_icon())
        self._float_btn.setToolTip("Dock" if floating else "Float")
        if floating:
            QTimer.singleShot(0, self._keep_on_screen)

    def _keep_on_screen(self):
        """Move and shrink a floating chart so it stays inside the available screen area."""
        if not self.isFloating():
            return
        screen = QApplication.screenAt(self.geometry().center()) or self.screen()
        if screen is None:
            return
        area = screen.availableGeometry()
        geom = self.geometry()
        width = min(geom.width(), area.width())
        height = min(geom.height(), area.height())
        x = min(max(geom.x(), area.left()), area.right() - width + 1)
        y = min(max(geom.y(), area.top()), area.bottom() - height + 1)
        if (x, y, width, height) != (geom.x(), geom.y(), geom.width(), geom.height()):
            self.setGeometry(x, y, width, height)

    def _minimize_dock(self):
        """Collapse to the title bar, or expand back, keeping width and position."""
        if self._collapsed:
            self._restore_from_collapse()
            return
        self._saved_geometry = self.geometry()
        width = self.width()
        self.widget().setVisible(False)
        title_h = self.titleBarWidget().sizeHint().height() + 4
        self.setMinimumSize(width, 0)
        self.setMaximumHeight(title_h)
        if self.isFloating():
            self.setGeometry(self._saved_geometry.x(), self._saved_geometry.y(), width, title_h)
        self._collapsed = True
        self._minimize_btn.setIcon(restore_icon())
        set_text(self._minimize_btn, "Restore", "tip")

    def _restore_from_collapse(self):
        """Restore dock from collapsed state if needed."""
        if not self._collapsed:
            return
        self.widget().setVisible(True)
        self.setMinimumSize(250, 150)
        self.setMaximumHeight(16777215)  # QWIDGETSIZE_MAX
        saved = getattr(self, "_saved_geometry", None)
        if self.isFloating() and saved is not None:
            self.setGeometry(saved)
            self._keep_on_screen()
        self._collapsed = False
        self._minimize_btn.setIcon(minimize_icon())
        set_text(self._minimize_btn, "Minimize", "tip")

    def _toggle_float(self):
        """Toggle between floating and docked."""
        self._restore_from_collapse()
        self.setFloating(not self.isFloating())

    def _update_mode_btn_styles(self):
        self.line_mode_btn.setStyleSheet(_MODE_BTN_CHECKED if self.line_mode_btn.isChecked() else _MODE_BTN_UNCHECKED)
        self.rgb_mode_btn.setStyleSheet(_MODE_BTN_CHECKED if self.rgb_mode_btn.isChecked() else _MODE_BTN_UNCHECKED)

    def _on_rgb_combo_setting_changed(self):
        """Debounce combo index changes — prevents 3 rapid-fire fetch calls."""
        self._combo_debounce_timer.start(160)

    def _fire_rgb_combo_changed(self):
        """Called once after debounce — triggers fetch+replot in parent panel."""
        if self._parent_panel:
            self._parent_panel._on_rgb_combo_changed()

    def _schedule_deferred_replot(self, *_args):
        """Coalesce expensive full redraws caused by rapid control changes."""
        self._replot_debounce_timer.start(90)

    def _fire_deferred_replot(self):
        if self._parent_panel:
            self._parent_panel._replot_current()

    def _schedule_axis_refresh(self):
        """Throttle range dragging while retaining live feedback."""
        if not self._axis_refresh_timer.isActive():
            self._axis_refresh_timer.start(33)

    def _fire_axis_refresh(self):
        if self._parent_panel:
            self._parent_panel._refresh_chart_ranges()

    def _on_mode_changed(self):
        is_rgb = self.rgb_mode_btn.isChecked()
        self.rgb_r_combo.setEnabled(is_rgb)
        self.rgb_g_combo.setEnabled(is_rgb)
        self.rgb_b_combo.setEnabled(is_rgb)
        self.rgb_y_combo.setEnabled(is_rgb)
        self.set_rgb_mode(is_rgb)
        self._update_mode_btn_styles()
        if not self._parent_panel:
            return
        if is_rgb:
            # Apply RGB preset — if bands are missing, _on_rgb_combo_changed will download them
            try:
                cid = None
                all_bands = []
                idx = self._parent_panel._current_viz_index
                hist = self._parent_panel._history
                if 0 <= idx < len(hist):
                    entry = hist[idx]
                    cid = entry.get("collection", "")
                    all_bands = entry.get("bands", [])
                # Keep a composition the user picked; preset only empty combos.
                combos = (self.rgb_r_combo, self.rgb_g_combo, self.rgb_b_combo)
                if (cid or all_bands) and not all(combo.currentData() for combo in combos):
                    self._parent_panel._try_preset_rgb(cid, all_bands)
            except Exception as exc:
                _logger.debug("RGB preset failed: %s", exc)
            # _try_preset_rgb may or may not change combos — always trigger fetch+replot
            self._combo_debounce_timer.stop()
            self._parent_panel._on_rgb_combo_changed()
        else:
            self._parent_panel._replot_current()

    def set_rgb_mode(self, is_rgb):
        rows = [getattr(self, name, None) for name in ("line_config_widget", "rgb_config_widget")]
        leaving, coming = rows if is_rgb else rows[::-1]
        # Hidden first: shown together for a moment, the two rows make the main
        # window give the dock their joint height, and it keeps it.
        if leaving is not None:
            leaving.setVisible(False)
        if coming is not None:
            coming.setVisible(True)

    def show_loading_overlay(self, text="Extracting RGB bands..."):
        """Show loading overlay on canvas, in the interface language."""
        if hasattr(self, "_loading_overlay") and self._loading_overlay:
            set_text(self._loading_overlay, text)
            self._loading_overlay.setVisible(True)
            self._loading_overlay.raise_()
            # Center overlay
            if self.canvas_plot:
                cw = self.canvas_plot.width()
                ch = self.canvas_plot.height()
                ow = min(300, cw - 20)
                oh = min(80, ch - 20)
                self._loading_overlay.setGeometry((cw - ow) // 2, (ch - oh) // 2, ow, oh)

    def hide_loading_overlay(self):
        """Hide loading overlay."""
        if hasattr(self, "_loading_overlay") and self._loading_overlay:
            self._loading_overlay.setVisible(False)

    def _on_band_toggled(self, band_name, checked):
        if checked:
            self._hidden_bands.discard(band_name)
        else:
            self._hidden_bands.add(band_name)
        self._schedule_deferred_replot()

    def refresh_line_bands(self, bands):
        """Rebuild inline band checkboxes from extracted band list."""
        # Clear existing checkboxes
        for cb in list(self._line_bands_cbs.values()):
            self._line_bands_hlay.removeWidget(cb)
            cb.deleteLater()
        self._line_bands_cbs = {}
        # Remove old stretch
        while self._line_bands_hlay.count():
            item = self._line_bands_hlay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for i, band in enumerate(bands):
            color = BAND_COLORS[i % len(BAND_COLORS)]
            cb = QCheckBox(band)
            cb.setChecked(band not in self._hidden_bands)
            cb.setStyleSheet(f"""
                QCheckBox {{
                    font-size: 9px; color: {color}; font-weight: bold;
                }}
                QCheckBox::indicator {{
                    width: 12px; height: 12px; border-radius: 2px;
                }}
                QCheckBox::indicator:checked {{
                    background-color: {color}; border: 1px solid {color};
                }}
                QCheckBox::indicator:unchecked {{
                    background-color: white; border: 1px solid {color};
                }}
            """)
            cb.toggled.connect(lambda checked, b=band: self._on_band_toggled(b, checked))
            self._line_bands_cbs[band] = cb
            self._line_bands_hlay.addWidget(cb)
        self._line_bands_hlay.addStretch()
        apply_click_cursors(self)

    def get_rgb_params(self):
        """Returns bounds rendering configs dictating RGB stretch layout constraints."""
        try:
            u_min = self._rgb_min_spin.value()
            u_max = self._rgb_max_spin.value()
            u_pt = self._rgb_pt_spin.value()
            pct_low = self._rgb_pct_low_spin.value()
            pct_high = self._rgb_pct_high_spin.value()
        except Exception:
            u_min, u_max, u_pt, pct_low, pct_high = 0, 10000, 120, 2, 98
        return u_min, u_max, u_pt, pct_low, pct_high

    def _on_rgb_spin_changed(self):
        self._rgb_user_adjusted = True
        self._schedule_deferred_replot()

    def _on_rgb_pct_changed(self):
        self._rgb_user_adjusted = False
        self._schedule_deferred_replot()

    def _on_rgb_auto_clicked(self):
        """Back to the automatic stretch and brightness with the current percentiles."""
        self._rgb_user_adjusted = False
        self._rgb_gamma_user = False
        self._schedule_deferred_replot()

    def _on_rgb_gamma_changed(self):
        self._rgb_gamma_user = True
        self._schedule_deferred_replot()

    def _sync_range_bars(self, _event=None):
        """Line the X and Y range bars up with the plot area of the chart."""
        canvas = getattr(self, "canvas_plot", None)
        if canvas is None or not self.figure or not self.figure.axes:
            for bar in (getattr(self, "x_range_bar", None), getattr(self, "y_range_bar", None)):
                if bar is not None:
                    bar.set_track_span(None, None)
            return
        try:
            box = self.figure.axes[0].get_window_extent()
            ratio = getattr(canvas, "device_pixel_ratio", None) or canvas.devicePixelRatioF() or 1.0
            height = canvas.height()
            left, right = box.x0 / ratio, box.x1 / ratio
            top, bottom = height - box.y1 / ratio, height - box.y0 / ratio
            origin = canvas.mapToGlobal(QPoint(0, 0))
            x_bar = self.x_range_bar.mapFromGlobal(origin).x()
            y_bar = self.y_range_bar.mapFromGlobal(origin).y()
            self.x_range_bar.set_track_span(x_bar + left, x_bar + right)
            self.y_range_bar.set_track_span(y_bar + top, y_bar + bottom)
        except Exception as exc:
            _logger.debug("Could not align the range bars with the plot: %s", exc)

    def _on_y_range_changed(self, ymin, ymax):
        self._y_range = (ymin, ymax)
        self._y_user_adjusted = True
        self._schedule_axis_refresh()

    def _on_x_range_changed(self, xmin, xmax):
        self._x_range = (xmin, xmax)
        self._x_user_adjusted = True
        self._schedule_axis_refresh()

    def _on_range_lock_toggled(self, locked):
        """Switch between per-series dynamic axes and a fixed user range."""
        self._range_locked = bool(locked)
        if locked:
            self._y_range = self.y_range_bar.get_view_range()
            self._x_range = self.x_range_bar.get_view_range()
            self._y_user_adjusted = True
            self._x_user_adjusted = True
            set_text(self.range_lock_btn, "Range locked")
            return

        set_text(self.range_lock_btn, "Dynamic range")
        self.reset_axis_ranges(force=True)
        if self._parent_panel:
            self._parent_panel._replot_current()

    def update_axis_ranges_from_data(self, all_dates, all_values):
        """Updates internal mapping elements resolving dynamic zoom boundaries on render queues"""
        if all_values:
            ymin = min(all_values)
            ymax = max(all_values)
            margin = (ymax - ymin) * 0.10 if ymax > ymin else 0.5
            data_ymin = ymin - margin
            data_ymax = ymax + margin
            if self._range_locked and self._y_range:
                data_ymin = min(data_ymin, self._y_range[0])
                data_ymax = max(data_ymax, self._y_range[1])
            self.y_range_bar.set_data_range(data_ymin, data_ymax)
            self.y_range_bar.set_format_fn(lambda v: f"{v:.2f}")

            if self._y_user_adjusted and self._y_range:
                self.y_range_bar.set_view_range(self._y_range[0], self._y_range[1])

        if all_dates:
            from matplotlib.dates import date2num, num2date

            d_nums = [date2num(d) for d in all_dates]
            dmin = min(d_nums)
            dmax = max(d_nums)
            margin_d = (dmax - dmin) * 0.02 if dmax > dmin else 1
            data_xmin = dmin - margin_d
            data_xmax = dmax + margin_d
            if self._range_locked and self._x_range:
                data_xmin = min(data_xmin, self._x_range[0])
                data_xmax = max(data_xmax, self._x_range[1])
            self.x_range_bar.set_data_range(data_xmin, data_xmax)

            def fmt_date(v):
                try:
                    dt = num2date(v)
                    return dt.strftime("%d/%m/%y")
                except Exception:
                    return f"{v:.0f}"

            self.x_range_bar.set_format_fn(fmt_date)

            if self._x_user_adjusted and self._x_range:
                self.x_range_bar.set_view_range(self._x_range[0], self._x_range[1])

    def get_effective_y_range(self):
        return self._y_range

    def get_effective_x_range(self):
        return self._x_range

    def reset_axis_ranges(self, force=False):
        if self._range_locked and not force:
            return
        self._y_range = None
        self._x_range = None
        self._y_user_adjusted = False
        self._x_user_adjusted = False
        self.y_range_bar.blockSignals(True)
        self.x_range_bar.blockSignals(True)
        self.y_range_bar.reset()
        self.x_range_bar.reset()
        self.y_range_bar.blockSignals(False)
        self.x_range_bar.blockSignals(False)

    def _on_chart_click(self, event):
        """Double-click handler: snap to nearest point and load VRT."""
        if event.dblclick and event.inaxes and self._parent_panel:
            from matplotlib.dates import num2date

            try:
                ax = event.inaxes
                click_x = event.xdata
                click_y = event.ydata

                # Collect all visible data points
                best_dist = float("inf")
                best_x = click_x
                best_y = click_y

                # Normalize to visual space
                xlim = ax.get_xlim()
                ylim = ax.get_ylim()
                x_span = xlim[1] - xlim[0] if xlim[1] != xlim[0] else 1
                y_span = ylim[1] - ylim[0] if ylim[1] != ylim[0] else 1

                for line in ax.get_lines():
                    xd = line.get_xdata()
                    yd = line.get_ydata()
                    if len(xd) == 0:
                        continue
                    for xi, yi in zip(xd, yd):
                        xn = float(xi)
                        yn = float(yi)
                        dx = (xn - click_x) / x_span
                        dy = (yn - click_y) / y_span
                        dist = dx * dx + dy * dy
                        if dist < best_dist:
                            best_dist = dist
                            best_x = xn
                            best_y = yn

                # Check scatter collections (RGB mode)
                for coll in ax.collections:
                    offsets = coll.get_offsets()
                    if offsets is not None and len(offsets) > 0:
                        for off in offsets:
                            xn, yn = float(off[0]), float(off[1])
                            dx = (xn - click_x) / x_span
                            dy = (yn - click_y) / y_span
                            dist = dx * dx + dy * dy
                            if dist < best_dist:
                                best_dist = dist
                                best_x = xn
                                best_y = yn

                # Snap to nearest point
                clicked_date = num2date(best_x).replace(tzinfo=None)
                self._show_halo_highlight(ax, best_x, best_y)
                self.canvas_plot.setCursor(QCursor(Qt.CursorShape.WaitCursor))
                self._parent_panel._on_chart_date_clicked(clicked_date)
            except Exception as _e:
                _logger.error("Error handling chart date click: %s", _e, exc_info=True)
            finally:
                self.canvas_plot.unsetCursor()

    def _show_halo_highlight(self, ax, xdata, ydata):
        """Draw persistent halo around nearest data point."""
        self._remove_click_highlight()

        halo = ax.plot(
            xdata,
            ydata,
            "o",
            color="#e74c3c",
            markersize=22,
            alpha=0.35,
            markeredgecolor="#e74c3c",
            markeredgewidth=2.5,
            markerfacecolor="none",
            zorder=15,
        )

        self._click_highlight = {"halo": halo[0]}
        self.canvas_plot.draw_idle()

    def _remove_click_highlight(self):
        """Remove click highlight."""
        hl = getattr(self, "_click_highlight", None)
        if hl:
            try:
                for key in ("halo", "inner", "vline", "marker"):
                    artist = hl.get(key)
                    if artist:
                        artist.remove()
                if self.canvas_plot:
                    self.canvas_plot.draw_idle()
            except Exception:
                pass
            self._click_highlight = None
