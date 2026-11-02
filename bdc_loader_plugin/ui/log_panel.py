"""
log_panel.py

Activity log for the BDC Loader plugin.

LogButton   — small header button that blinks bright when a new entry arrives.
LogWindow   — floating non-modal dialog that lists log entries, opened on click.

No collapsible panel in the footer; the button lives in the header bar.
"""

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QColor, QFont, QFontMetrics
from qgis.PyQt.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from ..logger import get_log_bus, get_recent_entries

_LEVEL_COLOR = {
    "INFO": "#24292f",
    "WARNING": "#7d4e00",
    "ERROR": "#c0392b",
}
_LEVEL_BG = {
    "INFO": None,
    "WARNING": "#fff8e6",
    "ERROR": "#fff0f0",
}
# Fixed-width level tags (5 chars each)
_LEVEL_TAG = {
    "INFO": "INFO ",
    "WARNING": "WARN ",
    "ERROR": "ERROR",
}
_MAX_VISIBLE = 200
_ROWS_SHOWN = 16
_BLINK_MS = 1500


class LogWindow(QDialog):
    """Floating non-modal window that displays log entries."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("Activity Log — BDC Loader")
        self._setup_ui()
        self._populate_from_history()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel("Last entries — newest at bottom")
        lbl.setStyleSheet("font-size: 10px; color: #57606a;")
        toolbar.addWidget(lbl, 1)

        copy_btn = QPushButton("Copy")
        copy_btn.setFixedSize(52, 22)
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.setToolTip("Copy selected lines, or all lines if none are selected")
        copy_btn.setStyleSheet(
            "QPushButton { font-size:9px; color:#57606a; border: 1px solid #d0d7de; "
            "border-radius:3px; background:#f6f8fa; }"
            "QPushButton:hover { color:#2ecc71; border-color:#2ecc71; }"
        )
        copy_btn.clicked.connect(self._copy)
        toolbar.addWidget(copy_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.setFixedSize(52, 22)
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.setStyleSheet(
            "QPushButton { font-size:9px; color:#57606a; border: 1px solid #d0d7de; "
            "border-radius:3px; background:#f6f8fa; }"
            "QPushButton:hover { color:#e74c3c; border-color:#e74c3c; }"
        )
        clear_btn.clicked.connect(self._clear)
        toolbar.addWidget(clear_btn)
        layout.addLayout(toolbar)

        mono = QFont("Monospace")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(9)
        row_h = QFontMetrics(mono).height() + 6
        list_h = row_h * _ROWS_SHOWN + 4

        self._list = QListWidget()
        self._list.setFont(mono)
        self._list.setFixedHeight(list_h)
        self._list.setAlternatingRowColors(True)
        self._list.setStyleSheet(
            "QListWidget {"
            "  background:#fafbfc; alternate-background-color:#f2f4f6;"
            "  border: 1px solid #d0d7de; border-radius: 5px; outline: 0;"
            "}"
            "QListWidget::item { padding: 3px 8px; border-bottom: 1px solid #eaedf0; }"
            "QListWidget::item:hover { background:#eef6ff; }"
            # Explicit selected-state colors so a row's own level color/tint
            # (set per-item in add_entry) never ends up unreadable against
            # the selection highlight.
            "QListWidget::item:selected { background:#bfe0ff; color:#0b2e4f; }"
            "QListWidget::item:selected:!active { background:#d3ebff; color:#0b2e4f; }"
        )
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        layout.addWidget(self._list)

        self.adjustSize()
        self.setMinimumWidth(860)
        self.resize(self.minimumWidth(), list_h + 60)

    def add_entry(self, entry: dict, scroll: bool = True):
        level = entry.get("level", "INFO")
        tag = _LEVEL_TAG.get(level, "INFO ")
        color = _LEVEL_COLOR.get(level, _LEVEL_COLOR["INFO"])
        bg = _LEVEL_BG.get(level)
        src = entry.get("src", "?")
        ts = entry.get("ts", "")
        time_part = ts[11:19] if len(ts) >= 19 else ts
        full_msg = entry.get("msg", "")
        text = f"[{tag}]  {src:<14}  {time_part}  {full_msg.splitlines()[0][:320]}"

        item = QListWidgetItem(text)
        item.setToolTip(full_msg)
        # The displayed text truncates long/multi-line messages for the list
        # row; Copy uses this untruncated version instead.
        item.setData(Qt.ItemDataRole.UserRole, f"[{tag}]  {src:<14}  {time_part}  {full_msg}")
        item.setForeground(QColor(color))
        if bg:
            item.setBackground(QColor(bg))

        if self._list.count() >= _MAX_VISIBLE:
            self._list.takeItem(0)

        self._list.addItem(item)
        if scroll:
            self._list.scrollToBottom()

    def _populate_from_history(self):
        for entry in get_recent_entries(_MAX_VISIBLE):
            self.add_entry(entry, scroll=False)
        if self._list.count():
            self._list.scrollToBottom()

    def _copy(self):
        """Copy the selected lines, or every visible line if none are
        selected, as plain text — so a user can paste the activity log into
        a chat/email to send to someone for support."""
        selected = self._list.selectedItems()
        items = selected if selected else [self._list.item(i) for i in range(self._list.count())]
        lines = [item.data(Qt.ItemDataRole.UserRole) or item.text() for item in items]
        QApplication.clipboard().setText("\n".join(lines))

    def _clear(self):
        self._list.clear()

    def closeEvent(self, event):
        # Hide instead of destroy so state is preserved
        event.ignore()
        self.hide()


class LogButton(QPushButton):
    """
    Header button that opens/closes the LogWindow and blinks bright
    when a new log entry arrives while the window is closed.
    """

    _STYLE_IDLE = (
        "QPushButton { background-color: #57606a; color: #bdc3c7; border: none; "
        "border-radius: 4px; font-size: 9px; font-weight: bold; }"
        "QPushButton:hover { background-color: #484f58; color: white; }"
        "QPushButton:pressed { background-color: #3a3f44; }"
    )
    _STYLE_LIT = (
        "QPushButton { background-color: #57606a; color: white; border: none; "
        "border-radius: 4px; font-size: 9px; font-weight: bold; }"
    )
    _STYLE_ERROR = (
        "QPushButton { background-color: #7d1a1a; color: #ffcccc; border: none; "
        "border-radius: 4px; font-size: 9px; font-weight: bold; }"
    )

    def __init__(self, parent=None):
        super().__init__("Log", parent)
        self.setFixedSize(38, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(self._STYLE_IDLE)

        self._window = LogWindow(parent)
        self._blink_timer = QTimer(self)
        self._blink_timer.setSingleShot(True)
        self._blink_timer.timeout.connect(self._dim)
        self._has_error = False

        self.clicked.connect(self._toggle_window)
        get_log_bus().new_entry.connect(self._on_new_entry)

    def _toggle_window(self):
        if self._window.isVisible():
            self._window.hide()
        else:
            self._window.show()
            self._window.raise_()
            # Stop any pending blink and return to idle
            self._blink_timer.stop()
            self._has_error = False
            self.setStyleSheet(self._STYLE_IDLE)

    def _on_new_entry(self, entry: dict):
        self._window.add_entry(entry)
        if not self._window.isVisible():
            self._has_error = entry.get("level") == "ERROR"
            self.setStyleSheet(self._STYLE_ERROR if self._has_error else self._STYLE_LIT)
            self._blink_timer.start(_BLINK_MS)

    def _dim(self):
        if not self._has_error:
            self.setStyleSheet(self._STYLE_IDLE)
