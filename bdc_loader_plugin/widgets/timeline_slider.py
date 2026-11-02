# -*- coding: utf-8 -*-
"""Timeline slider toolbar for temporal VRT navigation in QGIS."""

import logging
import re

_logger = logging.getLogger("bdc_loader")

from qgis.core import QgsCoordinateTransform, QgsProject, QgsRectangle, QgsSettings
from qgis.PyQt.QtCore import QSize, Qt, pyqtSignal
from qgis.PyQt.QtGui import QKeySequence
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QShortcut,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..core.layer_names import layer_key
from ..i18n import tr
from .icons import zoom_icon
from .shortcut_dialog import ShortcutConfigDialog
from .timeline_date_bar import TimelineDateBar

_COMPACT_VRT_NAME_RE = re.compile(r"^(.+?)_([A-Za-z0-9\-]+)_(\d{4}-\d{2}-\d{2})_(.+)$")
_CROP_VRT_NAME_RE = re.compile(r"^(.+?)_(Crop_.+?)_(\d{4}-\d{2}-\d{2})_(.+)$", re.IGNORECASE)
_VRT_DATE_RE = re.compile(r"(?<!\d)(\d{4})-?(\d{2})-?(\d{2})(?:T\d{6})?")


def _split_group_name(group_name):
    """Return collection and tile stored in a standard VRT layer group name."""
    if " / " not in group_name:
        return None
    collection, tile = group_name.split(" / ", 1)
    if not collection or not tile:
        return None
    return collection, tile


def _known_band_suffix(layer_name, known_bands):
    """Find the longest layer-name suffix composed only of known collection bands."""
    known = {str(band).lower() for band in known_bands if band}
    if not known:
        return None

    matches = []
    for index, character in enumerate(layer_name):
        if character != "_":
            continue
        candidate = layer_name[index + 1 :]
        parts = candidate.split("-")
        if candidate.lower() in known or (len(parts) > 1 and all(part.lower() in known for part in parts)):
            matches.append(candidate)
    return max(matches, key=len) if matches else None


def _parse_vrt_layer_name(layer_name, group_name="", known_bands=()):
    """Parse timeline metadata from compact or STAC-item VRT layer names.

    Compact crop names are parsed before the compact scene pattern because
    their stable spatial identity contains underscores. STAC item IDs obtain
    collection and tile from the layer-tree group, while their first
    acquisition date is normalized from either YYYY-MM-DD or YYYYMMDD.
    """
    group_parts = _split_group_name(group_name)
    crop_match = _CROP_VRT_NAME_RE.match(layer_name)
    if crop_match:
        collection, crop_id, date_str, bands = crop_match.groups()
        if group_parts:
            collection = group_parts[0]
        return collection, crop_id, date_str, bands

    compact_match = _COMPACT_VRT_NAME_RE.match(layer_name)
    if compact_match:
        if group_parts:
            return group_parts[0], group_parts[1], compact_match.group(3), compact_match.group(4)
        return compact_match.groups()

    if not group_parts:
        return None

    date_match = _VRT_DATE_RE.search(layer_name)
    if not date_match:
        return None

    collection, tile = group_parts
    date_str = "-".join(date_match.groups())
    bands = _known_band_suffix(layer_name, known_bands)
    item_prefix = f"{tile}_"
    if bands is None and layer_name.startswith(item_prefix):
        bands = layer_name[len(item_prefix) :]
    if bands is None:
        remainder = layer_name[date_match.end() :].lstrip("_-")
        bands = remainder if remainder and "_" not in remainder else layer_name.rsplit("_", 1)[-1]
    if not bands:
        return None
    return collection, tile, date_str, bands


def _known_collection_bands(collection):
    """Return current catalog bands without making the timeline depend on startup order."""
    from ..core.catalog_data import BAND_INFO

    return tuple(BAND_INFO.get(collection, {}))


def _timeline_info_for_layer(layer, root=None):
    """Read timeline metadata using the layer group and either supported name format."""
    group_name = ""
    if root is None:
        root = QgsProject.instance().layerTreeRoot()
    tree_node = root.findLayer(layer.id())
    if tree_node is not None:
        parent = tree_node.parent()
        if parent is not None and hasattr(parent, "name"):
            group_name = layer_key(parent)

    group_parts = _split_group_name(group_name)
    collection = group_parts[0] if group_parts else ""
    return _parse_vrt_layer_name(
        layer_key(layer),
        group_name=group_name,
        known_bands=_known_collection_bands(collection),
    )


# ---- Shortcut Config Dialog ----


# ---- Timeline Toolbar ----


class VRTTimelineSlider(QToolBar):
    """Timeline toolbar for temporal VRT navigation in QGIS main window."""

    layerChanged = pyqtSignal(str)

    _SETTINGS_PREFIX = "bdc_timeline"

    def __init__(self, iface, parent=None):
        super().__init__("BDC Timeline", parent or iface.mainWindow())
        self.iface = iface
        self._groups = {}
        self._current_key = None
        self._current_idx = 0
        self._sc_prev = None
        self._sc_next = None
        self._prev_key = ""
        self._next_key = ""
        self._enabled = True
        self.setObjectName("BDCTimelineToolbar")
        self.setMovable(True)
        self.setFloatable(True)
        self.setStyleSheet("""
            QToolBar {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #f0f4fa, stop:1 #e4eaf4);
                border-bottom: 1px solid #c8d0dc;
                spacing: 6px;
                padding: 2px 4px;
            }
        """)
        self._build_toolbar()
        self._load_and_apply_shortcuts()
        self.iface.mapCanvas().currentLayerChanged.connect(self._on_active_layer_changed)
        QgsProject.instance().layersAdded.connect(self._on_layers_changed)
        QgsProject.instance().layersRemoved.connect(self._on_layers_changed)

    def _build_toolbar(self):
        # Main container
        container = QWidget()
        container.setMinimumWidth(420)
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(6, 3, 6, 3)
        main_layout.setSpacing(2)

        self._build_tile_row(main_layout)

        # Clickable date bar
        self.date_bar = TimelineDateBar()
        self.date_bar.dateClicked.connect(self._on_date_clicked)
        main_layout.addWidget(self.date_bar)

        self._build_nav_row(main_layout)
        self.addWidget(container)

        # Separator
        self.addSeparator()

        self._build_toolbar_buttons()
        self._update_ui_state()

    def _build_tile_row(self, main_layout):
        """Tile label and combo, zoom button and the summary of dates."""
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(8)

        self.tile_label = QLabel("")
        self.tile_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #1a3a5c; padding: 0 4px;")
        top_row.addWidget(self.tile_label)

        self.tile_combo = QComboBox()
        self.tile_combo.setFixedHeight(22)
        self.tile_combo.setMinimumWidth(140)
        self.tile_combo.setMaximumWidth(260)
        self.tile_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tile_combo.setToolTip("Filter by tile / collection")
        self.tile_combo.setStyleSheet(
            "QComboBox { font-size: 10px; border: 1px solid #b8c4d4; border-radius: 3px; "
            "padding: 1px 6px; background: qlineargradient(x1:0,y1:0,x2:0,y2:1, "
            "stop:0 #fff, stop:1 #f0f4fa); } "
            "QComboBox:hover { border-color: #2e7dd1; } "
            "QComboBox::drop-down { border: none; width: 18px; }"
        )
        self.tile_combo.currentIndexChanged.connect(self._on_tile_combo_changed)
        top_row.addWidget(self.tile_combo)

        self.zoom_btn = QPushButton()
        self.zoom_btn.setFixedSize(24, 22)
        self.zoom_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.zoom_btn.setToolTip("Zoom to tile extent")
        self.zoom_btn.setIcon(zoom_icon("#2a4a6a"))
        self.zoom_btn.setIconSize(QSize(16, 16))
        self.zoom_btn.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid #b8c4d4; "
            "border-radius: 3px; } "
            "QPushButton:hover { background: #d0dff4; border-color: #2e7dd1; }"
        )
        self.zoom_btn.clicked.connect(self._zoom_to_tile)
        top_row.addWidget(self.zoom_btn)

        self.dates_summary_label = QLabel("")
        self.dates_summary_label.setStyleSheet("font-size: 9px; color: #5a7a9a; padding: 0 4px;")
        self.dates_summary_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top_row.addWidget(self.dates_summary_label, stretch=1)

        main_layout.addLayout(top_row)

    def _build_nav_row(self, main_layout):
        """Previous and next buttons around the position label."""
        ctrl = QHBoxLayout()
        ctrl.setContentsMargins(0, 0, 0, 0)
        ctrl.setSpacing(6)

        self.prev_btn = QPushButton("◀ Prev")
        self.prev_btn.setFixedHeight(26)
        self.prev_btn.setMinimumWidth(80)
        self.prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.prev_btn.setStyleSheet(self._nav_btn_style())
        self.prev_btn.clicked.connect(self.go_prev)
        ctrl.addWidget(self.prev_btn)

        self.position_label = QLabel("")
        self.position_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.position_label.setStyleSheet(
            "font-size: 12px; color: #1a5fa8; font-weight: bold; "
            "background: #e0ebf7; border-radius: 4px; padding: 2px 12px;"
        )
        ctrl.addWidget(self.position_label, stretch=1)

        self.next_btn = QPushButton("Next ▶")
        self.next_btn.setFixedHeight(26)
        self.next_btn.setMinimumWidth(80)
        self.next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.next_btn.setStyleSheet(self._nav_btn_style())
        self.next_btn.clicked.connect(self.go_next)
        ctrl.addWidget(self.next_btn)

        main_layout.addLayout(ctrl)

    def _build_toolbar_buttons(self):
        """On/off toggle, shortcut settings and close buttons."""
        self.toggle_btn = QPushButton("●")
        self.toggle_btn.setFixedSize(28, 28)
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.setToolTip("Toggle timeline")
        self.toggle_btn.clicked.connect(self._toggle_enabled)
        self._update_toggle_style()
        self.addWidget(self.toggle_btn)

        # Config button
        self.config_btn = QPushButton("⚙")
        self.config_btn.setFixedSize(28, 28)
        self.config_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.config_btn.setToolTip("Keyboard shortcuts")
        self.config_btn.setStyleSheet("""
            QPushButton {
                background: transparent; border: none;
                font-size: 16px; color: #555;
            }
            QPushButton:hover { color: #1a5fa8; }
        """)
        self.config_btn.clicked.connect(self._open_shortcut_config)
        self.addWidget(self.config_btn)

        # Close button
        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setToolTip("Close timeline")
        self.close_btn.setStyleSheet("""
            QPushButton {
                background: transparent; border: none;
                font-size: 14px; color: #999; font-weight: bold;
            }
            QPushButton:hover { color: #c0392b; }
        """)
        self.close_btn.clicked.connect(lambda: self.setVisible(False))
        self.addWidget(self.close_btn)

    def _nav_btn_style(self):
        return """
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #fff, stop:1 #eef2f8);
                border: 1px solid #b8c4d4;
                border-radius: 5px;
                font-size: 11px;
                font-weight: bold;
                color: #2a4a6a;
                padding: 2px 10px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #e8f0ff, stop:1 #d0dff4);
                border-color: #2e7dd1;
            }
            QPushButton:pressed {
                background: #c8d8f0;
            }
            QPushButton:disabled {
                color: #b0b8c4;
                background: #f0f2f5;
                border-color: #ddd;
            }
        """

    # ---- Toggle On/Off ----

    def _toggle_enabled(self):
        self._enabled = not self._enabled
        self._update_toggle_style()
        if self._enabled:
            self._enable_shortcuts()
        else:
            self._disable_shortcuts()
        self._update_ui_state()

    def _update_toggle_style(self):
        if self._enabled:
            self.toggle_btn.setStyleSheet("""
                QPushButton {
                    background: transparent; border: none;
                    font-size: 18px; color: #27ae60;
                }
                QPushButton:hover { color: #1e8449; }
            """)
            self.toggle_btn.setToolTip(tr("Timeline ON — click to disable"))
        else:
            self.toggle_btn.setStyleSheet("""
                QPushButton {
                    background: transparent; border: none;
                    font-size: 18px; color: #c0392b;
                }
                QPushButton:hover { color: #922b21; }
            """)
            self.toggle_btn.setToolTip(tr("Timeline OFF — click to enable"))

    def _enable_shortcuts(self):
        if self._sc_prev:
            self._sc_prev.setEnabled(True)
        if self._sc_next:
            self._sc_next.setEnabled(True)

    def _disable_shortcuts(self):
        if self._sc_prev:
            self._sc_prev.setEnabled(False)
        if self._sc_next:
            self._sc_next.setEnabled(False)

    # ---- Shortcuts ----

    def _load_and_apply_shortcuts(self):
        s = QgsSettings()
        prev_key = s.value(f"{self._SETTINGS_PREFIX}/shortcut_prev", ShortcutConfigDialog.DEFAULT_PREV, type=str)
        next_key = s.value(f"{self._SETTINGS_PREFIX}/shortcut_next", ShortcutConfigDialog.DEFAULT_NEXT, type=str)
        self._apply_shortcuts(prev_key, next_key)

    def _apply_shortcuts(self, prev_key, next_key):
        """Register keyboard shortcuts."""
        # Remove old shortcuts
        if self._sc_prev is not None:
            self._sc_prev.setEnabled(False)
            self._sc_prev.deleteLater()
            self._sc_prev = None
        if self._sc_next is not None:
            self._sc_next.setEnabled(False)
            self._sc_next.deleteLater()
            self._sc_next = None

        self._prev_key = prev_key
        self._next_key = next_key

        main_window = self.iface.mainWindow()

        self._sc_prev = QShortcut(QKeySequence(prev_key), main_window)
        self._sc_prev.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._sc_prev.activated.connect(self.go_prev)

        self._sc_next = QShortcut(QKeySequence(next_key), main_window)
        self._sc_next.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._sc_next.activated.connect(self.go_next)

        # Disable shortcuts if timeline is off
        if not self._enabled:
            self._sc_prev.setEnabled(False)
            self._sc_next.setEnabled(False)

        # Update tooltips
        self.prev_btn.setToolTip(tr(f"Previous date ({prev_key})"))
        self.next_btn.setToolTip(tr(f"Next date ({next_key})"))

    def _open_shortcut_config(self):
        dlg = ShortcutConfigDialog(self._prev_key, self._next_key, self.iface.mainWindow())
        if dlg.exec() == QDialog.DialogCode.Accepted:
            prev_key, next_key = dlg.get_shortcuts()
            self._apply_shortcuts(prev_key, next_key)
            s = QgsSettings()
            s.setValue(f"{self._SETTINGS_PREFIX}/shortcut_prev", prev_key)
            s.setValue(f"{self._SETTINGS_PREFIX}/shortcut_next", next_key)

    # ---- VRT scan ----

    def scan_project_layers(self):
        self._groups.clear()
        layers = QgsProject.instance().mapLayers().values()
        for layer in layers:
            if layer.type() != layer.RasterLayer:
                continue
            timeline_info = _timeline_info_for_layer(layer)
            if timeline_info is None:
                continue
            collection, tile, date_str, bands = timeline_info
            key = (collection, tile, bands)
            entry = {
                "date": date_str,
                "layer_id": layer.id(),
                "layer_name": layer.name(),
            }
            self._groups.setdefault(key, []).append(entry)

        for key in self._groups:
            self._groups[key].sort(key=lambda e: e["date"])

        has_groups = bool(self._groups)
        self.setVisible(has_groups)
        if has_groups:
            if not self._current_key or self._current_key not in self._groups:
                best_key = max(self._groups, key=lambda k: len(self._groups[k]))
                self._current_key = best_key
                self._current_idx = 0
            else:
                max_idx = len(self._groups[self._current_key]) - 1
                if self._current_idx > max_idx:
                    self._current_idx = max(0, max_idx)
        else:
            self._current_key = None
            self._current_idx = 0
        self._update_tile_combo()
        self._update_ui_state()

    def _update_tile_combo(self):
        try:
            self.tile_combo.blockSignals(True)
            self.tile_combo.clear()
            keys_sorted = sorted(self._groups.keys(), key=lambda k: (k[0], k[1]))
            for key in keys_sorted:
                collection, tile, bands = key
                n = len(self._groups[key])
                label = f"{tile} | {collection} ({n})"
                self.tile_combo.addItem(label, userData=key)
            count = int(self.tile_combo.count())
            idx_to_select = -1
            for i in range(count):
                if self.tile_combo.itemData(i) == self._current_key:
                    idx_to_select = i
                    break
            if idx_to_select >= 0:
                self.tile_combo.setCurrentIndex(idx_to_select)
            elif count > 0:
                self.tile_combo.setCurrentIndex(0)
            self.tile_combo.blockSignals(False)
        except (TypeError, AttributeError) as _e:
            _logger.debug("Failed to restore tile combo selection: %s", _e)

    def group_sizes(self):
        """{group key: number of dates} of the image groups on the map."""
        return {key: len(entries) for key, entries in self._groups.items()}

    def show_group(self, key):
        """Show the first date of the group ``key`` and select it in the tile list."""
        if key not in self._groups:
            return
        index = self.tile_combo.findData(key)
        if index >= 0:
            self.tile_combo.setCurrentIndex(index)
        self._current_key = key
        self._navigate_to(0)

    def position(self):
        """(group key, date index) shown now."""
        return self._current_key, self._current_idx

    def _on_tile_combo_changed(self, index):
        if index < 0:
            return
        key = self.tile_combo.itemData(index)
        if key and key in self._groups:
            self._current_key = key
            self._current_idx = 0
            self._update_ui_state()
            self._navigate_to(0)

    def _on_layers_changed(self, *args):
        self.scan_project_layers()

    def _on_active_layer_changed(self, layer):
        if not self._enabled:
            return
        if layer is None or layer.type() != layer.RasterLayer:
            return

        timeline_info = _timeline_info_for_layer(layer)
        if timeline_info is None:
            return

        key = (timeline_info[0], timeline_info[1], timeline_info[3])

        # layersAdded fires before the layer enters its tree group, so a layer
        # added to a known group can be missing from the last scan.
        if self._entry_index(key, layer.id()) is None:
            self.scan_project_layers()

        index = self._entry_index(key, layer.id())
        if index is None:
            return

        self._current_key = key
        self._current_idx = index

        self._update_tile_combo()
        self.setVisible(True)
        self._update_ui_state()

    def _entry_index(self, key, layer_id):
        """Date index of ``layer_id`` in the group ``key``, or None when the scan lacks it."""
        for i, entry in enumerate(self._groups.get(key, [])):
            if entry["layer_id"] == layer_id:
                return i
        return None

    def _on_date_clicked(self, idx):
        if self._enabled:
            self._navigate_to(idx)

    # ---- Navigation ----

    def go_prev(self):
        if self._enabled and self._current_key and self._current_idx > 0:
            self._navigate_to(self._current_idx - 1)

    def go_next(self):
        if self._enabled and self._current_key:
            entries = self._groups.get(self._current_key, [])
            if self._current_idx < len(entries) - 1:
                self._navigate_to(self._current_idx + 1)

    def _navigate_to(self, idx):
        if not self._current_key:
            return
        entries = self._groups.get(self._current_key, [])
        if not entries or idx < 0 or idx >= len(entries):
            return

        self._current_idx = idx
        entry = entries[idx]
        layer_id = entry["layer_id"]

        layer = QgsProject.instance().mapLayer(layer_id)
        if layer:
            root = self.iface.layerTreeView().layerTreeModel().rootGroup()
            for e in entries:
                tree_layer = root.findLayer(e["layer_id"])
                if tree_layer:
                    tree_layer.setItemVisibilityChecked(e["layer_id"] == layer_id)

            self.iface.setActiveLayer(layer)
            self.iface.mapCanvas().refresh()
            self.layerChanged.emit(layer_id)

        self._update_ui_state()

    def _update_ui_state(self):
        if not self._current_key or self._current_key not in self._groups:
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            self.tile_label.setText(tr("BDC Timeline"))
            self.position_label.setText(tr("Select a VRT"))
            self.dates_summary_label.setText("")
            self.date_bar.set_dates([])
            return

        entries = self._groups[self._current_key]
        n = len(entries)
        idx = self._current_idx
        collection, tile, bands = self._current_key

        enabled = self._enabled
        self.prev_btn.setEnabled(enabled and idx > 0)
        self.next_btn.setEnabled(enabled and idx < n - 1)

        # Tile label
        bands_short = bands.replace("_", ", ")
        self.tile_label.setText(f"{tile}  |  {collection}")

        # Current date
        date_str = entries[idx]["date"]
        self.position_label.setText(f"{date_str}   ({idx + 1} / {n})")

        # Date summary
        first_date = entries[0]["date"]
        last_date = entries[-1]["date"]
        if n == 1:
            self.dates_summary_label.setText(tr(f"1 date: {first_date}"))
        else:
            self.dates_summary_label.setText(tr(f"{n} dates: {first_date} → {last_date}  [{bands_short}]"))

        dates = [e["date"] for e in entries]
        self.date_bar.set_dates(dates, idx)

    # ---- Zoom to tile ----

    def _zoom_to_tile(self):
        if not self._current_key or self._current_key not in self._groups:
            return
        entries = self._groups[self._current_key]
        combined = QgsRectangle()
        canvas = self.iface.mapCanvas()
        dst_crs = canvas.mapSettings().destinationCrs()
        for e in entries:
            layer = QgsProject.instance().mapLayer(e["layer_id"])
            if layer and layer.isValid():
                ext = layer.extent()
                if layer.crs() != dst_crs:
                    xform = QgsCoordinateTransform(layer.crs(), dst_crs, QgsProject.instance())
                    ext = xform.transformBoundingBox(ext)
                combined.combineExtentWith(ext)
        if combined.isNull() or combined.isEmpty():
            return
        combined.scale(1.05)  # 5% margin like native QGIS
        canvas.setExtent(combined)
        canvas.refresh()

    # ---- Cleanup ----

    def cleanup(self):
        if self._sc_prev is not None:
            self._sc_prev.setEnabled(False)
            self._sc_prev.deleteLater()
            self._sc_prev = None
        if self._sc_next is not None:
            self._sc_next.setEnabled(False)
            self._sc_next.deleteLater()
            self._sc_next = None
        try:
            self.iface.mapCanvas().currentLayerChanged.disconnect(self._on_active_layer_changed)
        except Exception as _e:
            _logger.debug("Failed to disconnect currentLayerChanged: %s", _e)
        try:
            QgsProject.instance().layersAdded.disconnect(self._on_layers_changed)
            QgsProject.instance().layersRemoved.disconnect(self._on_layers_changed)
        except Exception as _e:
            _logger.debug("Failed to disconnect project layer signals: %s", _e)
