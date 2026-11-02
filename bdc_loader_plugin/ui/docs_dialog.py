# -*- coding: utf-8 -*-
"""Documentation dialog for BDC Loader Plugin."""

from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox, QFrame, QLabel, QTextBrowser, QVBoxLayout

from ..i18n import tr

INPE_DATA_URL = "https://data.inpe.br/dados/"
BDC_DATA_CUBES_URL = "https://data.inpe.br/dados/cubos-de-dados/"
BDC_EXPLORER_URL = "https://data.inpe.br/bdc/explorer/explore"


def show_docs_dialog(parent=None):
    """Shows a styled documentation dialog with BDC links and descriptions."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("BDC Documentation"))
    dlg.setMinimumSize(680, 560)
    dlg.resize(780, 620)
    dlg.setStyleSheet("""
        QDialog { background: #f4f7fb; }
        QFrame#docsHeader {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 #0d3b66, stop:1 #1976d2);
            border-radius: 12px;
        }
        QLabel#docsTitle { color: white; font-size: 22px; font-weight: bold; }
        QLabel#docsSubtitle { color: #b8d8f8; font-size: 11px; }
        QTextBrowser {
            background: white; border: 1px solid #d8e2ec;
            border-radius: 12px; padding: 8px;
            selection-background-color: #cfe3f8;
        }
        QDialogButtonBox QPushButton {
            min-width: 100px; padding: 7px 16px; border-radius: 7px;
            border: none; background: #1565c0; color: white; font-weight: bold;
        }
        QDialogButtonBox QPushButton:hover { background: #0d47a1; }
    """)

    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(12)

    # Header
    header = QFrame()
    header.setObjectName("docsHeader")
    hlayout = QVBoxLayout(header)
    hlayout.setContentsMargins(20, 16, 20, 16)
    hlayout.setSpacing(2)
    title = QLabel(tr("Explore BDC & INPE Data"))
    title.setObjectName("docsTitle")
    hlayout.addWidget(title)
    subtitle = QLabel(tr("Start with the official data portals, then use the optional technical references"))
    subtitle.setObjectName("docsSubtitle")
    hlayout.addWidget(subtitle)
    layout.addWidget(header)

    # Content
    browser = QTextBrowser()
    browser.setOpenExternalLinks(True)
    browser.setHtml(_build_html())
    layout.addWidget(browser, 1)

    btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    btn_box.rejected.connect(dlg.reject)
    layout.addWidget(btn_box)

    dlg.exec()


def _row(url, title, desc, featured=False):
    title, desc = tr(title), tr(desc)
    row_style = "background:#f7f0fb;" if featured else ""
    title_color = "#7d3c98" if featured else "#1565c0"
    return (
        f"<tr style='{row_style}'>"
        f"<td style='padding:6px 10px; vertical-align:top;'>"
        f"<a href='{url}' style='color:{title_color}; text-decoration:none; font-weight:700;'>{title}</a>"
        f"</td>"
        f"<td style='padding:6px 10px; font-size:12px; color:#3d4f5f;'>{desc}</td>"
        f"</tr>"
    )


def _section(title, color="#1565c0"):
    title = tr(title)
    return (
        f"<tr><td colspan='2' style='padding:14px 10px 6px 10px;'>"
        f"<div style='font-size:16px; font-weight:700; color:{color}; "
        f"border-bottom:2px solid {color}; padding-bottom:4px;'>{title}</div>"
        f"</td></tr>"
    )


_FOOTER = (
    "All links open in your default web browser. Start with the official INPE data portals; "
    "the remaining links provide direct access or optional technical detail."
)


def _build_html():
    base = "https://brazil-data-cube.github.io"
    spec = f"{base}/specifications"

    rows = [
        # ── Primary official portals ──
        _section("Start Here — Official INPE Data", "#7d3c98"),
        _row(
            INPE_DATA_URL,
            "Explore INPE Geospatial Data",
            "Main catalog for satellite imagery and other INPE collections, including CBERS, AMAZONIA-1, "
            "Sentinel, Landsat, meteorological, topographic, and water-related datasets.",
            featured=True,
        ),
        _row(
            BDC_DATA_CUBES_URL,
            "Brazil Data Cube Products",
            "Primary reference for available data cubes, spatial and temporal resolution, coverage periods, "
            "BDC grids, EPSG:10857, composition bands, product descriptions, and access links.",
            featured=True,
        ),
        # ── Direct access ──
        _section("Explore &amp; Access BDC Collections", "#c56200"),
        _row(
            "https://data.inpe.br/stac/browser/",
            "STAC Browser",
            "Explore BDC collections, dates, items, metadata, and downloadable assets in a web interface.",
        ),
        _row(
            BDC_EXPLORER_URL,
            "BDC Explorer",
            "Interactive map for visualizing satellite imagery, mosaics, data cubes, time series, and "
            "land-use trajectories.",
        ),
        _row(
            "https://data.inpe.br/bdc/stac/v1/",
            "STAC API Endpoint",
            "REST catalog used by this plugin for collection discovery, searches, metadata, and COG assets.",
        ),
        # ── Optional specifications ──
        _section("Optional Technical References", "#607d8b"),
        _row(
            f"{spec}/input-data.html",
            "Input Data",
            "Source satellite imagery used by BDC: Sentinel-2, Landsat-8, CBERS-4/4A, AMAZONIA-1, and MODIS.",
        ),
        _row(
            f"{spec}/concepts.html",
            "Concepts",
            "Core definitions — Cube Collection, Tile, Band, GRS, Compositing Function, and the 4D data model.",
        ),
        _row(
            f"{spec}/bdc-projection.html",
            "Projection",
            "Albers Equal-Area Conic projection with SIRGAS-2000 datum, centered at 12°S / 54°W.",
        ),
        _row(
            f"{spec}/bdc-grid.html",
            "Grids",
            "Hierarchical tiling system — Small (105 km), Medium (211 km), and Large (4224 km) grid levels.",
        ),
        _row(
            f"{spec}/processing-flow.html",
            "Processing Flow",
            "Pipeline from raw imagery to analysis-ready data cubes, including atmospheric correction and compositing.",
        ),
        _row(
            f"{spec}/naming.html",
            "Naming Convention",
            "How collections and files are named, e.g. <code>S2-16D_V2_008013_20220101_B01.tif</code>.",
        ),
        _row(
            f"{spec}/product-access.html",
            "Legacy Product Access Guide",
            "Additional BDC project instructions for STAC Browser, STAC API, and BDC Explorer.",
        ),
        # ── Optional services and learning ──
        _section("Optional API Guides &amp; Notebooks", "#2e7d32"),
        _row(
            f"{base}/applications/stac.html",
            "STAC Service Guide",
            "Technical documentation for discovering and accessing BDC image collections and data cubes via STAC.",
        ),
        _row(
            f"{base}/applications/stac/general.html",
            "STAC Python Client",
            "Python client library (<code>pystac-client</code>) used internally by this plugin for STAC queries.",
        ),
        _row(
            f"{base}/applications/wtss.html",
            "WTSS — Web Time Series Service",
            "Lightweight service for extracting time series at a given point and time interval. "
            "Used by this plugin for fast single-point temporal extraction.",
        ),
        _row(
            f"{base}/applications/wtss/retrieving_ts.html",
            "Retrieving Time Series (WTSS)",
            "Step-by-step guide on how to query WTSS to retrieve spectral values over time.",
        ),
        _row(
            f"{base}/applications/stac/jupyter.html",
            "STAC Jupyter Notebooks",
            "Interactive examples demonstrating STAC catalog queries using Python.",
        ),
        _row(
            f"{base}/applications/wtss/jupyter.html",
            "WTSS Jupyter Notebooks",
            "Interactive examples showing time series extraction via WTSS.",
        ),
    ]

    return (
        "<div style='font-family: Segoe UI, Arial, sans-serif; line-height:1.4;'>"
        "<table cellspacing='0' cellpadding='0' style='width:100%;'>" + "\n".join(rows) + "</table>"
        "<div style='margin-top:16px; padding:10px 12px; background:#f0f4fa; "
        "border:1px solid #d0dbe8; border-radius:8px; font-size:11px; color:#57606a;'>" + tr(_FOOTER) + "</div>"
        "</div>"
    )
