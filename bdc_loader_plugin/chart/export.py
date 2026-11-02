"""
Chart Export Utilities

Exports the time series history to CSV and GeoPackage.

Developed by Baggio Luiz de Castro e Silva
INPE - Sao Jose dos Campos, 2026
"""

import csv
import os

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtWidgets import QFileDialog, QMessageBox

from ..i18n import count_label, set_text


def history_feature_attributes(entry):
    """Attribute values of a history entry's point feature, in the layer's field order."""
    return [
        entry["id"],
        entry["label"],
        entry["lon"],
        entry["lat"],
        entry["collection"],
        ",".join(entry["bands"]),
        entry["start"],
        entry["end"],
        sum(len(v) for v in entry["data"].values()),
    ]


def _csv_safe(value) -> str:
    """Prefix formula-starting characters to prevent CSV formula injection."""
    s = str(value)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s


CSV_FIXED_COLUMNS = ["id", "longitude", "latitude", "start_date", "end_date", "label", "band"]


def csv_rows(history):
    """Header and rows of the wide CSV: one row per point and band, one column per date.

    The date columns are every date of every point and band, so a value is
    written under its own date and a band without a value on that date leaves
    the cell empty. Returns an empty list when the history holds no value.
    """
    series = [(entry, band, entry["data"].get(band, [])) for entry in history for band in entry["bands"]]
    series = [(entry, band, data) for entry, band, data in series if data]
    dates = sorted({dt.strftime("%Y-%m-%d") for _entry, _band, data in series for dt, _value in data})
    if not dates:
        return []
    rows = [CSV_FIXED_COLUMNS + dates]
    for entry, band, data in series:
        by_date = {dt.strftime("%Y-%m-%d"): value for dt, value in data}
        rows.append(
            [
                entry["id"],
                f"{entry['lon']:.6f}",
                f"{entry['lat']:.6f}",
                entry["start"],
                entry["end"],
                _csv_safe(entry["label"]),
                _csv_safe(band),
            ]
            + [f"{by_date[day]:.4f}" if day in by_date else "" for day in dates]
        )
    return rows


def export_csv(parent_widget, history, status_label):
    """
    Exports time series historical data to a CSV file.

    Args:
        parent_widget (QWidget): The parent widget for dialogs.
        history (list): The list of time series history dictionary entries.
        status_label (QLabel): The status label to update on success.
    """
    if not history:
        QMessageBox.warning(parent_widget, "Warning", "No data to export.")
        return

    path, _ = QFileDialog.getSaveFileName(
        parent_widget, "Export Time Series CSV", os.path.expanduser("~/bdc_timeseries.csv"), "CSV (*.csv)"
    )
    if not path:
        return

    try:
        rows = csv_rows(history)
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f, delimiter=",").writerows(rows)

        set_text(status_label, f"CSV file exported: {os.path.basename(path)}.")
        QMessageBox.information(parent_widget, "Exported", f"Saved in:\n{path}")
    except Exception as e:
        QMessageBox.warning(parent_widget, "Error", f"Error exporting CSV: {e}")


def export_timeseries_gpkg(parent_widget, history, status_label):
    """
    Exports the full time series data (point + band + date + value)
    to a GeoPackage file. Each observation becomes a feature.
    """
    if not history:
        QMessageBox.warning(parent_widget, "Warning", "No data to export.")
        return

    path, _ = QFileDialog.getSaveFileName(
        parent_widget,
        "Export Time Series as GeoPackage",
        os.path.expanduser("~/bdc_timeseries_full.gpkg"),
        "GeoPackage (*.gpkg)",
    )
    if not path:
        return

    try:
        fields = QgsFields()
        fields.append(QgsField("id", QVariant.Int))
        fields.append(QgsField("label", QVariant.String))
        fields.append(QgsField("longitude", QVariant.Double))
        fields.append(QgsField("latitude", QVariant.Double))
        fields.append(QgsField("collection", QVariant.String))
        fields.append(QgsField("band", QVariant.String))
        fields.append(QgsField("date", QVariant.String))
        fields.append(QgsField("value", QVariant.Double))
        crs = QgsCoordinateReferenceSystem("EPSG:4326")

        writer = QgsVectorFileWriter(path, "UTF-8", fields, QgsWkbTypes.Type.Point, crs, "GPKG")
        if writer.hasError() != QgsVectorFileWriter.WriterError.NoError:
            QMessageBox.warning(parent_widget, "Error", f"Error: {writer.errorMessage()}")
            return

        n_feat = 0
        for entry in history:
            pt = QgsGeometry.fromPointXY(QgsPointXY(entry["lon"], entry["lat"]))
            for band in entry.get("bands", []):
                band_data = entry.get("data", {}).get(band, [])
                for dt, val in sorted(band_data, key=lambda x: x[0]):
                    feat = QgsFeature()
                    feat.setGeometry(pt)
                    feat.setAttributes(
                        [
                            entry["id"],
                            entry["label"],
                            entry["lon"],
                            entry["lat"],
                            entry.get("collection", ""),
                            band,
                            dt.strftime("%Y-%m-%d"),
                            float(val),
                        ]
                    )
                    writer.addFeature(feat)
                    n_feat += 1

        del writer
        set_text(status_label, f"{count_label(n_feat, 'feature', 'features')} exported to GeoPackage.")

        reply = QMessageBox.question(
            parent_widget,
            "Add to Project",
            f"Exported {n_feat} features.\nAdd to QGIS project?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            layer = QgsVectorLayer(path, "BDC Time Series", "ogr")
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)

    except Exception as e:
        QMessageBox.warning(parent_widget, "Error", f"Error exporting GPKG: {e}")
