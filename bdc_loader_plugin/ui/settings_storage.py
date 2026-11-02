"""Storage tab of the settings dialog: disk use per file type with warning thresholds, cleanup by type, and a filtered file list to delete from."""

import os
import shutil

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..i18n import TRANSLATE_ITEMS, english_text, set_text, tr
from ..paths import temp_files
from .result_widgets import _format_size
from .settings_widgets import (
    _delete_button,
    _scrollable,
)


class StorageTab:
    """Storage tab of the settings dialog: disk use per file type with warning thresholds, cleanup by type, and a filtered file list to delete from."""

    def _build_storage_tab(self, tabs):
        """Storage tab: disk use per folder, thresholds and selective cleanup."""
        storage_tab = QWidget()
        storage_layout = QVBoxLayout(storage_tab)
        storage_layout.setSpacing(10)
        storage_layout.setContentsMargins(8, 12, 8, 8)

        storage_header = QLabel(
            "<span style='color: #57606a; font-size: 10px;'>"
            "Disk usage by file type. Adjust warning thresholds (MB) and clean as needed.</span>"
        )
        storage_header.setWordWrap(True)
        storage_layout.addWidget(storage_header)

        storage_layout.addLayout(self._build_storage_grid())

        self._storage_total_label = QLabel("")
        self._storage_total_label.setStyleSheet("font-size: 12px; font-weight: bold; margin-top: 4px;")
        storage_layout.addWidget(self._storage_total_label)

        storage_layout.addWidget(self._build_cleanup_group())
        storage_layout.addLayout(self._build_cleanup_actions())

        storage_layout.addStretch()
        tabs.addTab(_scrollable(storage_tab), "Storage")

    def _build_storage_grid(self):
        """One row per file type: label | size | bar | threshold spin | clean button."""
        storage_grid = QGridLayout()
        storage_grid.setSpacing(6)
        lbl_style = "font-size: 11px; font-weight: bold;"
        size_style = "font-size: 11px; color: #57606a;"
        spin_style = """
            QSpinBox { font-size: 10px; padding: 2px 4px; border: 1px solid #d0d7de; border-radius: 4px; }
        """
        clean_btn_style = """
            QPushButton {
                background-color: #d73a49; color: white; font-size: 10px;
                font-weight: bold; padding: 4px 10px; border: none; border-radius: 4px;
            }
            QPushButton:hover { background-color: #cb2431; }
            QPushButton:disabled { background-color: #d0d7de; color: #8b949e; }
        """

        # Column headers
        for col, text in [(0, "Type"), (1, "Used"), (2, ""), (3, "Warn (MB)"), (4, "")]:
            h = QLabel(f"<b style='font-size: 9px; color: #57606a;'>{text}</b>")
            storage_grid.addWidget(h, 0, col)

        self._storage_rows = {}  # key -> (size_label, bar, threshold_spin, clean_btn)

        row_defs = [
            ("vrt", "VRT Files", self._threshold_vrt_mb),
            ("ovr", "Overviews", self._threshold_ovr_mb),
            ("downloads", "Downloads", self._threshold_dl_mb),
            ("temp", "Temp Files", self._threshold_tmp_mb),
        ]
        for idx, (key, label, threshold_mb) in enumerate(row_defs, start=1):
            lbl = QLabel(label)
            lbl.setStyleSheet(lbl_style)
            storage_grid.addWidget(lbl, idx, 0)

            size_lbl = QLabel("—")
            size_lbl.setStyleSheet(size_style)
            size_lbl.setMinimumWidth(100)
            storage_grid.addWidget(size_lbl, idx, 1)

            bar = QProgressBar()
            bar.setFixedHeight(14)
            bar.setTextVisible(False)
            storage_grid.addWidget(bar, idx, 2)

            spin = QSpinBox()
            spin.setRange(50, 50000)
            spin.setSuffix(" MB")
            spin.setValue(threshold_mb)
            spin.setFixedWidth(100)
            spin.setStyleSheet(spin_style)
            spin.setToolTip(f"Warning threshold for {label}")
            storage_grid.addWidget(spin, idx, 3)

            btn = QPushButton("Clean")
            btn.setStyleSheet(clean_btn_style)
            btn.setFixedWidth(65)
            storage_grid.addWidget(btn, idx, 4)

            self._storage_rows[key] = (size_lbl, bar, spin, btn)

        # Connect clean buttons
        self._storage_rows["vrt"][3].clicked.connect(self._clean_vrt_files)
        self._storage_rows["ovr"][3].clicked.connect(self._clean_ovr_files)
        self._storage_rows["downloads"][3].clicked.connect(self._clean_downloads_folder)
        self._storage_rows["temp"][3].clicked.connect(self._clean_temp_files)

        # Real-time progress bar update when threshold changes
        for key in self._storage_rows:
            self._storage_rows[key][2].valueChanged.connect(self._refresh_storage_info)

        return storage_grid

    def _build_cleanup_group(self):
        """Selective cleanup: regex and type filter, Search button and the file tree."""
        cleanup_group = QGroupBox("Selective Cleanup")
        cleanup_group.setStyleSheet("QGroupBox { font-weight: bold; font-size: 11px; }")
        cleanup_gl = QVBoxLayout(cleanup_group)
        cleanup_gl.setContentsMargins(8, 8, 8, 8)
        cleanup_gl.setSpacing(6)

        # Filter row
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filter:"))
        self._clean_filter_input = QLineEdit()
        self._clean_filter_input.setPlaceholderText("Regex pattern (e.g. CBERS.* or \\.ovr$)")
        self._clean_filter_input.setStyleSheet("""
            QLineEdit { font-size: 10px; padding: 3px 6px; border: 1px solid #d0d7de; border-radius: 4px; }
        """)
        filter_row.addWidget(self._clean_filter_input, stretch=1)

        self._clean_type_combo = QComboBox()
        self._clean_type_combo.addItems(["All types", ".vrt only", ".ovr only", ".tif only", "Other"])
        self._clean_type_combo.setProperty(TRANSLATE_ITEMS, True)
        self._clean_type_combo.setStyleSheet("QComboBox { font-size: 10px; padding: 2px 6px; }")
        self._clean_type_combo.setFixedWidth(100)
        filter_row.addWidget(self._clean_type_combo)

        apply_filter_btn = QPushButton("Search")
        apply_filter_btn.setFixedHeight(24)
        apply_filter_btn.setStyleSheet("""
            QPushButton { background-color: #0969da; color: white; font-size: 10px;
                font-weight: bold; padding: 3px 10px; border: none; border-radius: 4px; }
            QPushButton:hover { background-color: #0860ca; }
        """)
        apply_filter_btn.clicked.connect(self._apply_clean_filter)
        filter_row.addWidget(apply_filter_btn)
        cleanup_gl.addLayout(filter_row)

        # File tree
        self._clean_tree = QTreeWidget()
        self._clean_tree.setHeaderLabels([tr(t) for t in ("File", "Size", "Folder")])
        self._clean_tree.header().setStretchLastSection(False)
        self._clean_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._clean_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._clean_tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._clean_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._clean_tree.setAlternatingRowColors(True)
        self._clean_tree.setStyleSheet("""
            QTreeWidget { font-size: 10px; border: 1px solid #d0d7de; border-radius: 4px; }
            QTreeWidget::item { padding: 2px 4px; }
            QTreeWidget::item:selected { background-color: #ddf4ff; color: #000; }
        """)
        self._clean_tree.setFixedHeight(150)
        cleanup_gl.addWidget(self._clean_tree)

        return cleanup_group

    def _build_cleanup_actions(self):
        """Count of filtered files and the Delete Selected and Delete All Filtered buttons."""
        bottom_row = QHBoxLayout()
        self._clean_count_label = QLabel("")
        self._clean_count_label.setStyleSheet("font-size: 10px; color: #57606a;")
        bottom_row.addWidget(self._clean_count_label)
        bottom_row.addStretch()
        bottom_row.addWidget(_delete_button("Delete Selected", self._delete_selected_files))
        bottom_row.addWidget(_delete_button("Delete All Filtered", self._delete_all_filtered))
        return bottom_row

    @staticmethod
    def _folder_size(path):
        """Return (total_bytes, file_count) for a directory tree."""
        total = 0
        count = 0
        if not os.path.isdir(path):
            return 0, 0
        for dirpath, _dirnames, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    total += os.path.getsize(fp)
                    count += 1
                except OSError:
                    pass
        return total, count

    @staticmethod
    def _temp_bdc_paths():
        """Return list of existing BDC temp paths (files and dirs)."""
        return temp_files()

    def _temp_bdc_size(self):
        """Return (total_bytes, file_count) across all BDC temp paths."""
        total = 0
        count = 0
        for p in self._temp_bdc_paths():
            if os.path.isfile(p):
                try:
                    total += os.path.getsize(p)
                    count += 1
                except OSError:
                    pass
            elif os.path.isdir(p):
                s, c = self._folder_size(p)
                total += s
                count += c
        return total, count

    @staticmethod
    def _size_by_extensions(path, extensions):
        """Return (total_bytes, file_count) for files matching given extensions."""
        total = 0
        count = 0
        if not os.path.isdir(path):
            return 0, 0
        for dirpath, _dirnames, filenames in os.walk(path):
            for f in filenames:
                if os.path.splitext(f)[1].lower() in extensions:
                    fp = os.path.join(dirpath, f)
                    try:
                        total += os.path.getsize(fp)
                        count += 1
                    except OSError:
                        pass
        return total, count

    def _refresh_storage_info(self):
        """Recalculate and display storage usage by file type."""
        vrt_dir = self.vrt_dir_input.text()
        sizes = {
            "vrt": self._size_by_extensions(vrt_dir, {".vrt"}),
            "ovr": self._size_by_extensions(vrt_dir, {".ovr"}),
            "downloads": self._folder_size(self.download_dir_input.text()),
            "temp": self._temp_bdc_size(),
        }
        total = sum(s for s, _ in sizes.values())

        for key, (sz, cnt) in sizes.items():
            size_lbl, bar, spin, btn = self._storage_rows[key]
            threshold_bytes = spin.value() * 1024 * 1024
            # Use MB as unit for progress bar to stay within int32 range
            bar.setRange(0, max(1, spin.value()))
            bar.setValue(min(sz // (1024 * 1024), spin.value()))
            set_text(size_lbl, f"{_format_size(sz)}  ({cnt} files)")
            if sz > threshold_bytes:
                bar.setStyleSheet("QProgressBar::chunk { background-color: #d73a49; }")
            elif sz > threshold_bytes // 2:
                bar.setStyleSheet("QProgressBar::chunk { background-color: #d29922; }")
            else:
                bar.setStyleSheet("QProgressBar::chunk { background-color: #2da44e; }")
            btn.setEnabled(cnt > 0)

        set_text(self._storage_total_label, f"Total: {_format_size(total)}")

    def _confirm_clean(self, label, size_bytes):
        """Show confirmation before cleaning."""
        return (
            QMessageBox.question(
                self,
                "Confirm Cleanup",
                f"Delete all {label} ({_format_size(size_bytes)})?\n\nThis action cannot be undone.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        )

    def _clean_folder_impl(self, folder_path, label):
        """Generic folder cleanup."""
        sz, _ = self._folder_size(folder_path)
        if sz == 0:
            return
        if not self._confirm_clean(label, sz):
            return
        try:
            shutil.rmtree(folder_path)
            os.makedirs(folder_path, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to clean {label}: {e}")
            return
        self._refresh_storage_info()

    def _clean_by_extension(self, folder, extensions, label):
        """Delete all files with given extensions from a folder tree."""
        sz, cnt = self._size_by_extensions(folder, extensions)
        if sz == 0:
            return
        if not self._confirm_clean(label, sz):
            return
        removed = 0
        for dirpath, _dirs, files in os.walk(folder):
            for f in files:
                if os.path.splitext(f)[1].lower() in extensions:
                    try:
                        os.remove(os.path.join(dirpath, f))
                        removed += 1
                    except OSError:
                        pass
        self._refresh_storage_info()

    def _clean_vrt_files(self):
        self._clean_by_extension(self.vrt_dir_input.text(), {".vrt"}, "VRT files")

    def _clean_ovr_files(self):
        self._clean_by_extension(self.vrt_dir_input.text(), {".ovr"}, "overview files")

    def _clean_downloads_folder(self):
        self._clean_folder_impl(self.download_dir_input.text(), "downloaded images")
        self._refresh_downloads_list()

    def _clean_temp_files(self):
        sz, _ = self._temp_bdc_size()
        if sz == 0:
            return
        if not self._confirm_clean("temporary files", sz):
            return
        for p in self._temp_bdc_paths():
            try:
                if os.path.isfile(p):
                    os.remove(p)
                elif os.path.isdir(p):
                    shutil.rmtree(p)
            except OSError:
                pass
        self._refresh_storage_info()

    def _delete_all_filtered(self):
        """Delete all files currently shown in the filter tree."""
        count = self._clean_tree.topLevelItemCount()
        if count == 0:
            QMessageBox.information(self, "Info", "No filtered files to delete. Run a search first.")
            return
        paths = []
        total_size = 0
        for i in range(count):
            item = self._clean_tree.topLevelItem(i)
            p = item.data(0, Qt.ItemDataRole.UserRole)
            if p and os.path.isfile(p):
                try:
                    total_size += os.path.getsize(p)
                except OSError:
                    pass
                paths.append(p)
        if not paths:
            return
        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Delete all {len(paths)} filtered file(s) ({_format_size(total_size)})?\n\nThis action cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        deleted = 0
        for p in paths:
            try:
                os.remove(p)
                deleted += 1
            except OSError:
                pass
        set_text(self._clean_count_label, f"Deleted {deleted}/{len(paths)} files.")
        self._apply_clean_filter()
        self._refresh_storage_info()
        self._refresh_downloads_list()

    def _apply_clean_filter(self):
        """Populate the selective cleanup tree based on filter and type."""
        import re as _re

        self._clean_tree.clear()
        pattern_text = self._clean_filter_input.text().strip()
        type_filter = english_text(self._clean_type_combo)

        # Build extension filter
        ext_map = {
            ".vrt only": {".vrt"},
            ".ovr only": {".ovr"},
            ".tif only": {".tif", ".tiff"},
        }
        allowed_exts = ext_map.get(type_filter)

        # Compile regex if provided
        regex = None
        if pattern_text:
            try:
                regex = _re.compile(pattern_text, _re.IGNORECASE)
            except _re.error:
                QMessageBox.warning(self, "Invalid Regex", f"Could not compile: {pattern_text}")
                return

        folders = [
            (self.vrt_dir_input.text(), "VRT"),
            (self.download_dir_input.text(), "Downloads"),
        ]
        total_count = 0
        total_size = 0

        for folder, folder_label in folders:
            if not os.path.isdir(folder):
                continue
            for dirpath, _dirs, files in os.walk(folder):
                for fname in files:
                    ext = os.path.splitext(fname)[1].lower()
                    # Type filter
                    if allowed_exts and ext not in allowed_exts:
                        continue
                    if type_filter == "Other" and ext in {".vrt", ".ovr", ".tif", ".tiff"}:
                        continue
                    # Regex filter
                    if regex and not regex.search(fname):
                        continue
                    fpath = os.path.join(dirpath, fname)
                    try:
                        fsize = os.path.getsize(fpath)
                    except OSError:
                        continue
                    item = QTreeWidgetItem(self._clean_tree)
                    item.setText(0, fname)
                    item.setText(1, _format_size(fsize))
                    item.setText(2, folder_label)
                    item.setData(0, Qt.ItemDataRole.UserRole, fpath)
                    total_count += 1
                    total_size += fsize

        self._clean_count_label.setText(
            f"{total_count} files found ({_format_size(total_size)})" if total_count else "No files match the filter."
        )

    def _delete_selected_files(self):
        """Delete files selected in the cleanup tree."""
        selected = self._clean_tree.selectedItems()
        if not selected:
            QMessageBox.information(self, "Info", "Select files to delete.")
            return
        total_size = 0
        paths = []
        for item in selected:
            p = item.data(0, Qt.ItemDataRole.UserRole)
            if p and os.path.isfile(p):
                try:
                    total_size += os.path.getsize(p)
                except OSError:
                    pass
                paths.append(p)
        if not paths:
            return
        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Delete {len(paths)} file(s) ({_format_size(total_size)})?\n\nThis action cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        deleted = 0
        for p in paths:
            try:
                os.remove(p)
                deleted += 1
            except OSError:
                pass
        set_text(self._clean_count_label, f"Deleted {deleted}/{len(paths)} files.")
        self._apply_clean_filter()
        self._refresh_storage_info()
        self._refresh_downloads_list()
