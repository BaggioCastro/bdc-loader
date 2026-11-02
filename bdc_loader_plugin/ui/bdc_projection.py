"""BDC Albers Equal-Area Conic (SIRGAS 2000 / Brazil Albers) as the project CRS."""

import logging
import os
import sqlite3
from contextlib import closing

from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsProject,
)
from qgis.PyQt.QtWidgets import (
    QMessageBox,
)

from ..core.bdc_crs import _is_bdc_crs, _resolve_bdc_crs

_BDC_PROJECTION_RESULTS = {
    "official": (
        "The project CRS is now SIRGAS 2000 / Brazil Albers (EPSG:10857).\n\n"
        "This official CRS was already available in QGIS, so no custom CRS was created."
    ),
    "created": (
        "The BDC Albers projection was added to the QGIS User CRS list and set as the project CRS.\n\n"
        "This compatible definition is used because EPSG:10857 is not available in this QGIS installation."
    ),
    "existing": (
        "A matching BDC Albers projection was already saved in QGIS and has been reused as the project CRS.\n\n"
        "No duplicate CRS was created."
    ),
}


def _confirm_bdc_projection(parent):
    """Ask whether to make BDC Albers the project CRS, listing its parameters."""
    reply = QMessageBox.question(
        parent,
        "BDC Projection",
        "Apply the BDC Albers Equal-Area Conic projection\n"
        "as the current QGIS project CRS?\n\n"
        "Projection: Albers Equal-Area Conic\n"
        "Datum: SIRGAS-2000 (GRS80)\n"
        "Origin: 12\u00b0S / 54\u00b0W\n"
        "Standard parallels: 2\u00b0S and 22\u00b0S",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    )
    return reply == QMessageBox.StandardButton.Yes


def _saved_bdc_crs(bdc_crs):
    """A BDC Albers CRS QGIS already knows, or None.

    Looks in the user CRS registry, then at the authority id of `bdc_crs`,
    then in the user database for CRSs saved by older QGIS versions.
    """
    crs = _registry_bdc_crs(bdc_crs)
    if crs is not None:
        return crs
    try:
        auth = str(bdc_crs.authid() or "")
    except (AttributeError, RuntimeError):
        auth = ""
    if auth and ":" in auth:
        return bdc_crs
    return _user_db_bdc_crs(bdc_crs)


def _registry_bdc_crs(bdc_crs):
    """A matching CRS from the QGIS user CRS registry, or None."""
    try:
        registry = QgsApplication.coordinateReferenceSystemRegistry()
        if not hasattr(registry, "userCrsList"):
            return None
        for record in registry.userCrsList():
            candidate = getattr(record, "crs", None)
            if not candidate or not candidate.isValid():
                srs_id = getattr(record, "id", None) or getattr(record, "srsid", None)
                if srs_id:
                    candidate = QgsCoordinateReferenceSystem(f"USER:{srs_id}")
            if candidate and _is_bdc_crs(candidate, bdc_crs):
                return candidate
    except Exception:
        logging.getLogger("bdc_loader").debug("CRS lookup in QGIS registry failed", exc_info=True)
    return None


def _user_db_bdc_crs(bdc_crs):
    """A matching CRS from the tbl_srs table of the QGIS user database, or None."""
    try:
        db_path = QgsApplication.qgisUserDatabaseFilePath()
        if os.path.isfile(db_path):
            with closing(sqlite3.connect(db_path)) as conn:
                for row in conn.execute("SELECT srs_id FROM tbl_srs ORDER BY srs_id ASC"):
                    candidate = QgsCoordinateReferenceSystem(f"USER:{row[0]}")
                    if _is_bdc_crs(candidate, bdc_crs):
                        return candidate
    except Exception:
        logging.getLogger("bdc_loader").debug("CRS lookup in spatialite failed", exc_info=True)
    return None


def _save_bdc_user_crs(parent, bdc_crs):
    """Save `bdc_crs` as a user CRS and return it; warn and return None when saving fails."""
    try:
        res = bdc_crs.saveAsUserCrs("BDC Albers Equal-Area Conic")
    except Exception:
        logging.getLogger("bdc_loader").debug("Failed to save BDC user CRS", exc_info=True)
        res = None
    if not isinstance(res, int) or isinstance(res, bool) or res <= 0:
        QMessageBox.warning(parent, "BDC Projection", "Failed to save the BDC CRS in the QGIS user database.")
        return None
    user_crs = QgsCoordinateReferenceSystem(f"USER:{res}")
    return user_crs if user_crs.isValid() else bdc_crs


def apply_bdc_projection(parent, iface):
    """Set the QGIS project CRS to BDC Albers Equal-Area Conic.

    Includes anti-duplication checks:
    1. If the project already uses BDC Albers CRS, notifies and returns immediately.
    2. Uses EPSG:10857 directly when the installed EPSG database provides it.
    3. On older databases, reuses a matching user CRS or saves the compatible fallback.
    """
    bdc_crs, is_official_epsg = _resolve_bdc_crs()
    if not bdc_crs or not bdc_crs.isValid():
        QMessageBox.warning(parent, "BDC Projection", "Failed to create BDC CRS.")
        return

    current_proj_crs = QgsProject.instance().crs()
    if current_proj_crs and current_proj_crs.isValid() and _is_bdc_crs(current_proj_crs, bdc_crs):
        if iface:
            iface.mainWindow().statusBar().showMessage(
                "\u2713 Project is already set to BDC Albers Equal-Area Conic (SIRGAS-2000)", 5000
            )
        QMessageBox.information(
            parent,
            "BDC Projection Already Active",
            "The current project is already using SIRGAS 2000 / Brazil Albers.\n\n"
            "No projection was added and no project setting was changed.",
        )
        return
    if not _confirm_bdc_projection(parent):
        return

    if is_official_epsg:
        crs, result_state = bdc_crs, "official"
    else:
        crs, result_state = _saved_bdc_crs(bdc_crs), "existing"
        if crs is None:
            crs, result_state = _save_bdc_user_crs(parent, bdc_crs), "created"
            if crs is None:
                return

    QgsProject.instance().setCrs(crs)
    if iface:
        iface.mapCanvas().refresh()
        iface.mainWindow().statusBar().showMessage(
            "\u2713 Project CRS set to BDC Albers Equal-Area Conic (SIRGAS-2000)", 5000
        )
    QMessageBox.information(parent, "BDC Projection Ready", _BDC_PROJECTION_RESULTS[result_state])
