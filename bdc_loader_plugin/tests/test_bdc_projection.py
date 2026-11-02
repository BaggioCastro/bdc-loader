"""Unit tests for the BDC Projection button logic, _is_bdc_crs validation, and anti-duplication locks."""

import os
import sqlite3
import tempfile
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from qgis.core import QgsApplication, QgsCoordinateReferenceSystem, QgsProject
from qgis.PyQt.QtWidgets import QMessageBox

from bdc_loader_plugin.core.bdc_crs import _is_bdc_crs, _resolve_bdc_crs
from bdc_loader_plugin.ui.main_dialog import BDCLoaderDialog


def _make_dummy_dialog():
    dialog = MagicMock()
    dialog.iface = MagicMock()
    dialog._apply_bdc_projection = BDCLoaderDialog._apply_bdc_projection.__get__(dialog, BDCLoaderDialog)
    return dialog


_BDC_PROJ = (
    "+proj=aea +lat_0=-12 +lon_0=-54 +lat_1=-2 +lat_2=-22 +x_0=5000000 +y_0=10000000 +ellps=GRS80 +units=m +no_defs"
)


def test_resolve_bdc_crs_prefers_official_epsg():
    """EPSG:10857 must be selected without constructing the custom fallback."""
    official_crs = MagicMock()
    official_crs.isValid.return_value = True

    with patch("bdc_loader_plugin.core.bdc_crs.QgsCoordinateReferenceSystem") as crs_class:
        crs_class.return_value = official_crs
        resolved_crs, is_official_epsg = _resolve_bdc_crs()

    crs_class.assert_called_once_with("EPSG:10857")
    crs_class.fromProj.assert_not_called()
    assert resolved_crs is official_crs
    assert is_official_epsg is True


def test_resolve_bdc_crs_falls_back_for_older_epsg_database():
    """An unavailable EPSG:10857 must fall back to the equivalent PROJ definition."""
    unavailable_epsg = MagicMock()
    unavailable_epsg.isValid.return_value = False
    custom_crs = MagicMock()
    custom_crs.isValid.return_value = True

    with patch("bdc_loader_plugin.core.bdc_crs.QgsCoordinateReferenceSystem") as crs_class:
        crs_class.return_value = unavailable_epsg
        crs_class.fromProj.return_value = custom_crs
        resolved_crs, is_official_epsg = _resolve_bdc_crs()

    crs_class.assert_called_once_with("EPSG:10857")
    crs_class.fromProj.assert_called_once_with(_BDC_PROJ)
    assert resolved_crs is custom_crs
    assert is_official_epsg is False


def test_is_bdc_crs_validation():
    """Test strict parameter checking in _is_bdc_crs."""
    bdc_crs = QgsCoordinateReferenceSystem.fromProj(_BDC_PROJ)

    same_crs = QgsCoordinateReferenceSystem.fromProj(
        "+y_0=1e7 +x_0=5e6 +lat_2=-22.0 +lat_1=-2 +lon_0=-54 +lat_0=-12 +proj=aea +ellps=GRS80 +units=m"
    )
    assert _is_bdc_crs(same_crs, bdc_crs) is True

    replacements = {
        "lat_0=-12": "lat_0=-120",
        "lon_0=-54": "lon_0=-540",
        "lat_1=-2": "lat_1=-20",
        "lat_2=-22": "lat_2=-220",
        "x_0=5000000": "x_0=50000000",
        "y_0=10000000": "y_0=100000000",
    }
    for original, replacement in replacements.items():
        different_albers = QgsCoordinateReferenceSystem.fromProj(_BDC_PROJ.replace(original, replacement))
        assert _is_bdc_crs(different_albers, bdc_crs) is False, original

    invalid_crs = QgsCoordinateReferenceSystem()
    assert _is_bdc_crs(invalid_crs, bdc_crs) is False
    assert _is_bdc_crs(bdc_crs, invalid_crs) is False


def test_is_bdc_crs_empty_authid_handling():
    """Test that two custom CRSs with empty authids do not falsely match if definitions differ."""
    bdc_crs = QgsCoordinateReferenceSystem.fromProj(_BDC_PROJ)
    other_custom_crs = QgsCoordinateReferenceSystem.fromProj(
        "+proj=utm +zone=23 +south +ellps=WGS84 +datum=WGS84 +units=m +no_defs"
    )

    with (
        patch.object(bdc_crs, "authid", return_value=""),
        patch.object(other_custom_crs, "authid", return_value=""),
        patch.object(other_custom_crs, "__eq__", return_value=True),
    ):
        assert _is_bdc_crs(other_custom_crs, bdc_crs) is False


def test_qgis_mock_has_no_phantom_matching_method():
    """The mock must expose only APIs which exist on supported QGIS versions."""
    assert not hasattr(QgsCoordinateReferenceSystem, "findMatchingUserCrs")


def test_apply_bdc_projection_already_set():
    """An already-active BDC CRS must produce a clear dialog without another prompt."""
    dialog = _make_dummy_dialog()

    bdc_crs = QgsCoordinateReferenceSystem.fromProj(_BDC_PROJ)
    QgsProject.instance().setCrs(bdc_crs)

    with (
        patch.object(QMessageBox, "question") as mock_question,
        patch.object(QMessageBox, "information") as mock_information,
    ):
        dialog._apply_bdc_projection()

    mock_question.assert_not_called()
    mock_information.assert_called_once()
    assert "already using" in mock_information.call_args.args[2]
    assert "No projection was added" in mock_information.call_args.args[2]


def test_apply_bdc_projection_user_declines():
    """Test that if user declines the prompt, project CRS is not changed."""
    dialog = _make_dummy_dialog()

    QgsProject.instance().setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))

    with (
        patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No),
        patch.object(QMessageBox, "information") as mock_information,
    ):
        dialog._apply_bdc_projection()

    mock_information.assert_not_called()
    assert QgsProject.instance().crs().authid() == "EPSG:4326"


def test_apply_bdc_projection_uses_official_epsg_without_user_crs_lookup():
    """A recognized EPSG:10857 is applied directly without registry or SQLite work."""
    dialog = _make_dummy_dialog()
    official_crs = QgsCoordinateReferenceSystem("EPSG:10857")
    QgsProject.instance().setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))

    with (
        patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes),
        patch(
            "bdc_loader_plugin.ui.bdc_projection._resolve_bdc_crs",
            return_value=(official_crs, True),
        ),
        patch.object(QgsApplication, "coordinateReferenceSystemRegistry") as registry_lookup,
        patch.object(QgsApplication, "qgisUserDatabaseFilePath") as sqlite_lookup,
        patch.object(QgsCoordinateReferenceSystem, "saveAsUserCrs") as mock_save,
        patch.object(QMessageBox, "information") as mock_information,
    ):
        dialog._apply_bdc_projection()

    registry_lookup.assert_not_called()
    sqlite_lookup.assert_not_called()
    mock_save.assert_not_called()
    mock_information.assert_called_once()
    assert "EPSG:10857" in mock_information.call_args.args[2]
    assert "no custom CRS was created" in mock_information.call_args.args[2]
    assert QgsProject.instance().crs().authid() == "EPSG:10857"


def test_apply_bdc_projection_saves_crs_if_new():
    """Test that if CRS is new, saveAsUserCrs is called once and applied."""
    dialog = _make_dummy_dialog()
    custom_crs = QgsCoordinateReferenceSystem.fromProj(_BDC_PROJ)

    QgsProject.instance().setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))

    with (
        patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes),
        patch(
            "bdc_loader_plugin.ui.bdc_projection._resolve_bdc_crs",
            return_value=(custom_crs, False),
        ),
        patch.object(QgsCoordinateReferenceSystem, "saveAsUserCrs", return_value=100001) as mock_save,
        patch.object(QMessageBox, "information") as mock_information,
    ):
        dialog._apply_bdc_projection()

    mock_save.assert_called_once_with("BDC Albers Equal-Area Conic")
    assert QgsProject.instance().crs().authid() == "USER:100001"
    mock_information.assert_called_once()
    assert "added to the QGIS User CRS list" in mock_information.call_args.args[2]
    assert "EPSG:10857 is not available" in mock_information.call_args.args[2]


def test_apply_bdc_projection_reuses_registry_crs():
    """An exact userCrsList match is reused without creating another user CRS."""
    dialog = _make_dummy_dialog()
    QgsProject.instance().setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    existing_crs = QgsCoordinateReferenceSystem.fromProj(_BDC_PROJ)
    record = SimpleNamespace(id=100001, name="Existing BDC CRS", crs=existing_crs)
    registry = MagicMock()
    registry.userCrsList.return_value = [record]

    with (
        patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes),
        patch(
            "bdc_loader_plugin.ui.bdc_projection._resolve_bdc_crs",
            return_value=(existing_crs, False),
        ),
        patch.object(QgsApplication, "coordinateReferenceSystemRegistry", return_value=registry),
        patch.object(QgsCoordinateReferenceSystem, "saveAsUserCrs") as mock_save,
        patch.object(QMessageBox, "information") as mock_information,
    ):
        dialog._apply_bdc_projection()

    registry.userCrsList.assert_called_once_with()
    mock_save.assert_not_called()
    mock_information.assert_called_once()
    assert "already saved in QGIS" in mock_information.call_args.args[2]
    assert "No duplicate CRS was created" in mock_information.call_args.args[2]
    assert QgsProject.instance().crs() == existing_crs


def test_apply_bdc_projection_reuses_sqlite_fallback():
    """The SQLite fallback reads candidate IDs and reuses the exact matching CRS."""
    dialog = _make_dummy_dialog()
    QgsProject.instance().setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    custom_crs = QgsCoordinateReferenceSystem.fromProj(_BDC_PROJ)
    registry = MagicMock()
    registry.userCrsList.return_value = []

    with tempfile.TemporaryDirectory(prefix="bdc_crs_db_test_") as work:
        db_path = os.path.join(work, "qgis.db")
        with closing(sqlite3.connect(db_path)) as conn, conn:
            conn.execute("CREATE TABLE tbl_srs (srs_id INTEGER PRIMARY KEY)")
            conn.execute("INSERT INTO tbl_srs (srs_id) VALUES (100123)")

        real_is_bdc_crs = _is_bdc_crs

        def match_sqlite_candidate(candidate, target):
            if candidate.authid() == "USER:100123":
                return True
            return real_is_bdc_crs(candidate, target)

        with (
            patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes),
            patch(
                "bdc_loader_plugin.ui.bdc_projection._resolve_bdc_crs",
                return_value=(custom_crs, False),
            ),
            patch.object(QgsApplication, "coordinateReferenceSystemRegistry", return_value=registry),
            patch.object(QgsApplication, "qgisUserDatabaseFilePath", return_value=db_path),
            patch("bdc_loader_plugin.ui.bdc_projection._is_bdc_crs", side_effect=match_sqlite_candidate),
            patch.object(QgsCoordinateReferenceSystem, "saveAsUserCrs") as mock_save,
            patch.object(QMessageBox, "information") as mock_information,
        ):
            dialog._apply_bdc_projection()

    mock_save.assert_not_called()
    mock_information.assert_called_once()
    assert "already saved in QGIS" in mock_information.call_args.args[2]
    assert QgsProject.instance().crs().authid() == "USER:100123"


def test_apply_bdc_projection_stops_when_save_fails():
    """A non-positive save result must not claim success or change the project CRS."""
    dialog = _make_dummy_dialog()
    original_crs = QgsCoordinateReferenceSystem("EPSG:4326")
    QgsProject.instance().setCrs(original_crs)
    custom_crs = QgsCoordinateReferenceSystem.fromProj(_BDC_PROJ)
    registry = MagicMock()
    registry.userCrsList.return_value = []

    with (
        patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes),
        patch.object(QMessageBox, "warning") as mock_warning,
        patch(
            "bdc_loader_plugin.ui.bdc_projection._resolve_bdc_crs",
            return_value=(custom_crs, False),
        ),
        patch.object(QgsApplication, "coordinateReferenceSystemRegistry", return_value=registry),
        patch.object(QgsCoordinateReferenceSystem, "saveAsUserCrs", return_value=-1),
        patch.object(QMessageBox, "information") as mock_information,
    ):
        dialog._apply_bdc_projection()

    mock_warning.assert_called_once()
    mock_information.assert_not_called()
    dialog.iface.mapCanvas().refresh.assert_not_called()
    assert QgsProject.instance().crs() == original_crs


def test_user_database_lookup_closes_the_database():
    """The lookup closes qgis.db, which Windows keeps locked while a connection is open."""
    from bdc_loader_plugin.ui.bdc_projection import _user_db_bdc_crs

    closed = []

    class _Tracked(sqlite3.Connection):
        def close(self):
            closed.append(True)
            super().close()

    real_connect = sqlite3.connect
    with tempfile.TemporaryDirectory(prefix="bdc_crs_db_test_") as work:
        db_path = os.path.join(work, "qgis.db")
        with closing(real_connect(db_path)) as conn, conn:
            conn.execute("CREATE TABLE tbl_srs (srs_id INTEGER PRIMARY KEY)")
        with (
            patch.object(QgsApplication, "qgisUserDatabaseFilePath", return_value=db_path),
            patch(
                "bdc_loader_plugin.ui.bdc_projection.sqlite3.connect",
                side_effect=lambda path: real_connect(path, factory=_Tracked),
            ),
        ):
            assert _user_db_bdc_crs(None) is None
    assert closed == [True]
