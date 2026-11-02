"""Map tool that picks grid tiles by clicking them on the canvas."""

import re

from qgis.core import (
    QgsCoordinateTransform,
    QgsFeatureRequest,
    QgsProject,
    QgsRectangle,
)
from qgis.gui import (
    QgsMapToolIdentifyFeature,
)
from qgis.PyQt.QtCore import Qt

from ..stac.parsers import MGRS_PATTERN, ROW_PATH_PATTERN, STG_PATTERN, TILE_PATTERN, WRS2_PATTERN


class TileSelectTool(QgsMapToolIdentifyFeature):
    def __init__(self, canvas, layer, callback, finish_callback=None):
        super().__init__(canvas, layer)
        self.callback = callback
        self.finish_callback = finish_callback
        self.layer = layer
        self.setLayer(layer)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Pre-compute CRS transform from map canvas to layer CRS
        self._transform = None
        try:
            canvas_crs = canvas.mapSettings().destinationCrs()
            layer_crs = layer.crs()
            if canvas_crs.isValid() and layer_crs.isValid() and canvas_crs != layer_crs:
                self._transform = QgsCoordinateTransform(canvas_crs, layer_crs, QgsProject.instance())
        except Exception as exc:
            import logging

            logging.getLogger("bdc_loader").debug("CRS transform init: %s", exc)

    def activate(self):
        super().activate()
        try:
            self.canvas().setFocus(Qt.FocusReason.OtherFocusReason)
        except Exception:
            pass

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            if self.finish_callback:
                self.finish_callback()
            event.accept()
            return
        super().keyPressEvent(event)

    def canvasReleaseEvent(self, event):
        try:
            if not self.layer or not self.layer.isValid():
                if self.finish_callback:
                    self.finish_callback()
                return
        except RuntimeError:
            if self.finish_callback:
                self.finish_callback()
            return

        # Convert screen coords to map CRS, then transform to layer CRS
        map_point = self.toMapCoordinates(event.pos())
        if self._transform:
            point = self._transform.transform(map_point)
        else:
            point = map_point

        tolerance = 5
        search_radius = self.canvas().mapUnitsPerPixel() * tolerance
        # If transform exists, scale search radius approximately
        if self._transform:
            # Use a larger radius to compensate for CRS distortion
            search_radius = max(search_radius, 0.01)
        rect = QgsRectangle(
            point.x() - search_radius, point.y() - search_radius, point.x() + search_radius, point.y() + search_radius
        )

        request = QgsFeatureRequest().setFilterRect(rect)
        features = self.layer.getFeatures(request)

        for feature in features:
            if not feature.geometry().contains(point):
                continue

            tile_id = None
            field_names = [f.name() for f in feature.fields()]

            # 1) Separate path and row fields (Amazonia-1, CBERS, WRS2)
            if ("path" in field_names or "PATH" in field_names) and ("row" in field_names or "ROW" in field_names):
                p_col = "path" if "path" in field_names else "PATH"
                r_col = "row" if "row" in field_names else "ROW"
                try:
                    p_val = int(feature[p_col])
                    r_val = int(feature[r_col])
                    tile_id = f"{p_val:03d}/{r_val:03d}"
                except (ValueError, TypeError):
                    pass

            # 2) Combined path_row field
            if not tile_id and ("path_row" in field_names or "PATH_ROW" in field_names):
                pr_col = "path_row" if "path_row" in field_names else "PATH_ROW"
                val = str(feature[pr_col]).strip()
                parts = re.split(r"[/_ -]", val)
                if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                    tile_id = f"{int(parts[0]):03d}/{int(parts[1]):03d}"

            # 3) Try common single field names (shapefile, GeoPackage, KML, WFS)
            if not tile_id:
                for field_name in [
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
                    if field_name in field_names:
                        val = str(feature[field_name]).strip()
                        if val and val != "NULL":
                            tile_id = val
                            break

            if tile_id and (
                TILE_PATTERN.match(tile_id)
                or MGRS_PATTERN.match(tile_id)
                or WRS2_PATTERN.match(tile_id)
                or STG_PATTERN.match(tile_id)
                or ROW_PATH_PATTERN.match(tile_id)
            ):
                if ROW_PATH_PATTERN.match(tile_id):
                    parts = re.split(r"[/_ -]", tile_id)
                    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                        tile_id = f"{int(parts[0]):03d}/{int(parts[1]):03d}"
                self.callback(tile_id)
                break

    def deactivate(self):
        try:
            if self.canvas():
                self.canvas().unsetCursor()
        except (RuntimeError, AttributeError):
            pass
        super().deactivate()
