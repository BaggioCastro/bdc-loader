"""Stylesheets of the main window's widgets."""

_DOCS_BUTTON_STYLE = """
    QPushButton {
        background-color: #2980b9;
        color: white;
        border: none;
        border-radius: 4px;
        font-size: 9px;
        font-weight: bold;
    }
    QPushButton:hover { background-color: #8e44ad; }
    QPushButton:pressed { background-color: #6c3483; }
"""


_BDC_PROJ_BUTTON_STYLE = """
    QPushButton {
        background-color: #2e7d32;
        color: white;
        border: none;
        border-radius: 4px;
        font-size: 9px;
        font-weight: bold;
    }
    QPushButton:hover { background-color: #43a047; }
    QPushButton:pressed { background-color: #1b5e20; }
"""


_CLOUD_SPIN_STYLE = """
    QSpinBox {
        font-size: 10px;
        padding: 2px 4px;
        border: 1px solid #d0d7de;
        border-radius: 3px;
        background: white;
    }
    QSpinBox:hover {
        border-color: #1f6feb;
    }
"""


_CLOUD_SLIDER_STYLE = """
    QSlider::groove:horizontal {
        height: 6px;
        background: #d0d7de;
        border-radius: 3px;
        margin: 0 2px;
    }
    QSlider::handle:horizontal {
        width: 16px;
        height: 16px;
        margin: -6px -1px;
        background: #1f6feb;
        border: 2px solid white;
        border-radius: 9px;
    }
    QSlider::handle:horizontal:hover {
        background: #0969da;
        border: 2px solid #e0e0e0;
    }
    QSlider::handle:horizontal:pressed {
        background: #0550ae;
    }
    QSlider::sub-page:horizontal {
        background: #1f6feb;
        border-radius: 3px;
    }
    QSlider::tick-mark {
        background: #aaa;
        width: 1px;
        height: 3px;
    }
"""


_TILE_FILTER_BUTTON_STYLE = """
    QPushButton {
        background-color: #0969da;
        color: white;
        font-size: 10px;
        font-weight: bold;
        padding: 4px 12px;
        border: none;
        border-radius: 4px;
    }
    QPushButton:hover {
        background-color: #0860ca;
    }
    QPushButton:pressed {
        background-color: #0757ba;
    }
"""


_RESET_BUTTON_STYLE = """
    QPushButton {
        background-color: white;
        color: #24292f;
        font-size: 10px;
        font-weight: bold;
        padding: 4px 12px;
        border: 1px solid #d0d7de;
        border-radius: 4px;
    }
    QPushButton:hover {
        background-color: #f3f4f6;
        border-color: #1f6feb;
    }
    QPushButton:pressed {
        background-color: #e5e7eb;
    }
"""


# Spatial filter groups grey out their title while another filter is in use.
_DISABLED_GROUP_STYLE = "QgsCollapsibleGroupBox:disabled { color: #8b949e; }"


_CONFIG_BTN_STYLE = """
    QPushButton {
        background-color: #57606a;
        color: white;
        border: none;
        border-radius: 4px;
        font-size: 12px;
        font-weight: bold;
    }
    QPushButton:hover { background-color: #484f58; }
    QPushButton:pressed { background-color: #3a3f44; }
"""


_ABOUT_BTN_STYLE = """
    QPushButton {
        background-color: #3498db;
        color: white;
        border: none;
        border-radius: 13px;
        font-weight: bold;
        font-size: 11px;
        padding: 0 12px;
    }
    QPushButton:hover { background-color: #217dbb; }
    QPushButton:pressed { background-color: #1b6699; }
"""


_COLL_FILTER_BTN_STYLE = """
    QPushButton {
        background-color: #3498db; color: white;
        border: none; border-radius: 4px;
        font-size: 14px; font-weight: bold;
    }
    QPushButton:hover { background-color: #2980b9; }
"""


_IMPORT_QUERY_BTN_BAR_STYLE = """
    QPushButton {
        background-color: #2980b9;
        color: white;
        font-weight: bold;
        padding: 10px;
        font-size: 13px;
        border: none;
        border-radius: 5px;
    }
    QPushButton:hover {
        background-color: #1f6693;
    }
"""


_EXPORT_QUERY_BTN_STYLE = """
    QPushButton {
        background-color: #34495e;
        color: white;
        font-weight: bold;
        padding: 10px;
        font-size: 13px;
        border: none;
        border-radius: 5px;
    }
    QPushButton:hover {
        background-color: #2c3e50;
    }
    QPushButton:pressed {
        background-color: #1a252f;
    }
"""


_SEARCH_BTN_STYLE = """
    QPushButton {
        background-color: #05C4B4;
        color: white;
        font-weight: bold;
        padding: 10px;
        font-size: 14px;
        border: none;
        border-radius: 5px;
    }
    QPushButton:hover {
        background-color: #04a89a;
    }
    QPushButton:pressed {
        background-color: #038c7f;
    }
"""


# Search STAC when the results on screen no longer match the panel: same size, amber.
_SEARCH_BTN_STALE_STYLE = (
    _SEARCH_BTN_STYLE.replace("#05C4B4", "#e67e22").replace("#04a89a", "#d35400").replace("#038c7f", "#ba4a00")
)


_STATUS_FRAME_STYLE = """
    QFrame#statusFrame {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #2c3e50, stop:1 #34495e);
        border-radius: 8px;
        border: 1px solid #1a252f;
    }
"""


_PROGRESS_BAR_STYLE = """
    QProgressBar {
        border: none;
        border-radius: 7px;
        background-color: rgba(255, 255, 255, 0.15);
        text-align: center;
        color: white;
        font-size: 9px;
        font-weight: bold;
    }
    QProgressBar::chunk {
        border-radius: 7px;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 #27ae60, stop:1 #2ecc71);
    }
"""


_STATUS_ICON_STYLE = """
    QLabel {
        color: #3498db;
        font-size: 14px;
        font-weight: bold;
        background: rgba(255, 255, 255, 0.1);
        border-radius: 10px;
    }
"""


_STATUS_LABEL_STYLE = """
    QLabel {
        color: #ecf0f1;
        font-size: 11px;
        padding: 2px;
    }
"""


_CANCEL_DOWNLOAD_BTN_STYLE = """
    QPushButton {
        background-color: #c0392b;
        color: white;
        font-size: 10px;
        font-weight: bold;
        padding: 4px 12px;
        border: none;
        border-radius: 4px;
    }
    QPushButton:hover {
        background-color: #e74c3c;
    }
    QPushButton:pressed {
        background-color: #a93226;
    }
    QPushButton:disabled {
        background-color: #7f8c8d;
    }
"""


_LOAD_BTN_STYLE = """
    QPushButton {
        background-color: #186DC2;
        color: white;
        font-weight: bold;
        padding: 10px;
        border: none;
        border-radius: 5px;
    }
    QPushButton:hover {
        background-color: #145ba3;
    }
    QPushButton:pressed {
        background-color: #104a85;
    }
"""


_CLEAR_BTN_STYLE = """
    QPushButton {
        background-color: white;
        color: black;
        font-weight: bold;
        padding: 10px;
        border: 2px solid black;
        border-radius: 5px;
    }
    QPushButton:hover {
        background-color: #f0f0f0;
    }
    QPushButton:pressed {
        background-color: #d0d0d0;
    }
"""


_DOWNLOAD_SELECTED_BTN_STYLE = """
    QPushButton {
        background-color: #2e7d32;
        color: white;
        font-weight: bold;
        padding: 10px;
        border: none;
        border-radius: 5px;
    }
    QPushButton:hover {
        background-color: #276b2b;
    }
    QPushButton:disabled {
        background-color: #a5c8a7;
    }
"""
