"""Dialog that sets the timeline's previous and next date shortcuts, warning about clashes with QGIS shortcuts."""

import logging

_logger = logging.getLogger("bdc_loader")

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QKeySequence
from qgis.PyQt.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..i18n import set_text

# QGIS built-in shortcuts (avoid overriding)
_QGIS_BUILTIN_SHORTCUTS = {
    "Ctrl+Z",
    "Ctrl+Y",
    "Ctrl+S",
    "Ctrl+Shift+S",
    "Ctrl+N",
    "Ctrl+O",
    "Ctrl+P",
    "Ctrl+Q",
    "Ctrl+W",
    "Ctrl+C",
    "Ctrl+V",
    "Ctrl+X",
    "Ctrl+A",
    "Ctrl+F",
    "Ctrl+G",
    "Ctrl+H",
    "Ctrl+L",
    "Ctrl+D",
    "Ctrl+Shift+N",
    "F5",
    "F11",
    "Ctrl+Shift+F",
    "Ctrl+Shift+P",
    "Ctrl+Tab",
    "Ctrl+E",
    "Ctrl+Shift+C",
    "Ctrl+Shift+V",
    "Ctrl++",
    "Ctrl+-",
    "Ctrl+0",
    "Ctrl+1",
    "Ctrl+2",
    "Ctrl+3",
    "Ctrl+4",
    "Ctrl+5",
    "Delete",
    "Backspace",
    "Space",
    "F1",
    "F2",
    "Escape",
}


class ShortcutConfigDialog(QDialog):
    """Dialog for configuring timeline keyboard shortcuts."""

    # Defaults that avoid common QGIS conflicts
    DEFAULT_PREV = "Alt+Left"
    DEFAULT_NEXT = "Alt+Right"

    def __init__(self, current_prev, current_next, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⌨️ Keyboard Shortcuts — BDC Timeline")
        self.setFixedWidth(440)
        self.setStyleSheet("QDialog { background: #f8f9fa; }")

        self._qgis_shortcuts = self._collect_qgis_shortcuts()

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 16, 20, 16)

        # Title
        title = QLabel("⌨️ Configure Timeline Shortcuts")
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #1a3a5c;")
        layout.addWidget(title)

        # Hint box
        hint_box = QLabel(
            "Click in the field and <b>press</b> your desired key combination.<br>"
            "Do not type — just press the shortcut keys."
        )
        hint_box.setWordWrap(True)
        hint_box.setStyleSheet(
            "background: #fff8e1; border: 1px solid #ffe082; border-radius: 6px; "
            "padding: 10px 14px; font-size: 10px; color: #6d4c00;"
        )
        layout.addWidget(hint_box)

        self._build_shortcut_cards(layout, current_prev, current_next)

        # Warning area (fixed height to prevent layout shift)
        self.warning_label = QLabel("")
        self.warning_label.setFixedHeight(36)
        self.warning_label.setWordWrap(True)
        self.warning_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._set_warning_ok()
        layout.addWidget(self.warning_label)

        self._build_dialog_buttons(layout)

    def _build_shortcut_cards(self, layout, current_prev, current_next):
        """One card per direction: arrow, label, key sequence field and a clear button."""
        _KEY_EDIT_STYLE = (
            "QKeySequenceEdit { padding: 6px 12px; border: 2px solid #ffd54f; "
            "border-radius: 5px; font-size: 13px; font-weight: bold; "
            "background: #fff9c4; color: #333; } "
            "QKeySequenceEdit:focus { border-color: #f9a825; background: #fff176; }"
        )

        for label_text, icon, attr_name, default_seq in [
            ("Previous date", "◀", "prev_edit", current_prev),
            ("Next date", "▶", "next_edit", current_next),
        ]:
            card = QWidget()
            card.setStyleSheet("QWidget { background: #fff; border: 1px solid #dce3ec; border-radius: 8px; }")
            card_lay = QHBoxLayout(card)
            card_lay.setContentsMargins(14, 10, 14, 10)
            card_lay.setSpacing(10)

            icon_lbl = QLabel(icon)
            icon_lbl.setFixedWidth(20)
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_lbl.setStyleSheet("font-size: 16px; color: #2e7dd1; border: none; font-weight: bold;")
            card_lay.addWidget(icon_lbl)

            lbl = QLabel(label_text)
            lbl.setStyleSheet("font-size: 11px; font-weight: bold; color: #2a4a6a; border: none;")
            lbl.setFixedWidth(95)
            card_lay.addWidget(lbl)

            edit = QKeySequenceEdit(QKeySequence(default_seq))
            edit.setStyleSheet(_KEY_EDIT_STYLE)
            edit.setToolTip("Click here, then press your desired shortcut keys")
            edit.keySequenceChanged.connect(self._check_conflicts)
            card_lay.addWidget(edit, stretch=1)

            # Clear button for this field
            clear_btn = QPushButton("✕")
            clear_btn.setFixedSize(22, 22)
            clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            clear_btn.setToolTip("Clear this shortcut")
            clear_btn.setStyleSheet(
                "QPushButton { background: transparent; border: none; "
                "font-size: 12px; color: #999; font-weight: bold; } "
                "QPushButton:hover { color: #c0392b; }"
            )
            clear_btn.clicked.connect(lambda _, e=edit: e.clear())
            card_lay.addWidget(clear_btn)

            setattr(self, attr_name, edit)
            layout.addWidget(card)

    def _build_dialog_buttons(self, layout):
        """Reset Defaults, Cancel and Apply buttons."""
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        reset_btn = QPushButton("↺ Reset Defaults")
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.setToolTip(f"Reset to defaults: {self.DEFAULT_PREV} / {self.DEFAULT_NEXT}")
        reset_btn.setStyleSheet(
            "QPushButton { padding: 6px 14px; border-radius: 5px; font-size: 11px; "
            "background: #f0f2f5; border: 1px solid #d0d4da; color: #555; } "
            "QPushButton:hover { background: #e0e4ea; border-color: #999; }"
        )
        reset_btn.clicked.connect(self._reset_defaults)
        btn_layout.addWidget(reset_btn)

        btn_layout.addStretch(1)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet(
            "QPushButton { padding: 6px 18px; border-radius: 5px; font-size: 11px; "
            "background: #fff; border: 1px solid #ccc; color: #555; } "
            "QPushButton:hover { background: #f5f5f5; border-color: #999; }"
        )
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        ok_btn = QPushButton("✓ Apply")
        ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_btn.setDefault(True)
        ok_btn.setStyleSheet(
            "QPushButton { padding: 6px 22px; border-radius: 5px; font-size: 11px; "
            "font-weight: bold; background: #2e7dd1; border: none; color: #fff; } "
            "QPushButton:hover { background: #1a5fa8; }"
        )
        ok_btn.clicked.connect(self._validate_and_accept)
        btn_layout.addWidget(ok_btn)

        layout.addLayout(btn_layout)

    def _set_warning_ok(self):
        set_text(self.warning_label, "No conflicts detected.")
        self.warning_label.setStyleSheet(
            "color: #27ae60; font-size: 10px; padding: 4px 10px; "
            "background: #eafaf1; border: 1px solid #a9dfbf; border-radius: 5px;"
        )

    def _set_warning_conflict(self, text):
        self.warning_label.setText(text)
        self.warning_label.setStyleSheet(
            "color: #c0392b; font-size: 10px; padding: 4px 10px; "
            "background: #fdf0ef; border: 1px solid #f5c6cb; border-radius: 5px;"
        )

    def _reset_defaults(self):
        self.prev_edit.setKeySequence(QKeySequence(self.DEFAULT_PREV))
        self.next_edit.setKeySequence(QKeySequence(self.DEFAULT_NEXT))
        self._check_conflicts()

    def _collect_qgis_shortcuts(self):
        """Collect registered QGIS shortcuts."""
        shortcuts = {}  # normalized_key -> action_name
        try:
            from qgis.gui import QgsGui

            mgr = QgsGui.shortcutsManager()
            for action in mgr.listActions():
                seq = action.shortcut()
                if not seq.isEmpty():
                    key = seq.toString()
                    shortcuts[key] = action.text().replace("&", "")
            for sc in mgr.listShortcuts():
                seq = sc.key()
                if not seq.isEmpty():
                    key = seq.toString()
                    if key not in shortcuts:
                        shortcuts[key] = sc.whatsThis() or sc.objectName() or key
        except Exception:
            # Fallback: use static set
            for k in _QGIS_BUILTIN_SHORTCUTS:
                shortcuts[QKeySequence(k).toString()] = k
        return shortcuts

    def _find_conflict(self, seq):
        """Return conflict description or None."""
        if seq.isEmpty():
            return None
        key = seq.toString()
        action_name = self._qgis_shortcuts.get(key)
        if action_name:
            return f"'{key}' conflicts with: {action_name}"
        return None

    def _check_conflicts(self):
        """Check for conflicts in real-time."""
        msgs = []
        c1 = self._find_conflict(self.prev_edit.keySequence())
        if c1:
            msgs.append(c1)
        c2 = self._find_conflict(self.next_edit.keySequence())
        if c2:
            msgs.append(c2)
        # Check if both are the same
        seq_p = self.prev_edit.keySequence().toString()
        seq_n = self.next_edit.keySequence().toString()
        if seq_p and seq_n and seq_p == seq_n:
            msgs.append("Both shortcuts are the same!")
        if msgs:
            self._set_warning_conflict("⚠️ " + " | ".join(msgs))
        else:
            self._set_warning_ok()

    def _validate_and_accept(self):
        seq_prev = self.prev_edit.keySequence()
        seq_next = self.next_edit.keySequence()

        if seq_prev.isEmpty() or seq_next.isEmpty():
            QMessageBox.warning(self, "Error", "Both shortcuts must be set.")
            return

        if seq_prev.toString() == seq_next.toString():
            QMessageBox.warning(self, "Error", "Both shortcuts cannot be the same.")
            return

        conflicts = []
        c1 = self._find_conflict(seq_prev)
        if c1:
            conflicts.append(c1)
        c2 = self._find_conflict(seq_next)
        if c2:
            conflicts.append(c2)

        if conflicts:
            msg = (
                "Shortcut conflict detected:\n\n"
                + "\n".join(f"  • {c}" for c in conflicts)
                + "\n\nUse these shortcuts anyway?\n"
                "(The QGIS shortcut may stop working)"
            )
            reply = QMessageBox.warning(
                self,
                "Shortcut conflict",
                msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self.accept()

    def get_shortcuts(self):
        return self.prev_edit.keySequence().toString(), self.next_edit.keySequence().toString()
