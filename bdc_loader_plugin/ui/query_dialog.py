# -*- coding: utf-8 -*-
"""
Query Export and Import Dialogs.

Provides UI dialogs for:
- QueryExportDialog: Exporting active query state to multiple formats (JSON, YAML, R sits, R rstac, Python, cURL).
- QueryImportDialog: Importing JSON/YAML query specifications with real-time validation and Tab materialization.

Developed by Baggio Luiz de Castro e Silva
INPE - Sao Jose dos Campos, 2026
"""

from qgis.PyQt.QtCore import QEvent, Qt, QTimer
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from ..core.query_spec import (
    clean_collection_id,
    parse_query_text,
    query_to_curl,
    query_to_json,
    query_to_python,
    query_to_r_rstac,
    query_to_r_sits,
    query_to_yaml,
    sits_collection_for,
)
from ..i18n import TRANSLATE_ITEMS, english_text, set_text, tr
from ..timing import COPIED_LABEL_MS
from ..widgets.sizing import fix_width_for_texts

# Reusable UI Stylesheet Constants
_BTN_ACCENT = """
    QPushButton { background-color: #05C4B4; color: white; font-weight: bold; padding: 6px 16px; border: none; border-radius: 4px; }
    QPushButton:hover { background-color: #04a89a; }
    QPushButton:disabled { background-color: #8c9ba5; color: #ffffff; }
"""
_BTN_PRIMARY = """
    QPushButton { background-color: #2980b9; color: white; font-weight: bold; padding: 4px 10px; border: none; border-radius: 4px; font-size: 11px; }
    QPushButton:hover { background-color: #1f6693; }
"""
_BTN_SECONDARY = """
    QPushButton { background-color: #f6f8fa; color: #24292f; border: 1px solid #d0d7de; padding: 4px 12px; border-radius: 4px; font-size: 11px; }
    QPushButton:hover { background-color: #eaeef2; border-color: #0969da; }
"""
_BTN_CANCEL = """
    QPushButton { background-color: #6e7681; color: white; padding: 6px 16px; border: none; border-radius: 4px; }
    QPushButton:hover { background-color: #57606a; }
"""
_EDITOR_DARK = "QTextEdit { background-color: #1e1e1e; color: #d4d4d4; border: 1px solid #3c3c3c; border-radius: 4px; padding: 8px; }"
_EDITOR_LIGHT = "QTextEdit { background-color: #ffffff; color: #24292f; border: 1px solid #d0d7de; border-radius: 4px; padding: 8px; } QTextEdit:focus { border-color: #0969da; }"


def _get_mono_font(size: int = 10) -> QFont:
    font = QFont("Monospace")
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSize(size)
    return font


class QueryExportDialog(QDialog):
    """Dialog for exporting current query parameters to JSON, YAML, R sits, R rstac, Python, cURL."""

    def __init__(self, query_spec: dict, parent=None):
        super().__init__(parent)
        self.query_spec = query_spec
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("Export Query / Code")
        self.resize(660, 500)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header Title
        header = QHBoxLayout()
        header.addWidget(
            QLabel("<b style='font-size:13px; color:#2c3e50;'>Export Query Parameters / Code Snippets</b>")
        )
        header.addStretch()
        layout.addLayout(header)

        # Format Selector Toolbar
        fmt_layout = QHBoxLayout()
        fmt_label = QLabel("Format:")
        fmt_label.setStyleSheet("font-weight: bold; color: #2c3e50;")
        fmt_layout.addWidget(fmt_label)

        self.format_combo = QComboBox()
        self.format_combo.addItems(
            [
                "JSON (Generic Spec)",
                "YAML (Generic Spec)",
                "R - sits Package (Data Cube)",
                "R - rstac Package (STAC API)",
                "Python (pystac-client)",
                "cURL / HTTP Request",
            ]
        )
        self.format_combo.setStyleSheet(
            "QComboBox { padding: 4px 8px; border: 1px solid #d0d7de; border-radius: 4px; background-color: #ffffff; color: #24292f; } QComboBox:hover { border-color: #0969da; }"
        )
        self.format_combo.setProperty(TRANSLATE_ITEMS, True)
        self.format_combo.currentIndexChanged.connect(self._update_code_display)
        fmt_layout.addWidget(self.format_combo, 1)
        layout.addLayout(fmt_layout)

        # Availability warning (shown when the sits format is picked for a
        # collection that the sits BDC source does not provide).
        self.sits_warning_label = QLabel()
        self.sits_warning_label.setWordWrap(True)
        self.sits_warning_label.setStyleSheet(
            "background-color: #fff3cd; color: #663c00; border: 1px solid #ffe69c;"
            " border-radius: 4px; padding: 6px 8px; font-size: 11px;"
        )
        self.sits_warning_label.setVisible(False)
        layout.addWidget(self.sits_warning_label)

        # Code Viewport
        self.code_editor = QTextEdit()
        self.code_editor.setReadOnly(True)
        self.code_editor.setFont(_get_mono_font(10))
        self.code_editor.setStyleSheet(_EDITOR_DARK)
        layout.addWidget(self.code_editor, 1)

        # Action Buttons
        btn_layout = QHBoxLayout()

        self.copy_btn = QPushButton("Copy to Clipboard")
        self.copy_btn.setStyleSheet(_BTN_ACCENT)
        self.copy_btn.clicked.connect(self._copy_to_clipboard)
        btn_layout.addWidget(self.copy_btn)
        fix_width_for_texts(self.copy_btn, ("Copy to Clipboard", "Copied!"))

        self.save_btn = QPushButton("Save File...")
        self.save_btn.setStyleSheet(_BTN_SECONDARY)
        self.save_btn.clicked.connect(self._save_to_file)
        btn_layout.addWidget(self.save_btn)

        btn_layout.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(_BTN_CANCEL)
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)
        self._update_code_display()

    def _update_code_display(self):
        fmt = english_text(self.format_combo)
        q = self.query_spec

        collection = clean_collection_id(q.get("collection"))
        if "sits" in fmt and sits_collection_for(collection) is None:
            set_text(
                self.sits_warning_label,
                f'Collection "{collection}" is not available in the sits BDC source. '
                "The generated sits_cube() will not run. Use the R - rstac or Python export instead, "
                'or check sits::sits_list_collections(source = "BDC").',
            )
            self.sits_warning_label.setVisible(True)
        else:
            self.sits_warning_label.setVisible(False)

        generators = {
            "JSON": query_to_json,
            "YAML": query_to_yaml,
            "sits": query_to_r_sits,
            "rstac": query_to_r_rstac,
            "Python": query_to_python,
            "cURL": query_to_curl,
        }
        for key, func in generators.items():
            if key in fmt:
                self.code_editor.setPlainText(func(q))
                return
        self.code_editor.setPlainText("")

    def _copy_to_clipboard(self):
        QApplication.clipboard().setText(self.code_editor.toPlainText())
        set_text(self.copy_btn, "Copied!")
        QTimer.singleShot(COPIED_LABEL_MS, lambda: set_text(self.copy_btn, "Copy to Clipboard"))

    def _save_to_file(self):
        fmt = english_text(self.format_combo)
        ext_filter = (
            "JSON Files (*.json)"
            if "JSON" in fmt
            else "YAML Files (*.yaml *.yml)"
            if "YAML" in fmt
            else "R Scripts (*.R)"
            if "R -" in fmt
            else "Python Scripts (*.py)"
            if "Python" in fmt
            else "Text Files (*.txt *.sh)"
        )

        filename, _ = QFileDialog.getSaveFileName(self, "Save Query File", "", ext_filter)
        if filename:
            try:
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(self.code_editor.toPlainText())
                QMessageBox.information(self, "Saved", f"File saved successfully:\n{filename}")
            except Exception as e:
                QMessageBox.critical(self, "Save Error", f"Could not save file: {e}")


class QueryImportDialog(QDialog):
    """Dialog for importing query specifications in JSON or YAML format into plugin UI."""

    def __init__(self, parent=None, on_apply_callback=None, get_current_spec_callback=None):
        super().__init__(parent)
        self.on_apply_callback = on_apply_callback
        self.get_current_spec_callback = get_current_spec_callback
        self._parsed_data = None
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("Import Query Specification")
        self.resize(660, 480)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # Header bar
        top_bar = QHBoxLayout()
        top_bar.addWidget(
            QLabel("<b style='font-size:13px; color:#2c3e50;'>Paste JSON/YAML text or load from file:</b>")
        )
        top_bar.addStretch()

        self.fill_current_btn = QPushButton("Fill from Current UI (Tab)")
        self.fill_current_btn.setStyleSheet(_BTN_PRIMARY)
        self.fill_current_btn.setToolTip("Press Tab or click to insert current plugin UI query parameters")
        self.fill_current_btn.clicked.connect(self._materialize_current_ui_spec)
        top_bar.addWidget(self.fill_current_btn)

        open_file_btn = QPushButton("Open File...")
        open_file_btn.setStyleSheet(_BTN_SECONDARY)
        open_file_btn.clicked.connect(self._open_file)
        top_bar.addWidget(open_file_btn)
        layout.addLayout(top_bar)

        # Text Editor
        self.input_editor = QTextEdit()
        self.input_editor.setFont(_get_mono_font(10))
        self.input_editor.setPlaceholderText(
            "Paste JSON or YAML query specification here...\n\n"
            "Tip: Press Tab to instantly fill with current plugin UI parameters!\n\n"
            'Example:\n{\n  "collection": "S2-16D-2",\n  "temporal": {"start": "2024-01-01", "end": "2024-12-31"}\n}'
        )
        self.input_editor.setStyleSheet(_EDITOR_LIGHT)
        self.input_editor.textChanged.connect(self._validate_text)
        self.input_editor.installEventFilter(self)
        layout.addWidget(self.input_editor, 1)

        # Status Label
        self.status_label = QLabel("Waiting for input (Press Tab to insert current UI query)...")
        self.status_label.setStyleSheet("font-size: 11px; color: #57606a;")
        layout.addWidget(self.status_label)

        # Action Bar
        btn_layout = QHBoxLayout()
        self.apply_btn = QPushButton("Apply to Plugin UI")
        self.apply_btn.setEnabled(False)
        self.apply_btn.setStyleSheet(_BTN_ACCENT)
        self.apply_btn.clicked.connect(self._apply_to_ui)
        btn_layout.addWidget(self.apply_btn)

        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(_BTN_CANCEL)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

    def eventFilter(self, obj, event):
        """Intercepts Tab key press in editor to materialize current UI query parameters."""
        if obj == self.input_editor and event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Tab:
            if not self.input_editor.toPlainText().strip():
                self._materialize_current_ui_spec()
                return True
        return super().eventFilter(obj, event)

    def _materialize_current_ui_spec(self):
        if self.get_current_spec_callback:
            try:
                spec = self.get_current_spec_callback()
                if spec:
                    self.input_editor.setPlainText(query_to_json(spec))
            except Exception as e:
                QMessageBox.warning(self, "Materialization Error", f"Could not read current UI spec: {e}")

    def _open_file(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Open Query Specification File",
            "",
            "Supported (*.json *.yaml *.yml);;JSON (*.json);;YAML (*.yaml *.yml)",
        )
        if filename:
            try:
                with open(filename, "r", encoding="utf-8") as f:
                    self.input_editor.setPlainText(f.read())
            except Exception as e:
                QMessageBox.critical(self, "Read Error", f"Could not read file: {e}")

    def _validate_text(self):
        raw_text = self.input_editor.toPlainText()
        ok, data, msg = parse_query_text(raw_text)
        if ok:
            self._parsed_data = data
            self.status_label.setText(f"<span style='color:#27ae60; font-weight:bold;'>{tr(msg)}</span>")
            self.apply_btn.setEnabled(True)
        else:
            self._parsed_data = None
            if not raw_text.strip():
                set_text(self.status_label, "Waiting for input (Press Tab to insert current UI query)...")
                self.status_label.setStyleSheet("font-size: 11px; color: #57606a;")
            else:
                self.status_label.setText(f"<span style='color:#cf222e; font-weight:bold;'>{tr(msg)}</span>")
            self.apply_btn.setEnabled(False)

    def _apply_to_ui(self):
        if self._parsed_data and self.on_apply_callback:
            try:
                self.on_apply_callback(self._parsed_data)
                QMessageBox.information(
                    self, "Query Loaded", "The query parameters have been successfully applied to the plugin interface."
                )
                self.accept()
            except Exception as e:
                QMessageBox.critical(self, "Application Error", f"Could not apply query to UI: {e}")
