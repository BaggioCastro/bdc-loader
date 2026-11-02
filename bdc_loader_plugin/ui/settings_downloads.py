"""Downloaded Images tab of the settings dialog: the downloaded files with their size and a delete action."""

import os
import shutil
from datetime import datetime

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..i18n import set_text, tr
from .result_widgets import _format_size
from .settings_widgets import (
    _scrollable,
)


class DownloadsTab:
    """Downloaded Images tab of the settings dialog: the downloaded files with their size and a delete action."""

    def _build_downloads_tab(self, tabs):
        """Downloaded Images tab: the list of downloaded files."""
        downloads_tab = QWidget()
        downloads_layout = QVBoxLayout(downloads_tab)
        downloads_layout.setSpacing(8)
        downloads_layout.setContentsMargins(8, 12, 8, 8)

        dl_header = QHBoxLayout()
        dl_header.addWidget(QLabel("<b>Locally downloaded images:</b>"))
        dl_header.addStretch()

        delete_btn = QPushButton("Delete Selected")
        delete_btn.setFixedHeight(26)
        delete_btn.setStyleSheet("""
            QPushButton {
                background-color: #d73a49; color: white; font-size: 10px;
                font-weight: bold; padding: 4px 12px; border: none; border-radius: 4px;
            }
            QPushButton:hover { background-color: #cb2431; }
        """)
        delete_btn.clicked.connect(self._delete_selected_downloads)
        dl_header.addWidget(delete_btn)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setFixedHeight(26)
        refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #0969da; color: white; font-size: 10px;
                font-weight: bold; padding: 4px 12px; border: none; border-radius: 4px;
            }
            QPushButton:hover { background-color: #0860ca; }
        """)
        refresh_btn.clicked.connect(self._refresh_downloads_list)
        dl_header.addWidget(refresh_btn)
        downloads_layout.addLayout(dl_header)

        self.downloads_tree = QTreeWidget()
        self.downloads_tree.setHeaderLabels([tr(t) for t in ("Collection / Item / Band", "Size", "Date")])
        self.downloads_tree.header().setStretchLastSection(False)
        self.downloads_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.downloads_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.downloads_tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.downloads_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.downloads_tree.setStyleSheet("""
            QTreeWidget { font-size: 10px; border: 1px solid #d0d7de; border-radius: 4px; }
            QTreeWidget::item { padding: 2px 4px; }
            QTreeWidget::item:hover { background-color: #f6f8fa; }
            QTreeWidget::item:selected { background-color: #ddf4ff; color: #000; }
        """)
        self.downloads_tree.setAlternatingRowColors(True)
        self.downloads_tree.setExpandsOnDoubleClick(False)
        downloads_layout.addWidget(self.downloads_tree, stretch=1)

        self.downloads_summary = QLabel("")
        self.downloads_summary.setStyleSheet("font-size: 10px; color: #57606a;")
        downloads_layout.addWidget(self.downloads_summary)

        tabs.addTab(_scrollable(downloads_tab), "Downloaded Images")

    def _refresh_downloads_list(self):
        self.downloads_tree.setUpdatesEnabled(False)
        self.downloads_tree.clear()
        dl_dir = self.download_dir_input.text()

        if not os.path.isdir(dl_dir):
            self.downloads_tree.setUpdatesEnabled(True)
            set_text(self.downloads_summary, "Downloads folder does not exist.")
            return

        downloads_path = os.path.join(dl_dir, "downloads")
        if not os.path.isdir(downloads_path):
            self.downloads_tree.setUpdatesEnabled(True)
            set_text(self.downloads_summary, "No images downloaded yet.")
            return

        total_files = 0
        total_size = 0

        for collection in sorted(os.listdir(downloads_path)):
            coll_path = os.path.join(downloads_path, collection)
            if not os.path.isdir(coll_path):
                continue

            coll_item = QTreeWidgetItem(self.downloads_tree)
            coll_item.setText(0, collection)
            coll_item.setData(0, Qt.ItemDataRole.UserRole, coll_path)
            coll_item.setExpanded(False)
            coll_files = 0
            coll_size = 0

            for item_name in sorted(os.listdir(coll_path)):
                item_path = os.path.join(coll_path, item_name)
                if not os.path.isdir(item_path):
                    continue

                item_node = QTreeWidgetItem(coll_item)
                item_node.setText(0, item_name)
                item_node.setData(0, Qt.ItemDataRole.UserRole, item_path)
                item_files = 0
                item_size = 0

                for fname in sorted(os.listdir(item_path)):
                    fpath = os.path.join(item_path, fname)
                    if not os.path.isfile(fpath):
                        continue
                    fsize = os.path.getsize(fpath)
                    fdate = datetime.fromtimestamp(os.path.getmtime(fpath)).strftime("%d/%m/%Y %H:%M")

                    band_node = QTreeWidgetItem(item_node)
                    band_node.setText(0, fname)
                    band_node.setText(1, _format_size(fsize))
                    band_node.setText(2, fdate)
                    band_node.setData(0, Qt.ItemDataRole.UserRole, fpath)

                    item_files += 1
                    item_size += fsize

                item_node.setText(1, _format_size(item_size))
                item_node.setText(2, f"{item_files} file(s)")
                coll_files += item_files
                coll_size += item_size

            coll_item.setText(1, _format_size(coll_size))
            coll_item.setText(2, f"{coll_files} file(s)")
            total_files += coll_files
            total_size += coll_size

        if total_files > 0:
            set_text(self.downloads_summary, f"Total: {total_files} file(s), {_format_size(total_size)}")
        else:
            set_text(self.downloads_summary, "No images downloaded yet.")

        self.downloads_tree.setUpdatesEnabled(True)

    def _delete_selected_downloads(self):
        selected = self.downloads_tree.selectedItems()
        if not selected:
            QMessageBox.information(self, "Info", "Select an item to delete.")
            return

        item = selected[0]
        path = item.data(0, Qt.ItemDataRole.UserRole)

        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "Error", "Path not found.")
            return

        if os.path.isfile(path):
            item_type = "file"
            item_name = os.path.basename(path)
        else:
            item_type = "folder"
            item_name = os.path.basename(path)

        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Delete {item_type}: {item_name}?\n\nThis action cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            if os.path.isfile(path):
                os.remove(path)
            else:
                shutil.rmtree(path)

            set_text(self.downloads_summary, f"{item_type.capitalize()} deleted: {item_name}")
            self._refresh_downloads_list()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error deleting: {e}")
