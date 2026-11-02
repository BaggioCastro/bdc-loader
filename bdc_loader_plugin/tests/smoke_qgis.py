"""Smoke check of the plugin in a real QGIS, without a screen, for the CI desktop jobs.

Builds the main window with QGIS's mocked iface, switches the language with
the flags and back, runs the tutorial's first steps, and reads a local raster
through the plugin's GDAL options. Prints one line per check and exits with
status 1 when one fails (or 0). Run from the repository root:

    QT_QPA_PLATFORM=offscreen python bdc_loader_plugin/tests/smoke_qgis.py
"""

import os
import sys
import tempfile
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from qgis.core import Qgis, QgsApplication, QgsSettings  # noqa: E402

FAILED = []


def check(ok, what):
    print(("ok   " if ok else "FAIL ") + what, flush=True)
    if not ok:
        FAILED.append(what)


def main():
    app = QgsApplication([], True)
    app.initQgis()
    try:
        print(f"QGIS {Qgis.version()}, Python {sys.version.split()[0]}, {sys.platform}", flush=True)
        QgsSettings().setValue("bdc_loader/tour_seen", True)
        QgsSettings().setValue("bdc_loader/language", "en")

        from qgis.testing.mocked import get_iface

        from bdc_loader_plugin.i18n import language
        from bdc_loader_plugin.ui.main_dialog import BDCLoaderDialog

        dialog = BDCLoaderDialog(get_iface())
        dialog.show()
        app.processEvents()
        check(dialog.isVisible(), "the main window opens")
        check(dialog.collection_combo.count() > 0, "collections are listed (online or bundled)")

        from qgis.PyQt.QtCore import Qt
        from qgis.PyQt.QtWidgets import QAbstractButton, QAbstractSpinBox, QComboBox

        hand = Qt.CursorShape.PointingHandCursor
        wrong = [
            type(w).__name__
            for kind in (QAbstractButton, QComboBox, QAbstractSpinBox)
            for w in dialog.findChildren(kind)
            if w.isVisibleTo(dialog)
            and w.isEnabled()
            and not (w.testAttribute(Qt.WidgetAttribute.WA_SetCursor) and w.cursor().shape() == hand)
        ]
        check(not wrong, f"every enabled button, box and arrow shows the pointing hand ({len(wrong)} do not)")

        width = dialog.width()
        dialog.language_buttons["pt"].click()
        app.processEvents()
        check(
            language() == "pt" and dialog.search_btn.text() == "Buscar STAC",
            "the flag switches to Portuguese",
        )
        dialog.language_buttons["en"].click()
        app.processEvents()
        check(language() == "en" and dialog.search_btn.text() == "Search STAC", "the flag switches back to English")
        check(dialog.width() == width, "the window keeps its width across the switch")

        dialog.start_tour()
        app.processEvents()
        tour = dialog._tour.tour
        check(tour.running and tour.index == 0, "the tutorial starts")
        tour._callout.next_btn.click()
        app.processEvents()
        check(tour.index == 1, "Next goes to the second step")
        tour.stop(completed=False)
        check(not tour.running, "the tutorial closes")

        from osgeo import gdal

        from bdc_loader_plugin.core.gdal_env import plugin_gdal

        path = os.path.join(tempfile.mkdtemp(), "smoke.tif")
        ds = gdal.GetDriverByName("GTiff").Create(path, 8, 8, 1)
        ds.GetRasterBand(1).Fill(7)
        ds = None
        with plugin_gdal():
            opened = gdal.Open(path)
            value = int(opened.GetRasterBand(1).ReadAsArray()[0, 0])
            opened = None
        check(value == 7, f"GDAL {gdal.__version__} reads a local raster inside the plugin's options")

        dialog.close()
        dialog.deleteLater()
        app.processEvents()
    except Exception:
        traceback.print_exc()
        FAILED.append("exception")
    finally:
        app.exitQgis()
    print(f"{len(FAILED)} failed" if FAILED else "all checks passed", flush=True)
    return 1 if FAILED else 0


if __name__ == "__main__":
    # Python's own teardown after exitQgis() can crash in a standalone QGIS
    # script; the checks are done, so leave with their status.
    os._exit(main())
