"""Small widget builders shared by the tabs of the settings dialog."""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
)


def _scrollable(page):
    """Hold a tab page in a scroll area, so a short window scrolls it instead
    of squeezing its controls (QTabWidget sizes itself without the extra
    height that wrapped text needs at the page's real width)."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(page)
    return scroll


_SPIN_STYLE = """
    QSpinBox { font-size: 11px; padding: 3px 6px; border: 1px solid #d0d7de; border-radius: 4px; }
    QSpinBox:focus { border-color: #1f6feb; }
"""


def _spin_row(grid, row, label, value_range, value, tooltip, hint):
    """Add a label, a spin box and a grey hint as one grid row; return the spin box."""
    label_widget = QLabel(label)
    label_widget.setStyleSheet("font-size: 11px;")
    grid.addWidget(label_widget, row, 0)
    spin = QSpinBox()
    spin.setRange(*value_range)
    spin.setValue(value)
    spin.setStyleSheet(_SPIN_STYLE)
    spin.setToolTip(tooltip)
    grid.addWidget(spin, row, 1)
    hint_widget = QLabel(hint)
    hint_widget.setStyleSheet("color: #57606a; font-size: 9px;")
    grid.addWidget(hint_widget, row, 2)
    return spin


def _delete_button(text, slot):
    """Red button that deletes files; `slot` runs on click."""
    button = QPushButton(text)
    button.setFixedHeight(28)
    button.setStyleSheet("""
        QPushButton { background-color: #d73a49; color: white; font-size: 10px;
            font-weight: bold; padding: 4px 14px; border: none; border-radius: 4px; }
        QPushButton:hover { background-color: #cb2431; }
    """)
    button.clicked.connect(slot)
    return button


def _add_toggle(layout, text, checked, info):
    """Add a bold checkbox and its grey explanation to `layout`; return the checkbox."""
    row = QHBoxLayout()
    check = QCheckBox(text)
    check.setChecked(checked)
    check.setStyleSheet("QCheckBox { font-size: 11px; font-weight: bold; }")
    row.addWidget(check)
    row.addStretch()
    layout.addLayout(row)

    info_label = QLabel(f"<span style='color: #57606a; font-size: 10px;'>{info}</span>")
    info_label.setWordWrap(True)
    layout.addWidget(info_label)
    return check


_SECONDARY_BUTTON_STYLE = """
    QPushButton {
        background-color: #f6f8fa; color: #24292f; font-size: 11px;
        font-weight: bold; padding: 6px 16px; border: 1px solid #d0d7de; border-radius: 6px;
    }
    QPushButton:hover { background-color: #eaeef2; }
"""


_SAVE_BUTTON_STYLE = """
    QPushButton {
        background-color: #2da44e; color: white; font-size: 11px;
        font-weight: bold; padding: 6px 16px; border: none; border-radius: 6px;
    }
    QPushButton:hover { background-color: #2c974b; }
"""


def _dialog_button(text, style, slot, width=None):
    """32 px tall dialog button; `width` fixes its width when given."""
    button = QPushButton(text)
    button.setFixedHeight(32)
    if width is not None:
        button.setFixedWidth(width)
    button.setStyleSheet(style)
    button.clicked.connect(slot)
    return button
