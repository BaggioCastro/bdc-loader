# -*- coding: utf-8 -*-
"""Shapefile and GeoPackage spatial handler for BDCLoaderDialog."""

import logging
import os
import re
import tempfile

_logger = logging.getLogger("bdc_loader")

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ..i18n import tr
from ..timing import AFTER_HANDLER_MS
from .catalog_data import COLLECTIONS
from .download_outputs import area_tag, crop_label, crop_tag
from .gdal_env import uses_gdal

# A vector source with more features than this (a whole tile grid, every
# municipality of a country) starts with none checked, so a search never
# covers the entire layer by accident.
_AUTO_CHECK_LIMIT = 50


def _polygon_geometry_type():
    try:
        from qgis.core import Qgis

        return Qgis.GeometryType.Polygon
    except AttributeError:
        from qgis.core import QgsWkbTypes

        return QgsWkbTypes.PolygonGeometry


def _to_wgs84(geom, crs):
    """Copy of ``geom`` in EPSG:4326."""
    from qgis.core import QgsGeometry

    out = QgsGeometry(geom)
    if crs.authid() != "EPSG:4326":
        out.transform(QgsCoordinateTransform(crs, QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance()))
    return out


def _write_cutline(geometry_json):
    """Write one GeoJSON geometry (EPSG:4326) as a temporary cutline file."""
    import json as _json

    feature_collection = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {}, "geometry": geometry_json}],
    }
    fd, path = tempfile.mkstemp(suffix=".geojson", prefix="bdc_cutline_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        _json.dump(feature_collection, f)
    return path


def _reference_grid_explanation():
    """Left column of the grid offer: what the grid is for and a link to the grid specification."""
    left = QVBoxLayout()
    left.setSpacing(8)

    title = QLabel("Add a BDC tile grid")
    title.setStyleSheet("font-size: 13px; font-weight: bold;")
    left.addWidget(title)

    desc = QLabel(
        "The grid shows where each BDC\n"
        "tile is and gives Draw on Canvas\n"
        "a map to draw over.\n\n"
        "Choose a grid to load directly\n"
        "from GeoServer (WFS)."
    )
    desc.setStyleSheet("font-size: 11px; color: #555;")
    desc.setWordWrap(True)
    left.addWidget(desc)
    left.addStretch()

    link = QLabel(
        '<a href="https://brazil-data-cube.github.io/specifications/bdc-grid.html">BDC Grid Specification ↗</a>'
    )
    link.setStyleSheet("font-size: 10px;")
    link.setOpenExternalLinks(True)
    left.addWidget(link)
    return left


def _grid_choice_column(dlg, options, chosen):
    """Right column: one button per (id, label, description) grid and Cancel.

    A grid button stores its id in ``chosen["grid"]`` and accepts ``dlg``.
    """
    right = QVBoxLayout()
    right.setSpacing(6)

    def _choose(grid_id):
        chosen["grid"] = grid_id
        dlg.accept()

    for grid_id, grid_label, grid_desc in options:
        btn = QPushButton(f"  {grid_label}")
        btn.setFixedHeight(38)
        btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #0969da; color: white; border: none;"
            "  border-radius: 4px; font-size: 11px; font-weight: bold;"
            "  text-align: left; padding-left: 10px;"
            "}"
            "QPushButton:hover { background-color: #0550ae; }"
        )
        btn.setToolTip(grid_desc)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda _checked=False, gid=grid_id: _choose(gid))
        right.addWidget(btn)

        hint = QLabel(f"  {grid_desc}")
        hint.setStyleSheet("font-size: 9px; color: #888; margin-bottom: 4px;")
        right.addWidget(hint)

    right.addStretch()

    cancel_btn = QPushButton("Cancel")
    cancel_btn.setFixedHeight(28)
    cancel_btn.setStyleSheet(
        "QPushButton { background-color: #e0e0e0; border: none;  border-radius: 4px; font-size: 10px; }"
        "QPushButton:hover { background-color: #ccc; }"
    )
    cancel_btn.clicked.connect(dlg.reject)
    right.addWidget(cancel_btn)
    return right


class ShapefileHandler:
    """Provides shapefile/GPKG spatial selection and mosaic grouping."""

    _SPATIAL_MODES = ("Extent", "Tiles", "Vector File")

    def _collection_has_tiles(self):
        if not hasattr(self, "collection_combo"):
            return True
        name = self._current_collection_name()
        return COLLECTIONS.get(name, {}).get("has_tiles", True)

    def _active_spatial_mode(self):
        if getattr(self, "_shape_vector_layer", None) is not None and not getattr(self, "_shape_suspended", False):
            return "Vector File"
        if hasattr(self, "extent_box") and self.extent_box.isActive():
            return "Extent"
        if (
            hasattr(self, "tiles_input")
            and self.tiles_input.text().strip()
            and not getattr(self, "_tiles_suspended", False)
        ):
            return "Tiles"
        return None

    def _paused_spatial_modes(self):
        """Filters closed with their choice kept (reopening the group resumes them)."""
        paused = []
        if hasattr(self, "extent_box") and not self.extent_box.isActive() and self.extent_box.hasExtent():
            paused.append("Extent")
        if getattr(self, "_tiles_suspended", False) and self.tiles_input.text().strip():
            paused.append("Tiles")
        if getattr(self, "_shape_suspended", False) and getattr(self, "_shape_vector_layer", None) is not None:
            paused.append("Vector File")
        return paused

    def _suspend_other_filters(self, keep):
        """Pause any filter in use other than ``keep``, keeping its choice."""
        if keep != "Extent" and hasattr(self, "extent_box") and self.extent_box.isActive():
            self.extent_box.suspend()
        if keep != "Tiles" and hasattr(self, "tiles_input") and self.tiles_input.text().strip():
            self._tiles_suspended = True
        if keep != "Vector File" and getattr(self, "_shape_vector_layer", None) is not None:
            self._shape_suspended = True

    def _refresh_spatial_hint(self):
        """Say which area filter is in use and how to switch to another one."""
        label = getattr(self, "_spatial_hint", None)
        if label is None:
            return
        has_tiles = self._collection_has_tiles()
        modes = [m for m in self._SPATIAL_MODES if has_tiles or m != "Tiles"]
        active = self._active_spatial_mode()
        if active is None:
            text = f"Choose one area: {', '.join(modes[:-1])} or {modes[-1]}."
        else:
            others = " or ".join(m for m in modes if m != active)
            text = f"Using {active}. To use {others}, close it or clear it (\u2715) first."
        if not has_tiles:
            text += " This collection has no tile grid."
        paused = [m for m in self._paused_spatial_modes() if m != active]
        if paused and active is None:
            names = " and ".join(paused)
            text += f" {names} {'is' if len(paused) == 1 else 'are'} closed but kept: open to use again."
        label.setText(tr(text))

    def _apply_spatial_locks(self):
        """Grey out every area filter except the one in use, the same way for all three.

        A locked group is disabled and collapsed; with no filter in use all
        three are open to the user (Tiles only when the collection has a grid).
        """
        groups = [
            (mode, getattr(self, attr, None))
            for mode, attr in (("Extent", "extent_box"), ("Tiles", "tiles_group"), ("Vector File", "shape_group"))
        ]
        if any(group is None for _mode, group in groups):
            return
        active = self._active_spatial_mode()
        has_tiles = self._collection_has_tiles()
        for mode, group in groups:
            enabled = active in (None, mode) and (has_tiles or mode != "Tiles")
            group.setEnabled(enabled)
            if not enabled:
                group.setCollapsed(True)
        self._refresh_spatial_hint()

    def _on_tiles_collapsed(self, collapsed):
        """Closing Tiles pauses the tiles entered (other filters unlock);
        reopening resumes them. Only the clear button forgets them."""
        if collapsed:
            if self._active_spatial_mode() == "Tiles":
                self._tiles_suspended = True
                self._apply_spatial_locks()
        elif getattr(self, "_tiles_suspended", False) and self._active_spatial_mode() is None:
            self._tiles_suspended = False
            self._apply_spatial_locks()

    def _on_shape_collapsed(self, collapsed):
        """Closing Vector File pauses the vector source; reopening resumes it."""
        if collapsed:
            if self._active_spatial_mode() == "Vector File":
                self._shape_suspended = True
                self._apply_spatial_locks()
        elif getattr(self, "_shape_suspended", False) and self._active_spatial_mode() is None:
            self._shape_suspended = False
            self._apply_spatial_locks()

    def _on_extent_expanded(self, collapsed):
        """Opening Extent resumes the area it had, or starts from the whole of
        Brazil; closing it pauses the area (the clear button forgets it).

        On an empty project a reference grid is offered as well, so there is
        something on the map to draw over.
        """
        if collapsed:
            if self.extent_box.isActive():
                self.extent_box.suspend()
            return
        if self.extent_box.isActive() or self._active_spatial_mode() is not None:
            return
        if self.extent_box.hasExtent():
            self.extent_box.setActive(True)
            return
        if not self.extent_box.hasExtent():
            self._set_extent_to_brazil()
        from qgis.core import QgsProject

        if not QgsProject.instance().mapLayers():
            from qgis.PyQt.QtCore import QTimer

            QTimer.singleShot(AFTER_HANDLER_MS, self._offer_reference_grid)

    def _set_extent_to_brazil(self):
        from ..stac.fallback import BRAZIL_BBOX

        self.extent_box.setOutputExtentFromUser(QgsRectangle(*BRAZIL_BBOX), QgsCoordinateReferenceSystem("EPSG:4326"))
        self.extent_box.setActive(True)
        if hasattr(self, "_update_extent_bbox_label"):
            self._update_extent_bbox_label()

    def _clear_extent(self):
        """Forget the extent so another area filter can be used."""
        self.extent_box.clear()
        if hasattr(self, "_update_extent_bbox_label"):
            self._update_extent_bbox_label()

    def _on_extent_toggled(self, checked):
        """Extent in use locks Tiles and Vector File; released, it unlocks them."""
        # This signal can fire during setup_ui before all sibling widgets exist.
        if not hasattr(self, "shape_group") or not hasattr(self, "tiles_group"):
            return
        if checked:
            self.extent_box.setCollapsed(False)
            self._suspend_other_filters("Extent")
        self._apply_spatial_locks()

    def _on_tiles_text_changed(self, text):
        """Tiles in use lock Extent and Vector File; cleared, they unlock them."""
        if text.strip():
            self._tiles_suspended = False
            self._suspend_other_filters("Tiles")
        else:
            self._tiles_suspended = False
        self._apply_spatial_locks()

    # ---- Shapefile / GPKG spatial mode ----

    def _browse_shapefile(self):
        """Opens file dialog to select a shapefile or GeoPackage."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Shapefile or GeoPackage",
            "",
            "Vector files (*.shp *.gpkg);;Shapefiles (*.shp);;GeoPackage (*.gpkg);;All Files (*)",
        )
        if not file_path:
            return
        self._load_shapefile(file_path)

    @uses_gdal
    def _load_shapefile(self, file_path):
        """Load a shapefile/GPKG and populate the feature list."""
        # For GPKG, check if it has multiple layers
        if file_path.lower().endswith(".gpkg"):
            from osgeo import ogr

            ds = ogr.Open(file_path)
            if not ds:
                QMessageBox.warning(self, "Error", f"Could not open: {file_path}")
                return
            layer_count = ds.GetLayerCount()
            if layer_count > 1:
                self.shape_layer_combo.clear()
                for i in range(layer_count):
                    lyr = ds.GetLayerByIndex(i)
                    geom_type = ogr.GeometryTypeToName(lyr.GetGeomType())
                    self.shape_layer_combo.addItem(f"{lyr.GetName()} ({geom_type})", lyr.GetName())
                self.shape_layer_combo.setEnabled(True)
                ds = None
                self._shape_file_path = file_path
                self.shape_file_input.setText(os.path.basename(file_path))
                # Load first layer
                layer_name = self.shape_layer_combo.itemData(0)
                vlayer = QgsVectorLayer(f"{file_path}|layername={layer_name}", layer_name, "ogr")
            else:
                ds = None
                vlayer = QgsVectorLayer(file_path, os.path.basename(file_path), "ogr")
                self._show_single_shape_layer(vlayer.name())
        else:
            vlayer = QgsVectorLayer(file_path, os.path.basename(file_path), "ogr")
            self._show_single_shape_layer(vlayer.name())

        if not vlayer or not vlayer.isValid():
            QMessageBox.warning(self, "Error", f"Invalid vector file: {file_path}")
            return

        self._activate_shape_layer(vlayer, os.path.basename(file_path), file_path)

    def _choose_project_layer(self):
        """Offer the polygon layers of the project (a loaded tile grid, say) as the vector source."""
        polygon = _polygon_geometry_type()
        layers = [
            layer
            for layer in QgsProject.instance().mapLayers().values()
            if isinstance(layer, QgsVectorLayer) and layer.isValid() and layer.geometryType() == polygon
        ]
        if not layers:
            QMessageBox.information(
                self,
                "Vector File",
                "The project has no polygon layer. Load one (for example a tile grid with Load Grid) "
                "or browse for a file.",
            )
            return
        menu = QMenu(self)
        for layer in sorted(layers, key=lambda lyr: lyr.name().casefold()):
            selected = layer.selectedFeatureCount()
            suffix = f"  ({selected} selected)" if selected else ""
            action = menu.addAction(f"{layer.name()}{suffix}")
            action.triggered.connect(lambda _checked=False, lyr=layer: self._use_project_layer(lyr))
        button = getattr(self, "shape_layer_btn", None)
        pos = button.mapToGlobal(button.rect().bottomLeft()) if button is not None else None
        menu.exec(pos) if pos is not None else menu.exec()

    def _use_project_layer(self, layer):
        """Use a layer already in the project as the vector source.

        With features selected on the map, only those are listed; the list
        follows later changes of that selection.
        """
        source = layer.source().split("|")[0]
        file_path = source if layer.providerType() == "ogr" and os.path.isfile(source) else None
        self._show_single_shape_layer(layer.name())
        self._activate_shape_layer(layer, f"Layer: {layer.name()}", file_path, project_layer=True)

    def _show_single_shape_layer(self, name):
        """Show the one layer in use in the (disabled) layer selector."""
        self.shape_layer_combo.blockSignals(True)
        self.shape_layer_combo.clear()
        self.shape_layer_combo.addItem(name, name)
        self.shape_layer_combo.setEnabled(False)
        self.shape_layer_combo.blockSignals(False)

    def _disconnect_project_layer(self):
        layer = getattr(self, "_shape_project_layer", None)
        self._shape_project_layer = None
        if layer is None:
            return
        for signal, slot in (
            (layer.selectionChanged, self._on_project_selection_changed),
            (layer.willBeDeleted, self._clear_shapefile),
        ):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass

    def _on_project_selection_changed(self, *_args):
        if getattr(self, "_shape_project_layer", None) is not None:
            self._populate_shape_features()

    def _activate_shape_layer(self, vlayer, display_name, file_path, project_layer=False):
        """Make ``vlayer`` the vector source and lock the other spatial modes."""
        self._disconnect_project_layer()
        if project_layer:
            self._shape_project_layer = vlayer
            vlayer.selectionChanged.connect(self._on_project_selection_changed)
            vlayer.willBeDeleted.connect(self._clear_shapefile)
        self._shape_file_path = file_path
        self._shape_vector_layer = vlayer
        self.shape_file_input.setText(display_name)

        # Populate attribute field combo
        self.shape_attr_combo.blockSignals(True)
        self.shape_attr_combo.clear()
        fields = vlayer.fields()
        # Add auto/FID option
        self.shape_attr_combo.addItem("(FID)", None)
        first_string_idx = None
        for field in fields:
            # Only string/text fields for labeling
            type_name = field.typeName().lower()
            if "string" in type_name or "text" in type_name or "char" in type_name:
                if first_string_idx is None:
                    first_string_idx = self.shape_attr_combo.count()
                self.shape_attr_combo.addItem(field.name(), field.name())
        # Also add integer fields as they may be useful IDs
        for field in fields:
            type_name = field.typeName().lower()
            if "int" in type_name or "integer" in type_name:
                self.shape_attr_combo.addItem(f"{field.name()} (int)", field.name())
        # Auto-select the first string field so features get meaningful names
        if first_string_idx is not None:
            self.shape_attr_combo.setCurrentIndex(first_string_idx)
        self.shape_attr_combo.setEnabled(True)
        self.shape_attr_combo.blockSignals(False)

        # The vector file is now the area filter in use
        self._shape_suspended = False
        self._suspend_other_filters("Vector File")
        self._apply_spatial_locks()

        self._populate_shape_features()

    def _on_shape_layer_changed(self, index):
        """When a different layer is selected in a multi-layer GPKG."""
        if not self._shape_file_path or index < 0:
            return
        layer_name = self.shape_layer_combo.itemData(index)
        if not layer_name:
            return
        vlayer = QgsVectorLayer(f"{self._shape_file_path}|layername={layer_name}", layer_name, "ogr")
        if vlayer and vlayer.isValid():
            self._shape_vector_layer = vlayer
            # Re-populate attr combo
            self.shape_attr_combo.blockSignals(True)
            self.shape_attr_combo.clear()
            self.shape_attr_combo.addItem("(FID)", None)
            first_string_idx = None
            for field in vlayer.fields():
                type_name = field.typeName().lower()
                if "string" in type_name or "text" in type_name or "char" in type_name:
                    if first_string_idx is None:
                        first_string_idx = self.shape_attr_combo.count()
                    self.shape_attr_combo.addItem(field.name(), field.name())
            for field in vlayer.fields():
                type_name = field.typeName().lower()
                if "int" in type_name or "integer" in type_name:
                    self.shape_attr_combo.addItem(f"{field.name()} (int)", field.name())
            if first_string_idx is not None:
                self.shape_attr_combo.setCurrentIndex(first_string_idx)
            self.shape_attr_combo.setEnabled(True)
            self.shape_attr_combo.blockSignals(False)
            self._populate_shape_features()

    def _on_shape_attr_changed(self, index):
        """When the attribute field for labeling changes, refresh the feature list."""
        self._populate_shape_features()

    def _populate_shape_features(self):
        """Populate feature list from currently loaded vector layer."""
        self.shape_feature_list.clear()
        self._shape_features = []

        vlayer = self._shape_vector_layer
        if not vlayer or not vlayer.isValid():
            return

        attr_field = self.shape_attr_combo.currentData()
        project_layer = getattr(self, "_shape_project_layer", None) is vlayer
        use_selection = project_layer and vlayer.selectedFeatureCount() > 0
        features = list(vlayer.getSelectedFeatures() if use_selection else vlayer.getFeatures())
        check_all = use_selection or len(features) <= _AUTO_CHECK_LIMIT

        for feat in features:
            fid = feat.id()
            geom = feat.geometry()
            if geom.isNull() or geom.isEmpty():
                continue

            if attr_field:
                name = str(feat[attr_field]) if feat[attr_field] is not None else f"Feature {fid}"
            else:
                name = f"Feature {fid}"

            self._shape_features.append((fid, name, geom))

            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if check_all else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, fid)
            self.shape_feature_list.addItem(item)

        count = len(self._shape_features)
        if use_selection:
            self.shape_info_label.setText(tr(f"{count} features selected on the map"))
        elif check_all:
            self.shape_info_label.setText(tr(f"{count} features loaded"))
        elif project_layer:
            self.shape_info_label.setText(tr(f"{count} features: check the ones to use, or select them on the map"))
        else:
            self.shape_info_label.setText(tr(f"{count} features: check the ones to use"))

    def _on_shape_merge_toggled(self, checked):
        """When merge is toggled, disable/enable the feature list."""
        self.shape_feature_list.setEnabled(not checked)
        if checked:
            self.shape_info_label.setText(tr(f"{len(self._shape_features)} features (merged as single boundary)"))
        else:
            selected = self._get_selected_shape_fids()
            self.shape_info_label.setText(tr(f"{len(selected)} of {len(self._shape_features)} features selected"))

    def _shape_select_all(self, select):
        """Select or deselect all features in the shape list."""
        for i in range(self.shape_feature_list.count()):
            item = self.shape_feature_list.item(i)
            item.setCheckState(Qt.CheckState.Checked if select else Qt.CheckState.Unchecked)
        if not self.shape_merge_check.isChecked():
            selected = self._get_selected_shape_fids()
            self.shape_info_label.setText(tr(f"{len(selected)} of {len(self._shape_features)} features selected"))

    def _get_selected_shape_fids(self):
        """Return list of selected feature IDs."""
        fids = []
        for i in range(self.shape_feature_list.count()):
            item = self.shape_feature_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                fids.append(item.data(Qt.ItemDataRole.UserRole))
        return fids

    def _shape_search_signature(self):
        """The vector area of a search: layer, label field, merge choice and checked features; None without one."""
        layer = getattr(self, "_shape_vector_layer", None)
        if layer is None:
            return None
        return (
            layer.source(),
            self.shape_attr_combo.currentIndex(),
            self.shape_merge_check.isChecked(),
            tuple(sorted(str(fid) for fid in self._get_selected_shape_fids())),
        )

    def _clear_shapefile(self):
        """Clear shapefile selection and re-enable extent/tiles."""
        self.shape_file_input.clear()
        self.shape_feature_list.clear()
        self.shape_attr_combo.clear()
        self.shape_attr_combo.setEnabled(False)
        self.shape_layer_combo.clear()
        self.shape_layer_combo.setEnabled(False)
        self.shape_merge_check.setChecked(False)
        self.shape_info_label.setText("")
        self._disconnect_project_layer()
        self._shape_vector_layer = None
        self._shape_features = []
        self._shape_file_path = None
        self._shape_suspended = False
        self._apply_spatial_locks()

    def _get_shape_bbox(self):
        """Get bounding box from selected shapefile features (or all if merged)."""
        if not self._shape_vector_layer or not self._shape_features or getattr(self, "_shape_suspended", False):
            return None

        if self.shape_merge_check.isChecked():
            # Use all features
            fids = [f[0] for f in self._shape_features]
        else:
            fids = self._get_selected_shape_fids()

        if not fids:
            return None

        # Build combined extent from selected features
        combined_extent = None
        for fid, name, geom in self._shape_features:
            if fid in fids:
                bbox = geom.boundingBox()
                if combined_extent is None:
                    combined_extent = QgsRectangle(bbox)
                else:
                    combined_extent.combineExtentWith(bbox)

        if combined_extent is None:
            return None

        # Transform to EPSG:4326 if needed
        vlayer_crs = self._shape_vector_layer.crs()
        if vlayer_crs.authid() != "EPSG:4326":
            transform = QgsCoordinateTransform(
                vlayer_crs, QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance()
            )
            combined_extent = transform.transformBoundingBox(combined_extent)

        return [
            combined_extent.xMinimum(),
            combined_extent.yMinimum(),
            combined_extent.xMaximum(),
            combined_extent.yMaximum(),
        ]

    def _get_shape_cutline_geometry(self):
        """Get the merged/dissolved geometry from selected features for VRT clipping.
        Returns the path to a temporary GeoJSON file with the cutline geometry, or None."""
        if not self._shape_vector_layer or not self._shape_features:
            return None

        if self.shape_merge_check.isChecked():
            fids = [f[0] for f in self._shape_features]
        else:
            fids = self._get_selected_shape_fids()

        if not fids:
            return None

        from qgis.core import QgsGeometry

        # Collect and merge geometries
        geometries = []
        for fid, name, geom in self._shape_features:
            if fid in fids:
                geometries.append(QgsGeometry(geom))

        if not geometries:
            return None

        # Dissolve/merge all geometries into one
        merged = geometries[0]
        for g in geometries[1:]:
            merged = merged.combine(g)

        # Transform to EPSG:4326 if needed
        vlayer_crs = self._shape_vector_layer.crs()
        if vlayer_crs.authid() != "EPSG:4326":
            transform = QgsCoordinateTransform(
                vlayer_crs, QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance()
            )
            merged.transform(transform)

        # Write to temp GeoJSON for GDAL cutline
        import json as _json

        geojson = _json.loads(merged.asJson())
        feature_collection = {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": {}, "geometry": geojson}],
        }

        fd, cutline_path = tempfile.mkstemp(suffix=".geojson", prefix="bdc_shape_cutline_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            _json.dump(feature_collection, f)

        return cutline_path

    def _get_feature_cutline_geometry(self, feat_name):
        """Get the geometry of a single named shape feature for VRT clipping.
        Returns the path to a temporary GeoJSON file with the cutline geometry, or None."""
        if not feat_name or not self._shape_vector_layer or not self._shape_features:
            return None

        from qgis.core import QgsGeometry

        for fid, name, geom in self._shape_features:
            if name != feat_name:
                continue

            feat_geom = QgsGeometry(geom)
            vlayer_crs = self._shape_vector_layer.crs()
            if vlayer_crs.authid() != "EPSG:4326":
                transform = QgsCoordinateTransform(
                    vlayer_crs, QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance()
                )
                feat_geom.transform(transform)

            import json as _json

            geojson = _json.loads(feat_geom.asJson())
            feature_collection = {
                "type": "FeatureCollection",
                "features": [{"type": "Feature", "properties": {}, "geometry": geojson}],
            }

            safe_name = re.sub(r"[^\w-]", "_", feat_name)[:40]
            fd, cutline_path = tempfile.mkstemp(suffix=".geojson", prefix=f"bdc_cutline_{safe_name}_")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                _json.dump(feature_collection, f)
            return cutline_path

        return None

    def _feature_area(self, fid):
        """(name, area tag, WKT in EPSG:4326) of one listed feature, or None.

        The tag is ``<layer>-<feature>``; the feature id is added when the
        label repeats inside the layer, so each feature keeps its own files.
        """
        for f_fid, f_name, f_geom in self._shape_features:
            if f_fid == fid:
                wkt = _to_wgs84(f_geom, self._shape_vector_layer.crs()).asWkt(6)
                repeated = sum(1 for _fid, name, _geom in self._shape_features if name == f_name) > 1
                layer = self._shape_vector_layer.name()
                tag = area_tag(layer, f_name, f"fid{f_fid}" if repeated else None)
                return f_name, tag, wkt
        return None

    def _merged_area(self):
        """(area tag, WKT in EPSG:4326) of every listed feature dissolved into one."""
        from qgis.core import QgsGeometry

        geometries = [QgsGeometry(geom) for _fid, _name, geom in self._shape_features]
        if not geometries:
            return None
        merged = QgsGeometry.unaryUnion(geometries) if len(geometries) > 1 else geometries[0]
        wkt = _to_wgs84(merged, self._shape_vector_layer.crs()).asWkt(6)
        return area_tag(self._shape_vector_layer.name() or "shape", "merged"), wkt

    @staticmethod
    def _crop_area(bbox):
        """(label, area tag) of an extent crop: its corner coordinates."""
        return f"Crop {crop_label(bbox)}", crop_tag(bbox)

    def _cutline_for_item(self, item):
        """Cutline (temporary GeoJSON path) of a crop or vector-feature mosaic.

        Built from the geometry recorded when the search ran, so changing the
        extent or the vector file afterwards does not change what a result
        covers. Results without a recorded geometry fall back to the current
        extent or vector selection.
        """
        props = getattr(item, "properties", {}) or {}
        wkt = props.get("bdc:area_wkt")
        if wkt:
            import json as _json

            from qgis.core import QgsGeometry

            geom = QgsGeometry.fromWkt(wkt)
            if geom and not geom.isNull():
                return _write_cutline(_json.loads(geom.asJson()))
        if props.get("bdc:is_extent_crop"):
            return self._get_extent_cutline()
        feat_name = props.get("bdc:feature_name")
        cutline = self._get_feature_cutline_geometry(feat_name) if feat_name else None
        return cutline or self._get_shape_cutline_geometry()

    def _is_shape_search_active(self):
        """Return True when the current search should behave as shape-based mosaic mode."""
        return bool(
            self._shape_vector_layer
            and self._shape_features
            and not getattr(self, "_shape_suspended", False)
            and not self.extent_box.isActive()
            and not self.get_tiles_list()
        )

    def _build_shape_mosaic_items(self, items, feature_name=None, area=None, area_wkt=None, feature_fid=None):
        """Group intersecting STAC items by date so results appear as mosaics instead of tiles."""
        from ..stac.parsers import group_items_by_date
        from ..ui.result_widgets import _ShapeMosaicItem

        mosaics = []
        for key, group_dt, group_items in group_items_by_date(items):
            mosaics.append(
                _ShapeMosaicItem(
                    key,
                    group_dt,
                    group_items,
                    feature_name=feature_name,
                    area=area,
                    area_wkt=area_wkt,
                    feature_fid=feature_fid,
                )
            )
        return mosaics

    # ------------------------------------------------------------------
    #  Offer a BDC reference grid when canvas is empty
    # ------------------------------------------------------------------

    # BDC standard grids — see https://brazil-data-cube.github.io/specifications/bdc-grid.html
    # BDC_SM_V2 : 110 × 110 km  tiles (small)
    # BDC_MD_V2 : 220 × 220 km  tiles (medium)
    # BDC_LG_V2 : 663 × 663 km  tiles (large)
    _GRID_OPTIONS = [
        ("BDC_SM_V2", "BDC_SM_V2", "110 × 110 km  — small tiles"),
        ("BDC_MD_V2", "BDC_MD_V2", "220 × 220 km  — medium tiles"),
        ("BDC_LG_V2", "BDC_LG_V2", "663 × 663 km  — large tiles"),
    ]

    def _offer_reference_grid(self):
        """Show a dialog to add a BDC tile grid as spatial reference layer.

        Opens when the user activates Extent / Draw on Canvas with no layers in
        the project.  Uses the same WFS loading path as load_grid().
        """
        dlg = QDialog(self)
        dlg.setWindowTitle("Load BDC Grid Reference")
        dlg.setFixedWidth(460)

        main_layout = QHBoxLayout(dlg)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(16)
        main_layout.addLayout(_reference_grid_explanation(), 1)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color: #ccc;")
        main_layout.addWidget(sep)

        chosen = {}
        main_layout.addLayout(_grid_choice_column(dlg, self._GRID_OPTIONS, chosen), 1)

        if dlg.exec() != QDialog.DialogCode.Accepted or "grid" not in chosen:
            return
        self._load_reference_grid(chosen["grid"])

    def _load_reference_grid(self, grid_name: str):
        """Load *grid_name* via WFS, style it and zoom to Brazil extent.

        Uses the same WFS URI and apply_grid_style() as the regular Load Grid
        button so the result is visually identical.
        """
        from qgis.core import (
            QgsCoordinateReferenceSystem,
            QgsCoordinateTransform,
            QgsRectangle,
        )
        from qgis.PyQt.QtCore import QCoreApplication

        from ..stac.fallback import BRAZIL_BBOX, bdc_grid_wfs_uri

        self._set_status(f"Loading grid {grid_name} from the BDC (WFS)...", "info")
        QCoreApplication.processEvents()

        wfs_uri = bdc_grid_wfs_uri(grid_name)
        layer = QgsVectorLayer(wfs_uri, grid_name, "WFS")

        if not layer or not layer.isValid():
            from qgis.PyQt.QtWidgets import QMessageBox

            QMessageBox.warning(
                self,
                "Grid Load Failed",
                f"Could not load {grid_name} from BDC GeoServer.\nCheck your internet connection and try again.",
            )
            self._set_status(f"Grid loading failed: {grid_name} could not be read from the BDC.", "error")
            return

        # Style identical to the regular grid panel
        self.apply_grid_style(layer)
        QgsProject.instance().addMapLayer(layer)

        # Zoom to Brazil extent
        brazil_extent = QgsRectangle(BRAZIL_BBOX[0], BRAZIL_BBOX[1], BRAZIL_BBOX[2], BRAZIL_BBOX[3])
        canvas = self.iface.mapCanvas()
        canvas_crs = canvas.mapSettings().destinationCrs()
        layer_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        if canvas_crs.isValid() and canvas_crs != layer_crs:
            transform = QgsCoordinateTransform(layer_crs, canvas_crs, QgsProject.instance())
            brazil_extent = transform.transformBoundingBox(brazil_extent)
        canvas.setExtent(brazil_extent)
        canvas.refresh()

        self._set_status(f"Grid {grid_name} added to the map. Draw on Canvas is ready.", "ok")
        self.iface.mainWindow().statusBar().showMessage(tr(f"Grid {grid_name} added to the map."), 5000)
        # Bring the plugin dialog back to front
        self.showNormal()
        self.raise_()

        # Keep Extent open, ready for Draw on Canvas
        self.extent_box.setCollapsed(False)
        self.activateWindow()
