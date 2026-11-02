# -*- coding: utf-8 -*-
"""About dialog for BDC Loader Plugin."""

import os

from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox, QFrame, QLabel, QTextBrowser, QVBoxLayout

from ..i18n import tr


def show_about_dialog(parent=None):
    """Shows the About dialog with project context and styled presentation."""
    metadata_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "metadata.txt")
    version = "unknown"
    try:
        with open(metadata_path, "r", encoding="utf-8") as metadata_file:
            for line in metadata_file:
                if line.startswith("version="):
                    version = line.split("=", 1)[1].strip()
                    break
    except OSError:
        pass

    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("About BDC Loader"))
    dlg.setMinimumSize(760, 620)
    dlg.resize(880, 680)
    dlg.setStyleSheet("""
        QDialog {
            background: #edf3f8;
        }
        QFrame#aboutHeader {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 #12344d, stop:1 #2e7dd1);
            border-radius: 14px;
        }
        QLabel#aboutTitle {
            color: white;
            font-size: 24px;
            font-weight: bold;
        }
        QLabel#aboutSubtitle {
            color: #d9ebfb;
            font-size: 11px;
        }
        QTextBrowser {
            background: white;
            border: 1px solid #d8e2ec;
            border-radius: 14px;
            padding: 10px;
            selection-background-color: #cfe3f8;
        }
        QDialogButtonBox QPushButton {
            min-width: 110px;
            padding: 8px 18px;
            border-radius: 8px;
            border: none;
            background: #1f6fbf;
            color: white;
            font-weight: bold;
        }
        QDialogButtonBox QPushButton:hover {
            background: #155796;
        }
    """)

    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(18, 18, 18, 18)
    layout.setSpacing(14)

    header = QFrame()
    header.setObjectName("aboutHeader")
    header_layout_about = QVBoxLayout(header)
    header_layout_about.setContentsMargins(22, 20, 22, 20)
    header_layout_about.setSpacing(4)

    title = QLabel("BDC Loader")
    title.setObjectName("aboutTitle")
    header_layout_about.addWidget(title)

    subtitle = QLabel(tr(f"QGIS plugin for temporal series workflows • Version {version}"))
    subtitle.setObjectName("aboutSubtitle")
    header_layout_about.addWidget(subtitle)
    layout.addWidget(header)

    text_browser = QTextBrowser()
    text_browser.setOpenExternalLinks(True)
    text_browser.setHtml(f"""
    <div style='font-family: Segoe UI, Arial, sans-serif; color:#203040; line-height:1.45; padding:8px 10px 16px 10px;'>
        <div style='margin-bottom:18px; padding:14px 16px; background:#f6fbff; border:1px solid #d7e8f6; border-radius:12px;'>
            <div style='font-size:18px; font-weight:700; color:#163a59; margin-bottom:6px;'>{tr("Developed by")}</div>
            <div style='font-size:13px;'>
                <b>{tr("Current Version:")}</b> <span style='color:#c76b00;'>{version}</span><br><br>
                <b>Baggio Luiz de Castro e Silva</b><br>
                {tr("INPE - National Institute for Space Research")}<br>
                {tr("Sao Jose dos Campos - SP, Brazil")}<br>
                <a href='mailto:baggio.silva@inpe.br'>baggio.silva@inpe.br</a>
            </div>
        </div>

        <div style='margin-bottom:18px;'>
            <div style='font-size:18px; font-weight:700; color:#1d5f96; margin-bottom:8px;'>{tr("About this plugin")}</div>
            <p style='font-size:13px; margin:0 0 10px 0;'>
                {tr("This plugin was built from needs and features identified by the author to support day-to-day time series analysis workflows inside QGIS. Its design follows a practical, user-oriented view focused on loading, exploring, navigating and extracting temporal data.")}
            </p>
            <p style='font-size:13px; margin:0 0 10px 0;'>
                {tr("BDC Loader is an independent plugin and <b>not an official Brazil Data Cube product</b>. It is aimed at frequent real-world use cases in temporal analysis.")}
            </p>
            <p style='font-size:13px; margin:0;'>
                {tr("The expectation is that it will also be useful to other users working with similar routines.")}
            </p>
        </div>

        <div style='margin-bottom:18px;'>
            <div style='font-size:18px; font-weight:700; color:#1d5f96; margin-bottom:8px;'>{tr("Key Features")}</div>
            <ul style='font-size:13px; margin-top:6px;'>
                <li>{tr("Integrated time series panel with temporal navigation inside QGIS.")}</li>
                <li>{tr("Dynamic search across Brazil Data Cube STAC collections.")}</li>
                <li>{tr("Remote and local VRT generation designed for daily analytical workflows.")}</li>
                <li>{tr("Loading of single bands or RGB compositions directly into the map.")}</li>
                <li>{tr("Point-based temporal value extraction focused on applied analysis.")}</li>
                <li>{tr("Shortcuts, filters and interface choices designed for productivity.")}</li>
            </ul>
        </div>

        <div style='margin-bottom:18px; padding:14px 16px; background:#fff8e8; border:1px solid #f0d9a7; border-radius:12px;'>
            <div style='font-size:16px; font-weight:700; color:#8a5a00; margin-bottom:6px;'>{tr("Important notice")}</div>
            <div style='font-size:13px;'>
                {tr("The plugin relies on services, catalogs and concepts associated with Brazil Data Cube, but its interface, workflow decisions and part of its functionality reflect an independent, user-driven implementation developed for research and applied use.")}
            </div>
        </div>

        <div style='margin-bottom:20px;'>
            <div style='font-size:18px; font-weight:700; color:#1d5f96; margin-bottom:8px;'>{tr("Useful Links")}</div>
            <ul style='font-size:13px; margin-top:6px;'>
                <li><a href='https://data.inpe.br/bdc/'>Brazil Data Cube - INPE</a></li>
                <li><a href='https://brazil-data-cube.github.io/products.html'>{tr("Collections Documentation")}</a></li>
            </ul>
        </div>

        <div style='text-align:right; font-size:34px; font-weight:700; letter-spacing:4px; color:#e4edf5;'>BDC VRT LOADER</div>
    </div>
    """)
    layout.addWidget(text_browser, 1)

    btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    btn_box.rejected.connect(dlg.reject)
    btn_box.accepted.connect(dlg.accept)
    layout.addWidget(btn_box)

    dlg.exec()
