"""Tile filter dialog of the results: search, pages of tile checkboxes, Select All and Apply."""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..i18n import set_text
from ..widgets.cursors import apply_click_cursors

# Tile filter dialog styles.
_SEARCH_INPUT_STYLE = """
    QLineEdit {
        font-size: 11px;
        padding: 4px 8px;
        border: 1px solid #d0d7de;
        border-radius: 4px;
        background: white;
    }
    QLineEdit:focus {
        border-color: #1f6feb;
    }
"""


_ALL_BTN_STYLE = """
    QPushButton {
        background-color: #2da44e;
        color: white;
        font-size: 10px;
        font-weight: bold;
        padding: 4px 12px;
        border: none;
        border-radius: 4px;
    }
    QPushButton:hover {
        background-color: #2c974b;
    }
"""


_NONE_BTN_STYLE = """
    QPushButton {
        background-color: #6e7781
        border-radius: 4px;
    }
    QPushButton:hover {
        background-color: #57606a;
    }
"""


_SCROLL_STYLE = """
    QScrollArea {
        border: 1px solid #d0d7de;
        border-radius: 6px;
        background: white;
    }
"""


_PAGE_BTN_STYLE = """
    QPushButton {
        background-color: #f6f8fa;
        color: #24292f;
        font-size: 10px;
        font-weight: bold;
        padding: 4px 12px;
        border: 1px solid #d0d7de;
        border-radius: 4px;
    }
    QPushButton:hover {
        background-color: #eaeef2;
        border-color: #1f6feb;
    }
    QPushButton:disabled {
        color: #8c959f;
        background-color: #f6f8fa;
    }
"""


_CANCEL_BTN_STYLE = """
    QPushButton {
        background-color: #f6f8fa;
        color: #24292f;
        font-size: 11px;
        font-weight: bold;
        padding: 6px 16px;
        border: 1px solid #d0d7de;
        border-radius: 6px;
    }
    QPushButton:hover {
        background-color: #eaeef2;
    }
"""


_APPLY_BTN_STYLE = """
    QPushButton {
        background-color: #0969da;
        color: white;
        font-size: 11px;
        font-weight: bold;
        padding: 6px 16px;
        border: none;
        border-radius: 6px;
    }
    QPushButton:hover {
        background-color: #0860ca;
    }
"""


class TileFilterDialog(QDialog):
    """Tile selection dialog with pagination and search."""

    def __init__(self, tiles_dict, parent=None):
        super().__init__(parent)
        self.tiles_dict = tiles_dict  # {tile_id: {'display': str, 'checked': bool}}
        self.tiles_per_page = 10
        self.current_page = 0
        self._search_text = ""
        self._update_filtered_tiles()
        self.checkboxes = {}

        self.setWindowTitle("Select Tiles")
        self.setModal(True)
        self.setMinimumSize(450, 400)
        self.setup_ui()
        self._update_page()

    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # Header
        header = QHBoxLayout()
        title = QLabel("<b style='font-size: 13px;'>Select tiles to filter</b>")
        header.addWidget(title)
        header.addStretch()

        # Selection count
        self.counter_label = QLabel()
        self.counter_label.setStyleSheet("font-size: 11px; color: #57606a;")
        header.addWidget(self.counter_label)
        layout.addLayout(header)

        # Search input
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search tile by ID...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setFixedHeight(30)
        self.search_input.setStyleSheet(_SEARCH_INPUT_STYLE)
        self.search_input.textChanged.connect(self._on_search_changed)
        layout.addWidget(self.search_input)

        self._build_quick_actions(layout)
        self._build_checkbox_area(layout)
        self._build_pagination(layout)
        self._build_dialog_buttons(layout)
        self.setLayout(layout)

    def _build_quick_actions(self, layout):
        """Select All and Deselect All buttons."""
        actions = QHBoxLayout()
        actions.setSpacing(8)

        all_btn = QPushButton("Select All")
        all_btn.setFixedHeight(28)
        all_btn.setStyleSheet(_ALL_BTN_STYLE)
        all_btn.clicked.connect(self._check_all_current_page)
        actions.addWidget(all_btn)

        none_btn = QPushButton("Deselect All")
        none_btn.setFixedHeight(28)
        none_btn.setStyleSheet(_NONE_BTN_STYLE)
        none_btn.clicked.connect(self._uncheck_all_current_page)
        actions.addWidget(none_btn)

        actions.addStretch()
        layout.addLayout(actions)

    def _build_checkbox_area(self, layout):
        """Scrollable list of tile checkboxes for the current page."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(_SCROLL_STYLE)

        self.checkbox_container = QWidget()
        self.checkbox_layout = QVBoxLayout(self.checkbox_container)
        self.checkbox_layout.setSpacing(6)
        self.checkbox_layout.setContentsMargins(12, 12, 12, 12)
        self.checkbox_layout.addStretch()

        scroll.setWidget(self.checkbox_container)
        layout.addWidget(scroll, stretch=1)

    def _build_pagination(self, layout):
        """Previous and next page buttons, shown when the tiles fill more than one page."""
        if self.total_pages > 1:
            pagination = QHBoxLayout()
            pagination.setSpacing(8)

            self.prev_btn = QPushButton("◀ Prev")
            self.prev_btn.setFixedHeight(28)
            self.prev_btn.setStyleSheet(_PAGE_BTN_STYLE)
            self.prev_btn.clicked.connect(self._prev_page)
            pagination.addWidget(self.prev_btn)

            self.page_label = QLabel()
            self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.page_label.setStyleSheet("font-size: 11px; color: #24292f; font-weight: bold;")
            pagination.addWidget(self.page_label, stretch=1)

            self.next_btn = QPushButton("Next ▶")
            self.next_btn.setFixedHeight(28)
            self.next_btn.setStyleSheet(_PAGE_BTN_STYLE)
            self.next_btn.clicked.connect(self._next_page)
            pagination.addWidget(self.next_btn)

            layout.addLayout(pagination)

    def _build_dialog_buttons(self, layout):
        """Cancel and Apply buttons."""
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(32)
        cancel_btn.setFixedWidth(100)
        cancel_btn.setStyleSheet(_CANCEL_BTN_STYLE)
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)

        apply_btn = QPushButton("Apply")
        apply_btn.setFixedHeight(32)
        apply_btn.setFixedWidth(100)
        apply_btn.setStyleSheet(_APPLY_BTN_STYLE)
        apply_btn.clicked.connect(self.accept)
        buttons.addWidget(apply_btn)

        layout.addLayout(buttons)

    def _update_filtered_tiles(self):
        """Recalculate filtered tile list and total pages."""
        if self._search_text:
            self._filtered_tiles = sorted(
                t
                for t in self.tiles_dict.keys()
                if self._search_text in t.lower() or self._search_text in self.tiles_dict[t]["display"].lower()
            )
        else:
            self._filtered_tiles = sorted(self.tiles_dict.keys())
        self.total_pages = max(1, (len(self._filtered_tiles) + self.tiles_per_page - 1) // self.tiles_per_page)

    def _on_search_changed(self, text):
        """Filter the tiles as the user types."""
        self._save_page_state()
        self._search_text = text.strip().lower()
        self._update_filtered_tiles()
        self.current_page = 0
        self._update_page()

    def _update_page(self):
        """Update the current page display."""
        # Clear the previous checkboxes
        for cb in self.checkboxes.values():
            cb.hide()
            cb.deleteLater()
        self.checkboxes.clear()

        while self.checkbox_layout.count() > 1:
            item = self.checkbox_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().setParent(None)
                item.widget().deleteLater()

        # Calculate page range (using filtered list)
        start_idx = self.current_page * self.tiles_per_page
        end_idx = min(start_idx + self.tiles_per_page, len(self._filtered_tiles))
        page_tiles = self._filtered_tiles[start_idx:end_idx]

        # Create checkboxes for current page
        for tile_id in page_tiles:
            tile_data = self.tiles_dict[tile_id]
            cb = QCheckBox(tile_data["display"])
            cb.setChecked(tile_data["checked"])
            cb.setStyleSheet("QCheckBox { font-size: 11px; padding: 4px; }")
            self.checkboxes[tile_id] = cb
            self.checkbox_layout.insertWidget(self.checkbox_layout.count() - 1, cb)
            apply_click_cursors(cb)

        # Update controls
        self._update_controls()

    def _update_controls(self):
        """Update labels and buttons."""
        checked_count = sum(1 for t in self.tiles_dict.values() if t["checked"])
        total_count = len(self.tiles_dict)

        if self._search_text:
            filtered_count = len(self._filtered_tiles)
            set_text(self.counter_label, f"{checked_count}/{total_count} selected ({filtered_count} filtered)")
        else:
            set_text(self.counter_label, f"{checked_count}/{total_count} selected")

        if self.total_pages > 1:
            set_text(self.page_label, f"Page {self.current_page + 1} of {self.total_pages}")
            self.prev_btn.setEnabled(self.current_page > 0)
            self.next_btn.setEnabled(self.current_page < self.total_pages - 1)

    def _prev_page(self):
        """Go to previous page."""
        self._save_page_state()
        if self.current_page > 0:
            self.current_page -= 1
            self._update_page()

    def _next_page(self):
        """Go to next page."""
        self._save_page_state()
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self._update_page()

    def _save_page_state(self):
        """Save checkbox state for the current page."""
        for tile_id, cb in self.checkboxes.items():
            self.tiles_dict[tile_id]["checked"] = cb.isChecked()

    def _check_all_current_page(self):
        """Select all on the current page."""
        for cb in self.checkboxes.values():
            cb.setChecked(True)
        self._save_page_state()
        self._update_controls()

    def _uncheck_all_current_page(self):
        """Deselect all on the current page."""
        for cb in self.checkboxes.values():
            cb.setChecked(False)
        self._save_page_state()
        self._update_controls()

    def get_selected_tiles(self):
        """Return set of selected tiles."""
        self._save_page_state()
        return {tid for tid, data in self.tiles_dict.items() if data["checked"]}
