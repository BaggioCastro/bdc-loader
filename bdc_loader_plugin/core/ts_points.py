# -*- coding: utf-8 -*-
"""
TSPointManager — Point management for the time series panel.

Handles map picker tool, coordinate input, WKT parsing, vector file loading,
and point list manipulation.
"""

import logging
import os

_logger = logging.getLogger("bdc_loader")

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QEvent, Qt, QTimer
from qgis.PyQt.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QWidget,
)

from ..i18n import count_label, tr
from ..timing import AFTER_HANDLER_MS
from ..widgets.point_picker import PointPickerTool


class TSPointManager:
    """Point picking, coordinate entry, WKT parsing, and vector loading."""

    def _on_point_mode_changed(self, multi_checked):
        self._multi_point_mode = multi_checked
        self.single_point_btn.setStyleSheet(self._mode_unchecked_ss if multi_checked else self._mode_checked_ss)
        self.multi_point_btn.setStyleSheet(self._mode_checked_ss if multi_checked else self._mode_unchecked_ss)

    def eventFilter(self, source, event):
        if source is self.points_list and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                selected = self.points_list.selectedItems()
                if selected:
                    rows = sorted([self.points_list.row(it) for it in selected], reverse=True)
                    for row in rows:
                        self.points_list.takeItem(row)
                        if row < len(self._current_points):
                            self._current_points.pop(row)
                    self._set_status(
                        f"{count_label(len(self._current_points), 'point', 'points')} to extract.", "pending", 0
                    )
                    return True
        return super().eventFilter(source, event)

    def _toggle_picker(self, checked):
        canvas = self.iface.mapCanvas()
        if checked:
            self._previous_tool = canvas.mapTool()
            self._picker_tool = PointPickerTool(
                canvas,
                self._on_point_picked,
                on_deactivate=self._on_picker_deactivated,
            )
            canvas.setMapTool(self._picker_tool)
            self._set_status("Click a point on the map, or press Esc to stop the picker.", "pending", 0)
        else:
            if self._picker_tool:
                self._picker_tool.cancel("button")
            else:
                self._restore_picker_navigation()

    def _restore_picker_navigation(self):
        canvas = self.iface.mapCanvas()
        previous_tool = self._previous_tool
        self._previous_tool = None

        def _apply_restore():
            if previous_tool:
                try:
                    canvas.setMapTool(previous_tool)
                    return
                except Exception as _e:
                    _logger.debug("Could not restore previous map tool: %s", _e)
            try:
                self.iface.actionPan().trigger()
            except Exception as _e:
                _logger.debug("Could not trigger pan action: %s", _e)

        QTimer.singleShot(0, _apply_restore)

    def _on_picker_deactivated(self, reason=None):
        """Called when picker tool is deactivated (ESC, button or tool switch)."""
        self.pick_btn.blockSignals(True)
        self.pick_btn.setChecked(False)
        self.pick_btn.blockSignals(False)
        self._picker_tool = None
        if reason in ("escape", "button"):
            self._restore_picker_navigation()
            pending = len(self._current_points)
            if pending:
                self._set_status(f"Picker stopped: {count_label(pending, 'point', 'points')} to extract.", "pending", 0)
            else:
                self._set_status("Picker stopped.", "info")

    def _set_picker_loading(self, loading):
        if not self._picker_tool:
            return
        try:
            self._picker_tool.set_loading(loading)
        except Exception as _e:
            _logger.debug("Could not set picker loading state: %s", _e)

    def _extract_time_series_from_picker(self):
        try:
            self._extract_time_series(picker_overlay_text="Extracting time series...")
        finally:
            self._set_picker_loading(False)

    def _on_point_picked(self, point):
        canvas = self.iface.mapCanvas()
        src_crs = canvas.mapSettings().destinationCrs()
        dst_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        transform = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())
        point_4326 = transform.transform(point)
        lon = round(point_4326.x(), 6)
        lat = round(point_4326.y(), 6)

        self.lon_input.setText(f"{lon:.6f}")
        self.lat_input.setText(f"{lat:.6f}")

        if not self._multi_point_mode:
            self._current_points.clear()
            self.points_list.clear()
            self._add_point(lon, lat, f"P{len(self._current_points) + 1}")
            self._set_picker_loading(True)
            QTimer.singleShot(AFTER_HANDLER_MS, self._extract_time_series_from_picker)
        else:
            self._add_point(lon, lat, f"P{len(self._current_points) + 1}")

    def _add_point_from_coords(self):
        try:
            lon = float(self.lon_input.text().replace(",", "."))
            lat = float(self.lat_input.text().replace(",", "."))
        except ValueError:
            QMessageBox.warning(self, "Warning", "Invalid coordinates.")
            return
        if lon < -180 or lon > 180 or lat < -90 or lat > 90:
            QMessageBox.warning(self, "Warning", "Coordinates out of range.")
            return
        if not self._multi_point_mode:
            self._current_points.clear()
            self.points_list.clear()
        self._add_point(lon, lat, f"P{len(self._current_points) + 1}")

    def _copy_coords(self):
        lon_text = self.lon_input.text().strip()
        lat_text = self.lat_input.text().strip()
        if lon_text and lat_text:
            clipboard = QApplication.clipboard()
            clipboard.setText(f"{lon_text}, {lat_text}")
            self.copy_coord_btn.setStyleSheet("""
                QPushButton {
                    background-color: #27ae60; color: white;
                    border: none; border-radius: 3px; font-size: 11px;
                }
            """)
            self._set_status(f"Coordinates copied: {lon_text}, {lat_text}.", "success")
            QTimer.singleShot(
                1200,
                lambda: self.copy_coord_btn.setStyleSheet("""
                QPushButton {
                    background-color: #95a5a6; color: white;
                    border: none; border-radius: 3px; font-size: 11px;
                }
                QPushButton:hover { background-color: #7f8c8d; }
            """),
            )
        else:
            self._set_status("Enter Lon and Lat before copying.", "warning")

    def _add_point_from_wkt(self):
        wkt_text = self.wkt_input.text().strip()
        if not wkt_text:
            QMessageBox.warning(self, "Warning", "Enter a WKT POINT geometry.")
            return
        try:
            geom = QgsGeometry.fromWkt(wkt_text)
            if geom.isNull() or geom.wkbType() != QgsWkbTypes.Type.Point:
                raise ValueError("Not a valid POINT")
            point = geom.asPoint()
            lon = round(point.x(), 6)
            lat = round(point.y(), 6)
            if not self._multi_point_mode:
                self._current_points.clear()
                self.points_list.clear()
            self._add_point(lon, lat, f"P{len(self._current_points) + 1}")
            self.wkt_input.clear()
        except Exception as e:
            QMessageBox.warning(self, "Warning", f"Invalid WKT: {e}")

    def _load_vector(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Point Vector",
            "",
            "Vector files (*.gpkg *.shp);;GeoPackage (*.gpkg);;Shapefile (*.shp);;All files (*)",
        )
        if not path:
            return
        try:
            layer = QgsVectorLayer(path, "temp_points", "ogr")
            if not layer.isValid():
                QMessageBox.warning(self, "Warning", f"Cannot open file: {path}")
                return
            src_crs = layer.crs()
            dst_crs = QgsCoordinateReferenceSystem("EPSG:4326")
            transform = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())

            count = 0
            invalid_geom = False
            for feat in layer.getFeatures():
                geom = feat.geometry()
                if geom.isNull():
                    continue
                if geom.wkbType() in (QgsWkbTypes.Type.Point, QgsWkbTypes.Type.Point25D):
                    pt = geom.asPoint()
                    pt4326 = transform.transform(QgsPointXY(pt))
                    lon = round(pt4326.x(), 6)
                    lat = round(pt4326.y(), 6)
                    label = None
                    for fn in ["label", "name", "nome", "id", "ID"]:
                        idx_f = layer.fields().indexOf(fn)
                        if idx_f >= 0:
                            label = str(feat.attribute(idx_f))
                            break
                    if not label:
                        label = f"SHP-{count + 1}"
                    self._add_point(lon, lat, label)
                    count += 1
                elif geom.wkbType() in (QgsWkbTypes.Type.MultiPoint, QgsWkbTypes.Type.MultiPoint25D):
                    for pt in geom.asMultiPoint():
                        pt4326 = transform.transform(QgsPointXY(pt))
                        lon = round(pt4326.x(), 6)
                        lat = round(pt4326.y(), 6)
                        self._add_point(lon, lat, f"SHP-{count + 1}")
                        count += 1
                else:
                    invalid_geom = True

            if invalid_geom:
                QMessageBox.warning(
                    self,
                    "Mixed Geometry Warning",
                    "Line/polygon features were ignored.\n\n"
                    "Only Point geometries are supported.\n"
                    "Convert centroids or generate points if needed.",
                )

            self._set_status(
                f"{count_label(count, 'point', 'points')} loaded from {os.path.basename(path)}.", "success"
            )
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Error loading vector: {e}")

    def _add_point(self, lon, lat, label=""):
        for p in self._current_points:
            if abs(p[0] - lon) < 1e-6 and abs(p[1] - lat) < 1e-6:
                self._set_status(f"Duplicate point skipped: ({lon:.6f}, {lat:.6f}).", "warning")
                return
        self._current_points.append((lon, lat, label))

        item_widget = QWidget()
        item_layout = QHBoxLayout(item_widget)
        item_layout.setContentsMargins(2, 0, 2, 0)
        item_layout.setSpacing(2)
        lbl = QLabel(f"{label}: ({lon:.6f}, {lat:.6f})")
        lbl.setStyleSheet("font-size: 9px; border: none; background: transparent;")
        item_layout.addWidget(lbl, stretch=1)
        x_btn = QPushButton("\u2716")
        x_btn.setFixedSize(14, 14)
        x_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        x_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: #e74c3c; font-size: 9px; font-weight: bold; }"
            "QPushButton:hover { color: #c0392b; background: #f5b7b1; border-radius: 2px; }"
        )
        pt_idx = len(self._current_points) - 1
        x_btn.clicked.connect(lambda checked, r=pt_idx: self._remove_point_by_index(r))
        item_layout.addWidget(x_btn)

        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, (lon, lat))
        item.setSizeHint(item_widget.sizeHint())
        self.points_list.addItem(item)
        self.points_list.setItemWidget(item, item_widget)
        self._set_status(f"{count_label(len(self._current_points), 'point', 'points')} to extract.", "pending", 0)

    def _remove_point_by_index(self, idx):
        if idx < len(self._current_points):
            self._current_points.pop(idx)
        self._rebuild_points_list()
        self._set_status(f"{count_label(len(self._current_points), 'point', 'points')} to extract.", "pending", 0)

    def _rebuild_points_list(self):
        self.points_list.clear()
        for i, (lon, lat, label) in enumerate(self._current_points):
            item_widget = QWidget()
            item_layout = QHBoxLayout(item_widget)
            item_layout.setContentsMargins(2, 0, 2, 0)
            item_layout.setSpacing(2)
            lbl = QLabel(f"{label}: ({lon:.6f}, {lat:.6f})")
            lbl.setStyleSheet("font-size: 9px; border: none; background: transparent;")
            item_layout.addWidget(lbl, stretch=1)
            x_btn = QPushButton("\u2716")
            x_btn.setFixedSize(14, 14)
            x_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            x_btn.setStyleSheet(
                "QPushButton { background: transparent; border: none; color: #e74c3c; font-size: 9px; font-weight: bold; }"
                "QPushButton:hover { color: #c0392b; background: #f5b7b1; border-radius: 2px; }"
            )
            x_btn.clicked.connect(lambda checked, r=i: self._remove_point_by_index(r))
            item_layout.addWidget(x_btn)

            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, (lon, lat))
            item.setSizeHint(item_widget.sizeHint())
            self.points_list.addItem(item)
            self.points_list.setItemWidget(item, item_widget)

    def _on_point_double_clicked(self, item):
        coords = item.data(Qt.ItemDataRole.UserRole)
        if coords:
            self._zoom_to_point(coords[0], coords[1])

    def _clear_points(self):
        self._current_points.clear()
        self.points_list.clear()
        self.lon_input.clear()
        self.lat_input.clear()
        self._set_status("Points cleared.", "info")

    def _show_points_help(self):
        QMessageBox.information(
            self,
            "Points \u2014 Help & Features",
            "<b>\u25cf Map Picker:</b><br>"
            "Click the picker button, then click on the map to select a pixel.<br>"
            "Press <b>ESC</b> to deactivate and return to normal navigation.<br><br>"
            "<b>\u25cf Single mode:</b> Click map \u2192 auto-extracts time series for 1 point.<br>"
            "<b>\u25cf Multi mode:</b> Pick multiple points, then click <b>Extract</b>.<br><br>"
            "<b>\u25cf Coordinates (Lon/Lat):</b><br>"
            "Enter longitude and latitude in WGS84 (EPSG:4326) and click <b>+</b>.<br>"
            "Example: Lon = <code>-47.9292</code>, Lat = <code>-15.7801</code><br><br>"
            "<b>\u25cf WKT:</b><br>"
            "Enter a POINT geometry in WKT format:<br>"
            "<code>POINT(-47.9292 -15.7801)</code><br><br>"
            "<b>\u25cf Shapefile / GeoPackage:</b><br>"
            "Click <b>SHP / GPKG</b> to load point features.<br>"
            "Only <b>Point</b> or <b>MultiPoint</b> geometries are supported.<br>"
            "The label column is auto-detected from: "
            "<code>label</code>, <code>name</code>, <code>nome</code>, <code>id</code>.<br><br>"
            "<b>Required SHP/GPKG format:</b><br>"
            "\u2022 Geometry type: <b>Point</b> or <b>MultiPoint</b><br>"
            "\u2022 CRS: any (auto-reprojected to EPSG:4326)<br>"
            "\u2022 Optional columns: <code>label</code>, <code>name</code>, <code>nome</code>, or <code>id</code> for point labels<br><br>"
            "<b>\u25cf Bands filter:</b> Type in the filter box to search bands. "
            "Use <b>All</b>/<b>None</b> to toggle selection.<br><br>"
            "<b>\u25cf Interactions:</b><br>"
            "\u2022 <b>Double-click</b> a point to zoom to it on the map<br>"
            "\u2022 <b>Delete/Backspace</b> to remove selected points<br>"
            "\u2022 <b>Right-click</b> for context menu (remove, zoom, copy coords)",
        )

    def _points_context_menu(self, pos):
        item = self.points_list.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        remove_action = menu.addAction(tr("Remove point"))
        zoom_action = menu.addAction(tr("Zoom to point"))
        copy_action = menu.addAction(tr("Copy coordinates"))
        action = menu.exec(self.points_list.mapToGlobal(pos))
        if action == remove_action:
            row = self.points_list.row(item)
            if row < len(self._current_points):
                self._current_points.pop(row)
            self._rebuild_points_list()
            self._set_status(f"{count_label(len(self._current_points), 'point', 'points')} to extract.", "pending", 0)
        elif action == zoom_action:
            coords = item.data(Qt.ItemDataRole.UserRole)
            if coords:
                self._zoom_to_point(coords[0], coords[1])
        elif action == copy_action:
            coords = item.data(Qt.ItemDataRole.UserRole)
            if coords:
                QApplication.clipboard().setText(f"{coords[0]:.6f}, {coords[1]:.6f}")
                self._set_status(f"Coordinates copied: {coords[0]:.6f}, {coords[1]:.6f}.", "success")

    def _zoom_to_point(self, lon, lat):
        canvas = self.iface.mapCanvas()
        dst_crs = canvas.mapSettings().destinationCrs()
        src_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        transform = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())
        point = transform.transform(QgsPointXY(lon, lat))
        canvas.setCenter(point)
        canvas.zoomScale(50000)
        canvas.refresh()
