# -*- coding: utf-8 -*-
"""
TSHistoryManager — History management for the time series panel.

Handles the extraction history list, settings dialog, context menus,
and entry removal/clearing.
"""

import logging

_logger = logging.getLogger("bdc_loader")

from qgis.core import QgsProject
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QWidget,
)

from ..i18n import count_label, set_text, tr
from ..widgets.dialogs import HistorySettingsDialog


class TSHistoryManager:
    """History list management, settings, and entry manipulation."""

    def _show_history_settings(self):
        dlg = HistorySettingsDialog(self._hist_settings, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._hist_settings = dlg.get_settings()
            self._apply_layer_style()
            self._set_status("History settings saved.", "success")

    def _refresh_history_list(self):
        self.history_list.blockSignals(True)
        self.history_list.clear()
        for entry in self._history:
            n_vals = sum(len(v) for v in entry["data"].values())
            text = (
                f"#{entry['id']} {entry['label']} "
                f"({entry['lon']:.4f}, {entry['lat']:.4f}) "
                f"| {entry['collection']} | {len(entry['bands'])}b | {n_vals}v"
            )
            item_widget = QWidget()
            item_layout = QHBoxLayout(item_widget)
            item_layout.setContentsMargins(2, 1, 2, 1)
            item_layout.setSpacing(3)
            lbl = QLabel(text)
            lbl.setStyleSheet("font-size: 9px; border: none; background: transparent;")
            item_layout.addWidget(lbl, stretch=1)
            remove_btn = QPushButton("\u2716")
            remove_btn.setFixedSize(16, 16)
            remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            remove_btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent; border: none;
                    color: #e74c3c; font-size: 10px; font-weight: bold;
                }
                QPushButton:hover { color: #c0392b; background-color: #f5b7b1; border-radius: 3px; }
            """)
            eid = entry["id"]
            set_text(remove_btn, f"Remove #{eid}", "tip")
            remove_btn.clicked.connect(lambda checked, hid=eid: self._remove_history_entry(hid))
            item_layout.addWidget(remove_btn)

            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, entry["id"])
            item.setSizeHint(item_widget.sizeHint())
            self.history_list.addItem(item)
            self.history_list.setItemWidget(item, item_widget)
        self.history_list.blockSignals(False)

        if 0 <= self._current_viz_index < self.history_list.count():
            self.history_list.setCurrentRow(self._current_viz_index)

    def _on_history_selected(self, row):
        if row < 0 or row >= len(self._history):
            return
        self._current_viz_index = row
        entry = self._history[row]
        self._update_viz_navigation()
        self._ensure_chart_dock()
        self._update_rgb_combos(entry["bands"], entry.get("collection", ""))
        self.chart_dock.reset_axis_ranges()
        self._plot_result(entry)
        if self._auto_center:
            self._zoom_to_point(entry["lon"], entry["lat"])

    def _history_context_menu(self, pos):
        item = self.history_list.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        zoom_action = menu.addAction(tr("Zoom to point"))
        copy_action = menu.addAction(tr("Copy coordinates"))
        remove_action = menu.addAction(tr("Remove from history"))
        action = menu.exec(self.history_list.mapToGlobal(pos))
        hist_id = item.data(Qt.ItemDataRole.UserRole)

        if action == zoom_action:
            for entry in self._history:
                if entry["id"] == hist_id:
                    self._zoom_to_point(entry["lon"], entry["lat"])
                    break
        elif action == copy_action:
            for entry in self._history:
                if entry["id"] == hist_id:
                    QApplication.clipboard().setText(f"{entry['lon']:.6f}, {entry['lat']:.6f}")
                    self._set_status(f"Coordinates copied: {entry['lon']:.6f}, {entry['lat']:.6f}.", "success")
                    break
        elif action == remove_action:
            self._remove_history_entry(hist_id)

    def _remove_history_entry(self, hist_id):
        shown = None
        if 0 <= self._current_viz_index < len(self._history):
            shown = self._history[self._current_viz_index]
        self._history = [e for e in self._history if e["id"] != hist_id]
        self._remove_point_from_temp_layer(hist_id)
        if not self._history:
            self._current_viz_index = -1
        elif shown is not None and shown["id"] != hist_id:
            # Keep showing the same series when another one is removed.
            self._current_viz_index = self._history.index(shown)
        else:
            self._current_viz_index = min(max(self._current_viz_index, 0), len(self._history) - 1)
        self._refresh_history_list()
        self._update_viz_navigation()
        if self._history and self.chart_dock:
            entry = self._history[self._current_viz_index]
            if entry is not shown:
                self._update_rgb_combos(entry["bands"], entry.get("collection", ""))
                self.chart_dock.reset_axis_ranges()
            self._plot_result(entry)
        elif self.chart_dock and self.chart_dock.figure:
            self.chart_dock.figure.clear()
            self.chart_dock.canvas_plot.draw_idle()
            self.chart_dock.export_csv_btn.setEnabled(False)
            self.chart_dock.export_shp_btn.setEnabled(False)
        self._set_status(
            f"Point #{hist_id} removed; the history has {count_label(len(self._history), 'point', 'points')}.", "info"
        )

    def _clear_history(self):
        self._history.clear()
        self._history_counter = 0
        self._current_viz_index = -1
        self._refresh_history_list()
        self._update_viz_navigation()

        if self._temp_layer:
            try:
                QgsProject.instance().removeMapLayer(self._temp_layer.id())
            except Exception as _e:
                _logger.debug("Failed to remove temp point layer: %s", _e)
            self._temp_layer = None

        if self.chart_dock and self.chart_dock.figure:
            self.chart_dock.figure.clear()
            self.chart_dock.canvas_plot.draw_idle()
            self.chart_dock.export_csv_btn.setEnabled(False)
            self.chart_dock.export_shp_btn.setEnabled(False)

        self._set_status("History cleared.", "info")
