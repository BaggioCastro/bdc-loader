# -*- coding: utf-8 -*-
"""
Grid and tile management handler for BDCLoaderDialog.

Provides the GridManager mixin that handles BDC tile-grid lifecycle:
WFS download, local caching, zip extraction, QGIS map layer rendering
with labeling, and interactive tile selection.
"""

import logging
import os
import shutil
import tempfile
import urllib.parse
import urllib.request
import webbrowser
import zipfile

_logger = logging.getLogger("bdc_loader")

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFillSymbol,
    QgsPalLayerSettings,
    QgsProject,
    QgsRectangle,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)
from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStyle,
    QVBoxLayout,
)

from ..config import PLUGIN_VERSION
from ..i18n import count_label, failure_text, set_text, tr
from ..net import TRANSFER_S
from ..stac.fallback import BRAZIL_BBOX, bdc_grid_wfs_uri
from ..stac.parsers import (
    MGRS_PATTERN,
    ROW_PATH_PATTERN,
    STG_PATTERN,
    TILE_PATTERN,
    WRS2_PATTERN,
)
from ..ui.result_widgets import _format_size
from .catalog_data import COLLECTIONS, GRID_URLS
from .ui_wait import run_in_worker


def _safe_extract_zip(zip_ref, target_dir):
    """Extract a ZIP archive to target_dir, rejecting path-traversal entries."""
    real_target = os.path.realpath(target_dir)
    for member in zip_ref.infolist():
        member_path = os.path.realpath(os.path.join(real_target, member.filename))
        if not member_path.startswith(real_target + os.sep) and member_path != real_target:
            raise ValueError(f"Rejected ZIP entry with path traversal: {member.filename}")
        zip_ref.extract(member, target_dir)


_GRID_SHAPEFILE_PARTS = (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qmd", ".qpj", ".cst")


def _stream_grid(url, path, progress, cancelled):
    """Stream ``url`` into ``path`` in 64 KiB chunks; False when ``cancelled()`` turns true.

    Runs in a worker: it only fills ``progress`` ("done", "total" bytes).
    """
    req = urllib.request.Request(url, headers={"User-Agent": f"BDC-Loader-Plugin/{PLUGIN_VERSION}"})
    with urllib.request.urlopen(req, timeout=TRANSFER_S) as response:
        progress["total"] = int(response.headers.get("Content-Length") or 0)
        with open(path, "wb") as f:
            while True:
                if cancelled():
                    return False
                chunk = response.read(64 * 1024)
                if not chunk:
                    return True
                f.write(chunk)
                progress["done"] += len(chunk)


def _rename_grid_files(grid_dir, grid_name):
    """Rename the first extracted file of each shapefile part to `grid_name` plus its extension."""
    for ext in _GRID_SHAPEFILE_PARTS:
        matches = [f for f in os.listdir(grid_dir) if f.endswith(ext)]
        if not matches:
            continue
        old_path = os.path.join(grid_dir, matches[0])
        new_path = os.path.join(grid_dir, f"{grid_name}{ext}")
        if old_path != new_path:
            if os.path.exists(new_path):
                os.remove(new_path)
            os.rename(old_path, new_path)


def _convert_kml_grid(kml_path, gpkg_path):
    """Convert a KML grid to GeoPackage and remove the KML; the KML stays when conversion fails."""
    try:
        kml_layer = QgsVectorLayer(kml_path, "temp_kml", "ogr")
        if kml_layer.isValid() and kml_layer.featureCount() > 0:
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.fileEncoding = "UTF-8"
            error_code = QgsVectorFileWriter.writeAsVectorFormatV3(
                kml_layer, gpkg_path, QgsProject.instance().transformContext(), options
            )
            if error_code[0] == QgsVectorFileWriter.WriterError.NoError:
                os.remove(kml_path)
            elif os.path.exists(gpkg_path):
                os.remove(gpkg_path)
        del kml_layer
    except Exception:
        _logger.warning("KML-to-GPKG conversion failed", exc_info=True)
        if os.path.exists(gpkg_path):
            os.remove(gpkg_path)


def _grid_error_mailto(grid_name, error_text):
    """mailto: link to the BDC team with the grid error in the body."""
    subject = urllib.parse.quote(f"[BDC Loader] Grid download error {grid_name}")
    body = urllib.parse.quote(
        f"Hello BDC team,\n\nI encountered an error while downloading grid {grid_name} in the BDC Loader plugin.\n\n"
        f"--- Error details ---\n{error_text}\n\n"
        f"Please check if the service is available.\n\nThank you."
    )
    return f"mailto:brazildatacube@inpe.br?subject={subject}&body={body}"


def _add_error_header(layout, dlg):
    """Critical icon, title and a line on the likely cause, followed by a separator."""
    header = QHBoxLayout()
    icon_lbl = QLabel()
    icon_lbl.setPixmap(dlg.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxCritical).pixmap(40, 40))
    header.addWidget(icon_lbl)

    title_lbl = QLabel(
        "<b style='font-size:13px; color:#c0392b;'>Grid download failed</b><br>"
        "<span style='font-size:11px; color:#444;'>The server may be down or unavailable at the moment.</span>"
    )
    title_lbl.setWordWrap(True)
    header.addWidget(title_lbl, stretch=1)
    layout.addLayout(header)

    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setStyleSheet("color: #ddd;")
    layout.addWidget(sep)


def _add_error_details(layout, error_text):
    """Guidance line and the selectable error text."""
    info_lbl = QLabel(
        "Please try again later. If the problem persists, contact the Brazil Data Cube team with the error below."
    )
    info_lbl.setWordWrap(True)
    info_lbl.setStyleSheet("font-size: 11px; color: #333;")
    layout.addWidget(info_lbl)

    error_box = QPlainTextEdit()
    error_box.setPlainText(error_text)
    error_box.setReadOnly(True)
    error_box.setFixedHeight(90)
    error_box.setStyleSheet("""
        QPlainTextEdit {
            font-family: monospace;
            font-size: 10px;
            background-color: #f6f8fa;
            border: 1px solid #d0d7de;
            border-radius: 4px;
            padding: 4px;
            color: #c0392b;
        }
    """)
    layout.addWidget(error_box)

    copy_hint = QLabel(
        "<span style='font-size:9px; color:#888;'>Select the text above and press Ctrl+C to copy.</span>"
    )
    layout.addWidget(copy_hint)


def _add_error_buttons(layout, dlg, mailto_url):
    """Email BDC Team, which opens `mailto_url`, and Close."""
    btn_row = QHBoxLayout()
    btn_row.setSpacing(8)

    email_btn = QPushButton("  Email BDC Team")
    email_btn.setFixedHeight(34)
    email_btn.setIcon(dlg.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation))
    email_btn.setStyleSheet("""
        QPushButton {
            background-color: #0969da;
            color: white;
            font-size: 11px;
            font-weight: bold;
            padding: 6px 16px;
            border: none;
            border-radius: 6px;
        }
        QPushButton:hover { background-color: #0860ca; }
    """)
    email_btn.clicked.connect(lambda: webbrowser.open(mailto_url))
    btn_row.addWidget(email_btn)
    btn_row.addStretch()

    ok_btn = QPushButton("Close")
    ok_btn.setFixedHeight(34)
    ok_btn.setFixedWidth(90)
    ok_btn.setStyleSheet("""
        QPushButton {
            background-color: #f6f8fa;
            color: #24292f;
            font-size: 11px;
            font-weight: bold;
            padding: 6px 16px;
            border: 1px solid #d0d7de;
            border-radius: 6px;
        }
        QPushButton:hover { background-color: #eaeef2; }
    """)
    ok_btn.clicked.connect(dlg.accept)
    btn_row.addWidget(ok_btn)
    layout.addLayout(btn_row)


class GridManager:
    """Provides grid download, tile selection, and extent management."""

    def get_grid_path(self, grid_name: str) -> str:
        return os.path.join(self.grids_dir, grid_name, f"{grid_name}.shp")

    def is_grid_downloaded(self, grid_name: str) -> bool:
        grid_dir = os.path.join(self.grids_dir, grid_name)
        return (
            os.path.exists(self.get_grid_path(grid_name))
            or os.path.exists(os.path.join(grid_dir, f"{grid_name}.gpkg"))
            or os.path.exists(os.path.join(grid_dir, f"{grid_name}.kml"))
        )

    def _set_tiles_mode(self, enabled: bool):
        """Enable/disable the tile controls, then apply the area-filter locks.

        A collection without a tile system disables and collapses the Tiles
        group. Otherwise the inner controls follow ``enabled`` and the group
        itself is greyed out only while Extent or Vector File is in use.
        """
        idx = self.collection_combo.currentIndex() if hasattr(self, "collection_combo") else 0
        collection_name = (
            self.collection_combo.itemData(idx, Qt.ItemDataRole.UserRole) if hasattr(self, "collection_combo") else ""
        )
        if not collection_name and hasattr(self, "collection_combo"):
            collection_name = self.collection_combo.currentText().replace("[CUBE] ", "").replace("[COLLECTION] ", "")
        config = COLLECTIONS.get(collection_name, {})
        has_tiles = config.get("has_tiles", True)

        if not has_tiles:
            if hasattr(self, "tiles_group"):
                self.tiles_group.setEnabled(False)
                self.tiles_group.setCollapsed(True)
            self.load_grid_btn.setEnabled(False)
            self.select_tiles_btn.setEnabled(False)
            self.finish_tiles_btn.setEnabled(False)
            self.tiles_input.setEnabled(False)
            self.selected_tiles_list.setEnabled(False)
            self.tile_filter_btn.setEnabled(False)
            self.clear_tiles()
            self.extent_box.setEnabled(True)
            if hasattr(self, "tiles_input"):
                set_text(self.tiles_input, "No tile grid available", "placeholder")
            self._apply_spatial_locks()
            return

        if hasattr(self, "tiles_group"):
            self.tiles_group.setEnabled(True)
        self.load_grid_btn.setEnabled(enabled)
        self.select_tiles_btn.setEnabled(False if not enabled else (self.grid_layer is not None))
        self.finish_tiles_btn.setEnabled(False)
        self.tiles_input.setEnabled(enabled)
        self.selected_tiles_list.setEnabled(enabled)
        self.tile_filter_btn.setEnabled(enabled)
        if hasattr(self, "tiles_input"):
            self.tiles_input.setPlaceholderText("031023, 031024, ...")
        if not enabled:
            self.clear_tiles()
            self.extent_box.setEnabled(True)
        self._apply_spatial_locks()

    def update_grid_status(self):
        collection_name = self._current_collection_name()
        config = COLLECTIONS.get(collection_name, {})
        if not config.get("has_tiles", True):
            self.grid_status_label.setText(tr("Collection has no tile system"))
            self.grid_status_label.setStyleSheet("color: #e67e22; font-size: 10px;")
            self._set_tiles_mode(False)
            if hasattr(self, "tiles_input"):
                set_text(self.tiles_input, "No tile grid available", "placeholder")
            self.grid_layer = None
            return
        elif hasattr(self, "tiles_input"):
            self.tiles_input.setPlaceholderText("031023, 031024, ...")
        grid_name = config.get("grid", "BDC_SM_V2")

        existing_layers = QgsProject.instance().mapLayersByName(grid_name)
        if existing_layers and existing_layers[0].isValid():
            self.grid_layer = existing_layers[0]
            self.select_tiles_btn.setEnabled(True)
            self.grid_status_label.setText(tr(f"Grid {grid_name} loaded"))
            self.grid_status_label.setStyleSheet("color: green; font-size: 10px;")
            return

        if os.path.exists(self.get_grid_path(grid_name)):
            self.grid_status_label.setText(tr(f"Grid {grid_name} available locally"))
            self.grid_status_label.setStyleSheet("color: blue; font-size: 10px;")
        else:
            self.grid_status_label.setText(tr(f"Grid {grid_name} — click Load Grid (WFS)"))
            self.grid_status_label.setStyleSheet("color: #0969da; font-size: 10px;")

        self.select_tiles_btn.setEnabled(False)
        self.grid_layer = None

    def download_grid(self, grid_name: str) -> bool:
        """Download and extract tile grid. Supports ZIP, KML and other formats.

        Uses chunked download to keep UI responsive with real progress and cancel support.
        """
        url = GRID_URLS.get(grid_name)
        if not url:
            QMessageBox.warning(self, "Error", f"Download URL not available for grid {grid_name}")
            return False

        # Clean old files (e.g. old MGRS KML when switching to shapefile)
        grid_dir = os.path.join(self.grids_dir, grid_name)
        if os.path.exists(grid_dir):
            shutil.rmtree(grid_dir, ignore_errors=True)

        self._begin_grid_download(grid_name)
        file_ext = ".kml" if url.endswith(".kml") else ".zip"  # a WFS answers with a shape-zip
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=file_ext, delete=False) as tmp_file:
                tmp_path = tmp_file.name
            if not self._fetch_grid_file(url, tmp_path, grid_name):
                self._set_status("Grid download cancelled.", "warning")
                return False

            os.makedirs(grid_dir, exist_ok=True)
            if file_ext == ".zip":
                self._set_status(f"Extracting grid {grid_name}...", "info")
                QCoreApplication.processEvents()
                with zipfile.ZipFile(tmp_path, "r") as zip_ref:
                    _safe_extract_zip(zip_ref, grid_dir)
                _rename_grid_files(grid_dir, grid_name)
            else:
                self._set_status(f"Converting grid {grid_name} to GeoPackage...", "info")
                QCoreApplication.processEvents()
                kml_path = os.path.join(grid_dir, f"{grid_name}.kml")
                shutil.move(tmp_path, kml_path)
                tmp_path = None
                _convert_kml_grid(kml_path, os.path.join(grid_dir, f"{grid_name}.gpkg"))

            self._set_status(f"Grid {grid_name} downloaded.", "success")
            return True

        except Exception as e:
            self._set_status(failure_text("Grid download", e), "error")
            self._show_grid_download_error(grid_name, url, e)
            return False
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            self.progress_bar.setVisible(False)
            self._hide_cancel_button()

    def _begin_grid_download(self, grid_name):
        """Show a busy progress bar and the Cancel button, which stops the download while it runs."""
        self._grid_download_cancelled = False
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self._set_status(f"Downloading grid {grid_name}...", "download")
        self._show_cancel_button(self._cancel_grid_download)
        QCoreApplication.processEvents()

    def _fetch_grid_file(self, url, path, grid_name):
        """Download ``url`` into ``path`` in a worker, showing the progress; False when cancelled."""
        progress = {"done": 0, "total": 0}

        def _show_progress():
            done, total = progress["done"], progress["total"]
            if not total:
                return
            pct = int(done * 100 / total)
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(pct)
            self._set_status(
                f"Downloading grid {grid_name}: {_format_size(done)} of {_format_size(total)}",
                "download",
            )

        return run_in_worker(
            _stream_grid, url, path, progress, lambda: self._grid_download_cancelled, on_wait=_show_progress
        )

    def _cancel_grid_download(self):
        """Cancel an ongoing grid download."""
        self._grid_download_cancelled = True

    def _show_grid_download_error(self, grid_name: str, url: str, error: Exception):
        """Show download error dialog with BDC contact information."""
        error_text = f"Grid: {grid_name}\nURL: {url}\nError: {error}"

        dlg = QDialog(self)
        dlg.setWindowTitle("Error downloading grid")
        dlg.setMinimumWidth(520)
        dlg.setModal(True)

        layout = QVBoxLayout(dlg)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)
        _add_error_header(layout, dlg)
        _add_error_details(layout, error_text)
        _add_error_buttons(layout, dlg, _grid_error_mailto(grid_name, error_text))
        dlg.exec()

    def apply_grid_style(self, layer):
        try:
            symbol = QgsFillSymbol.createSimple(
                {"color": "255,0,0,30", "outline_color": "255,0,0,180", "outline_width": "0.5"}
            )
            layer.renderer().setSymbol(symbol)

            label_settings = QgsPalLayerSettings()
            field_names = [f.name() for f in layer.fields()]

            has_path_row_fields = ("path" in field_names or "PATH" in field_names) and (
                "row" in field_names or "ROW" in field_names
            )
            has_path_row_combined = "path_row" in field_names or "PATH_ROW" in field_names

            if has_path_row_fields:
                path_f = "path" if "path" in field_names else "PATH"
                row_f = "row" if "row" in field_names else "ROW"
                label_settings.isExpression = True
                label_settings.fieldName = (
                    f"lpad(to_string(\"{path_f}\"), 3, '0') || '/' || lpad(to_string(\"{row_f}\"), 3, '0')"
                )
            elif has_path_row_combined:
                pr_f = "path_row" if "path_row" in field_names else "PATH_ROW"
                label_settings.isExpression = True
                label_settings.fieldName = f"replace(\"{pr_f}\", '_', '/')"
            else:
                field_name = "tile"
                for fname in [
                    "tile",
                    "TILE",
                    "Name",
                    "name",
                    "NAME",
                    "id",
                    "ID",
                    "TILE_ID",
                    "tile_id",
                    "grid_id",
                    "GRID_ID",
                ]:
                    if fname in field_names:
                        field_name = fname
                        break
                label_settings.isExpression = False
                label_settings.fieldName = field_name

            label_settings.enabled = True

            text_format = QgsTextFormat()
            text_format.setSize(8)
            text_format.setColor(QColor(139, 0, 0))

            buffer_settings = QgsTextBufferSettings()
            buffer_settings.setEnabled(True)
            buffer_settings.setSize(1)
            buffer_settings.setColor(QColor(255, 255, 255))
            text_format.setBuffer(buffer_settings)

            label_settings.setFormat(text_format)
            labeling = QgsVectorLayerSimpleLabeling(label_settings)
            layer.setLabeling(labeling)
            layer.setLabelsEnabled(True)
        except Exception as _e:
            _logger.debug("Failed to enable grid labels: %s", _e)

    def _load_grid_wfs(self, grid_name: str):
        """Try loading grid directly from INPE BDC GeoServer as WFS layer (no download).

        Returns QgsVectorLayer or None if WFS loading fails.
        """
        try:
            self._set_status(f"Loading grid {grid_name} from the BDC (WFS)...", "info")
            QCoreApplication.processEvents()

            wfs_uri = bdc_grid_wfs_uri(grid_name)

            layer = QgsVectorLayer(wfs_uri, grid_name, "WFS")
            if layer.isValid() and layer.featureCount() >= 0:
                return layer
            return None
        except Exception:
            _logger.warning("WFS grid load failed for %s", grid_name, exc_info=True)
            return None

    def load_grid(self):
        """Load tile grid for the current collection.

        Tries WFS remote loading first (fast, no download), falls back to local files or download.
        """
        collection_name = self._current_collection_name()
        config = COLLECTIONS.get(collection_name, {})
        grid_name = config.get("grid", "BDC_SM_V2")

        # Check if already loaded in project
        existing_layers = QgsProject.instance().mapLayersByName(grid_name)
        if existing_layers and existing_layers[0].isValid():
            self.grid_layer = existing_layers[0]
            self.update_grid_status()
            QMessageBox.information(self, "Grid Loaded", f"Grid {grid_name} is already in the project")
            return

        layer = None

        # 1) Try WFS remote loading (no download needed)
        layer = self._load_grid_wfs(grid_name)

        if not layer:
            # 2) Try local files (previously downloaded)
            if self.is_grid_downloaded(grid_name):
                # Check for old KML format
                grid_dir = os.path.join(self.grids_dir, grid_name)
                shp_exists = os.path.exists(self.get_grid_path(grid_name))
                gpkg_exists = os.path.exists(os.path.join(grid_dir, f"{grid_name}.gpkg"))
                kml_exists = os.path.exists(os.path.join(grid_dir, f"{grid_name}.kml"))
                if kml_exists and not shp_exists and not gpkg_exists:
                    msg = QMessageBox.question(
                        self,
                        "Grid Update Available",
                        f"Grid {grid_name} is stored as KML (old format).\n"
                        f"Download optimized shapefile version?\n\n"
                        f"This will be faster and use Brazil-only tiles.",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    )
                    if msg == QMessageBox.StandardButton.Yes:
                        if not self.download_grid(grid_name):
                            return

                shp_path = self.get_grid_path(grid_name)
                gpkg_path = os.path.join(self.grids_dir, grid_name, f"{grid_name}.gpkg")
                kml_path = os.path.join(self.grids_dir, grid_name, f"{grid_name}.kml")

                if os.path.exists(shp_path):
                    layer = QgsVectorLayer(shp_path, grid_name, "ogr")
                elif os.path.exists(gpkg_path):
                    layer = QgsVectorLayer(gpkg_path, grid_name, "ogr")
                elif os.path.exists(kml_path):
                    layer = QgsVectorLayer(kml_path, grid_name, "ogr")

            if not layer or not layer.isValid():
                # 3) Download shapefile as last resort
                msg = QMessageBox.question(
                    self,
                    "Download Required",
                    f"Grid {grid_name} could not be loaded from WFS.\nDownload shapefile now?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if msg != QMessageBox.StandardButton.Yes:
                    return
                if not self.download_grid(grid_name):
                    return

                shp_path = self.get_grid_path(grid_name)
                gpkg_path = os.path.join(self.grids_dir, grid_name, f"{grid_name}.gpkg")
                if os.path.exists(shp_path):
                    layer = QgsVectorLayer(shp_path, grid_name, "ogr")
                elif os.path.exists(gpkg_path):
                    layer = QgsVectorLayer(gpkg_path, grid_name, "ogr")

        if not layer or not layer.isValid():
            QMessageBox.critical(self, "Error", f"Could not load grid {grid_name}")
            return

        self.apply_grid_style(layer)
        QgsProject.instance().addMapLayer(layer)
        self.grid_layer = layer
        self.update_grid_status()

        # Zoom to Brazil extent (not full layer extent which may include non-Brazil tiles)
        brazil_extent = QgsRectangle(BRAZIL_BBOX[0], BRAZIL_BBOX[1], BRAZIL_BBOX[2], BRAZIL_BBOX[3])
        canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        layer_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        if canvas_crs.isValid() and canvas_crs != layer_crs:
            transform = QgsCoordinateTransform(layer_crs, canvas_crs, QgsProject.instance())
            brazil_extent = transform.transformBoundingBox(brazil_extent)
        self.iface.mapCanvas().setExtent(brazil_extent)
        self.iface.mapCanvas().refresh()
        self._set_status(f"Grid {grid_name} added to the map.", "success")

    def prepare_extent_box(self):
        self.extent_box.setOutputCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
        map_canvas = self.iface.mapCanvas()
        self.extent_box.setCurrentExtent(
            map_canvas.mapSettings().destinationCrs().bounds(), map_canvas.mapSettings().destinationCrs()
        )
        self.extent_box.setMapCanvas(map_canvas)

    def get_bbox_from_extent(self):
        if not self.extent_box.isActive() or not self.extent_box.hasExtent():
            return None
        extent = self.extent_box.outputExtent()
        return [extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum()]

    def is_extent_crop_mode(self):
        """Return True if the user selected Crop for the extent mode."""
        return self.extent_box.isActive() and hasattr(self, "_extent_mode_crop") and self._extent_mode_crop.isChecked()

    def _get_extent_cutline(self):
        """Generate a temporary GeoJSON cutline from the current extent bbox.
        Returns the file path, or None if extent is not active / not in crop mode.
        """
        if not self.is_extent_crop_mode():
            return None
        bbox = self.get_bbox_from_extent()
        if not bbox:
            return None
        import json as _json

        xmin, ymin, xmax, ymax = bbox
        fc = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[xmin, ymin], [xmax, ymin], [xmax, ymax], [xmin, ymax], [xmin, ymin]]],
                    },
                }
            ],
        }
        fd, path = tempfile.mkstemp(suffix=".geojson", prefix="bdc_extent_cutline_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            _json.dump(fc, f)
        return path

    def start_tile_selection(self):
        if not self.grid_layer or not self.grid_layer.isValid():
            QMessageBox.warning(self, "Error", "Load the grid first!")
            return

        self.previous_tool = self.iface.mapCanvas().mapTool()
        from ..widgets.tile_select_tool import TileSelectTool

        self.tile_select_tool = TileSelectTool(
            self.iface.mapCanvas(), self.grid_layer, self.on_tile_selected, self.finish_tile_selection
        )
        self.iface.mapCanvas().setMapTool(self.tile_select_tool)

        self.select_tiles_btn.setEnabled(False)
        self.finish_tiles_btn.setEnabled(True)
        self.showMinimized()

        self.iface.messageBar().pushInfo("BDC Loader", tr("Click a tile on the map, or press Esc to cancel."))

    def on_tile_selected(self, tile_id: str):
        existing = [self.selected_tiles_list.item(i).text() for i in range(self.selected_tiles_list.count())]
        if tile_id not in existing:
            self.selected_tiles_list.addItem(tile_id)
            self.update_tiles_input()
        # End selection mode and bring dialog back
        self.finish_tile_selection()

    def finish_tile_selection(self):
        # Turn off the selection tool and restore the previous one
        if self.tile_select_tool:
            self.iface.mapCanvas().unsetMapTool(self.tile_select_tool)
            self.tile_select_tool = None
        if self.previous_tool:
            self.iface.mapCanvas().setMapTool(self.previous_tool)
        else:
            try:
                self.iface.actionPan().trigger()
            except Exception as _e:
                _logger.debug("Could not restore pan action: %s", _e)
        try:
            self.iface.messageBar().clearWidgets()
        except Exception as _e:
            _logger.debug("Could not clear message bar: %s", _e)
        self.previous_tool = None
        self.select_tiles_btn.setEnabled(True)
        self.finish_tiles_btn.setEnabled(False)
        self._restore_dialog_focus()

    def update_tiles_input(self):
        tiles = [self.selected_tiles_list.item(i).text() for i in range(self.selected_tiles_list.count())]
        self.tiles_input.setText(", ".join(tiles))

    def _copy_tiles_to_clipboard(self):
        """Copy selected tiles to clipboard."""
        text = self.tiles_input.text().strip()
        if text:
            from qgis.PyQt.QtWidgets import QApplication

            QApplication.clipboard().setText(text)
            self._set_status(
                f"{count_label(self.selected_tiles_list.count(), 'tile', 'tiles')} copied to the clipboard.", "success"
            )

    def clear_tiles(self):
        self._tiles_suspended = False
        self.selected_tiles_list.clear()
        self.tiles_input.clear()

    def get_tiles_list(self):
        import re

        if getattr(self, "_tiles_suspended", False):
            return []  # closed Tiles group: kept, not used

        collection_name = self._current_collection_name()
        config = COLLECTIONS.get(collection_name, {})
        if not config.get("has_tiles", True):
            return []

        text = self.tiles_input.text().strip()
        if not text:
            return []
        raw_tiles = [t.strip() for t in text.replace(";", ",").split(",") if t.strip()]
        result = []
        for t in raw_tiles:
            if (
                TILE_PATTERN.match(t)
                or MGRS_PATTERN.match(t)
                or WRS2_PATTERN.match(t)
                or STG_PATTERN.match(t)
                or ROW_PATH_PATTERN.match(t)
            ):
                if ROW_PATH_PATTERN.match(t):
                    parts = re.split(r"[/_ -]", t)
                    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                        t = f"{int(parts[0]):03d}/{int(parts[1]):03d}"
                result.append(t)
        return result
