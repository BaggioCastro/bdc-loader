# -*- coding: utf-8 -*-
"""
TSLayerManager — Temporary map layer management for the time series panel.

Creates and manages a memory vector layer that displays extracted point
locations on the QGIS map canvas with configurable styling and labels.
"""

import logging
import random

_logger = logging.getLogger("bdc_loader")

from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsFeature,
    QgsGeometry,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsPointXY,
    QgsProject,
    QgsRendererCategory,
    QgsTextFormat,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtGui import QColor

from ..chart.export import history_feature_attributes
from ..timing import POINTS_LAYER_TO_TOP_MS

_TEMP_LAYER_NAME = "BDC TS Points"
_TEMP_LAYER_PROPERTY = "bdc_loader/ts_points"


class TSLayerManager:
    """Temporary point layer creation, styling, and feature management."""

    def _get_or_create_temp_layer(self):
        if self._temp_layer is not None:
            try:
                from qgis.PyQt import sip as _sip

                if _sip.isdeleted(self._temp_layer):
                    self._temp_layer = None
                elif QgsProject.instance().mapLayer(self._temp_layer.id()):
                    return self._temp_layer
                else:
                    self._temp_layer = None
            except Exception:
                self._temp_layer = None

        self._remove_stale_temp_layers()
        self._temp_layer = QgsVectorLayer(
            "Point?crs=EPSG:4326"
            "&field=id:integer"
            "&field=label:string(50)"
            "&field=longitude:double"
            "&field=latitude:double"
            "&field=collection:string(50)"
            "&field=bands:string(500)"
            "&field=start_date:string(10)"
            "&field=end_date:string(10)"
            "&field=n_values:integer",
            _TEMP_LAYER_NAME,
            "memory",
        )

        if self._temp_layer.isValid():
            if self._history:
                self._temp_layer.startEditing()
                for entry in self._history:
                    feat = QgsFeature(self._temp_layer.fields())
                    feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(entry["lon"], entry["lat"])))
                    feat.setAttributes(history_feature_attributes(entry))
                    self._temp_layer.addFeature(feat)
                self._temp_layer.commitChanges()

            self._temp_layer.setCustomProperty(_TEMP_LAYER_PROPERTY, True)
            self._apply_layer_style()
            QgsProject.instance().addMapLayer(self._temp_layer, False)
            QgsProject.instance().layerTreeRoot().insertLayer(0, self._temp_layer)

        return self._temp_layer

    @staticmethod
    def _remove_stale_temp_layers():
        """Remove point layers left by an earlier panel or plugin instance.

        Their history is gone, so keeping them only duplicates "BDC TS Points".
        """
        project = QgsProject.instance()
        stale = [
            layer.id()
            for layer in project.mapLayers().values()
            if layer.customProperty(_TEMP_LAYER_PROPERTY, False)
            or (layer.name() == _TEMP_LAYER_NAME and layer.providerType() == "memory")
        ]
        if stale:
            project.removeMapLayers(stale)

    def remove_temp_layer(self):
        """Remove this panel's point layer from the project."""
        layer, self._temp_layer = self._temp_layer, None
        if layer is None:
            return
        try:
            from qgis.PyQt import sip as _sip

            if not _sip.isdeleted(layer) and QgsProject.instance().mapLayer(layer.id()):
                QgsProject.instance().removeMapLayer(layer.id())
        except Exception as _e:
            _logger.debug("Failed to remove temp point layer: %s", _e)

    def _apply_layer_style(self):
        if not self._temp_layer:
            return

        settings = self._hist_settings
        size = str(settings.get("point_size", 2.8))
        color = settings.get("point_color", "#e74c3c")
        mode = settings.get("color_mode", "single")
        visible = settings.get("visible", True)
        show_labels = settings.get("show_labels", False)

        if mode == "single":
            symbol = QgsMarkerSymbol.createSimple(
                {
                    "name": "circle",
                    "color": color,
                    "outline_color": "#333333",
                    "outline_width": "0.4",
                    "size": size,
                }
            )
            self._temp_layer.renderer().setSymbol(symbol)
        elif mode in ("random", "classified"):
            categories = []
            for entry in self._history:
                rand_color = QColor(random.randint(50, 220), random.randint(50, 220), random.randint(50, 220))
                sym = QgsMarkerSymbol.createSimple(
                    {
                        "name": "circle",
                        "color": rand_color.name(),
                        "outline_color": "#333333",
                        "outline_width": "0.4",
                        "size": size,
                    }
                )
                cat = QgsRendererCategory(entry["id"], sym, entry["label"])
                categories.append(cat)
            renderer = QgsCategorizedSymbolRenderer("id", categories)
            self._temp_layer.setRenderer(renderer)

        try:
            label_settings = QgsPalLayerSettings()
            label_settings.fieldName = "label"
            label_settings.enabled = show_labels
            text_format = QgsTextFormat()
            text_format.setSize(8)
            text_format.setColor(QColor("#2c3e50"))
            label_settings.setFormat(text_format)
            labeling = QgsVectorLayerSimpleLabeling(label_settings)
            self._temp_layer.setLabeling(labeling)
            self._temp_layer.setLabelsEnabled(show_labels)
        except Exception as _e:
            _logger.debug("Failed to apply label settings to temp layer: %s", _e)

        try:
            root = QgsProject.instance().layerTreeRoot()
            node = root.findLayer(self._temp_layer.id())
            if node:
                node.setItemVisibilityChecked(visible)
        except Exception as _e:
            _logger.debug("Failed to set layer visibility in tree: %s", _e)

        self._temp_layer.triggerRepaint()

    def _add_point_to_temp_layer(self, hist_entry):
        layer = self._get_or_create_temp_layer()
        if not layer:
            return
        layer.startEditing()
        feat = QgsFeature(layer.fields())
        feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(hist_entry["lon"], hist_entry["lat"])))
        n_vals = sum(len(v) for v in hist_entry["data"].values())
        feat.setAttributes(
            [
                hist_entry["id"],
                hist_entry["label"],
                hist_entry["lon"],
                hist_entry["lat"],
                hist_entry["collection"],
                ",".join(hist_entry["bands"]),
                hist_entry["start"],
                hist_entry["end"],
                n_vals,
            ]
        )
        layer.addFeature(feat)
        layer.commitChanges()
        self._apply_layer_style()
        self._move_temp_layer_to_top()

    def _remove_point_from_temp_layer(self, hist_id):
        layer = self._get_or_create_temp_layer()
        if not layer:
            return
        layer.startEditing()
        for feat in layer.getFeatures():
            if feat.attribute("id") == hist_id:
                layer.deleteFeature(feat.id())
                break
        layer.commitChanges()
        layer.triggerRepaint()

    def _on_layer_removed(self, layer_id):
        """Reset _temp_layer ref when the user manually deletes it."""
        if self._temp_layer is not None:
            try:
                if self._temp_layer.id() == layer_id:
                    self._temp_layer = None
            except RuntimeError:
                self._temp_layer = None

    def _on_layers_added(self, layers):
        """When any layer is added, move BDC TS Points back to top."""
        if self._temp_layer is not None:
            try:
                from qgis.PyQt import sip as _sip

                if not _sip.isdeleted(self._temp_layer):
                    if any(getattr(lyr, "id", lambda: None)() == self._temp_layer.id() for lyr in layers):
                        return
            except Exception:
                pass
        QTimer.singleShot(POINTS_LAYER_TO_TOP_MS, self._move_temp_layer_to_top)

    def _move_temp_layer_to_top(self):
        """Move BDC TS Points to the top of the layer tree."""
        if not self._temp_layer:
            return
        try:
            from qgis.PyQt import sip as _sip

            if _sip.isdeleted(self._temp_layer):
                self._temp_layer = None
                return
        except Exception:
            pass
        try:
            root = QgsProject.instance().layerTreeRoot()
            node = root.findLayer(self._temp_layer.id())
            if not node:
                return
            children = root.children()
            if children and children[0] is node:
                return
            taken = node.parent().takeChild(node)
            if taken is not None:
                root.insertChildNode(0, taken)
        except Exception:
            pass
