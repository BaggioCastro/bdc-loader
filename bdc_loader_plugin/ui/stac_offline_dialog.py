# -*- coding: utf-8 -*-
"""
STAC Offline Dialog.

Shows connectivity information when STAC is unreachable, provides a test
link, and pings the server periodically to detect recovery.
"""

import threading
import time

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ..i18n import set_text
from ..net import PING_S
from ..stac.client import STAC_URL
from ..timing import STAC_RECOVERED_CLOSE_MS
from ..ui.thumbnails import _invoke_on_ui_thread

# Ping interval in milliseconds (30 seconds)
_PING_INTERVAL_MS = 30_000


class StacOfflineDialog(QDialog):
    """Non-blocking dialog shown when STAC is offline.

    Features:
    - Visual status indicator with offline explanation
    - Clickable link to test STAC URL manually
    - Automatic periodic ping that runs in background threads
    - Auto-closes and notifies on recovery
    """

    def __init__(self, parent=None, on_recovered=None):
        super().__init__(parent)
        self._on_recovered = on_recovered
        self._ping_timer = QTimer(self)
        self._ping_timer.timeout.connect(self._ping_stac)
        self._ping_running = False
        self._setup_ui()
        # Start pinging immediately
        self._ping_timer.start(_PING_INTERVAL_MS)

    def _setup_ui(self):
        self.setWindowTitle("STAC - Connection Status")
        self.setMinimumWidth(460)
        self.setMaximumWidth(560)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 18, 20, 18)

        # --- Header with icon ---
        header = QHBoxLayout()
        dot = QLabel()
        dot.setFixedSize(14, 14)
        dot.setStyleSheet("background-color: #e74c3c; border-radius: 7px;")
        title = QLabel("<b style='font-size:14px;'>STAC Server Offline</b>")
        header.addWidget(dot)
        header.addSpacing(8)
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        # --- Separator ---
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #bdc3c7;")
        layout.addWidget(sep)

        # --- Info text ---
        info = QLabel(
            "The <b>BDC STAC</b> server is currently unreachable.<br><br>"
            "The plugin is operating in <b>offline/fallback mode</b> with "
            "cached collection data. Some features like search and live "
            "temporal extents are unavailable until the server recovers.<br><br>"
            "The plugin will <b>automatically check</b> every 30 seconds "
            "and notify you when the service is back online."
        )
        info.setWordWrap(True)
        info.setStyleSheet("font-size: 12px; color: #2c3e50;")
        layout.addWidget(info)

        # --- Test link ---
        link = QLabel(
            f"<a href='{STAC_URL}' style='color:#2980b9; font-size:12px;'>Open STAC endpoint in browser to test</a>"
        )
        link.setOpenExternalLinks(True)
        link.setStyleSheet("padding: 4px 0;")
        layout.addWidget(link)

        # --- Ping status ---
        self._ping_label = QLabel("")
        self._ping_label.setStyleSheet("font-size: 11px; color: #7f8c8d;")
        layout.addWidget(self._ping_label)

        # --- Buttons ---
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        retry_btn = QPushButton("Check Now")
        retry_btn.setStyleSheet(
            "QPushButton { background-color: #3498db; color: white; "
            "padding: 6px 18px; border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background-color: #2980b9; }"
        )
        retry_btn.clicked.connect(self._ping_stac)
        btn_layout.addWidget(retry_btn)

        close_btn = QPushButton("Continue Offline")
        close_btn.setStyleSheet(
            "QPushButton { background-color: #95a5a6; color: white; "
            "padding: 6px 18px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #7f8c8d; }"
        )
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

    # ------------------------------------------------------------------
    # Ping logic
    # ------------------------------------------------------------------
    def _ping_stac(self):
        """Run a non-blocking STAC connectivity check in a background thread."""
        if self._ping_running:
            return
        self._ping_running = True
        set_text(self._ping_label, "Checking connection...")

        def _check():
            import requests as _req

            try:
                t0 = time.time()
                r = _req.get(STAC_URL, timeout=PING_S)
                ms = int((time.time() - t0) * 1000)
                return r.status_code < 400, ms
            except Exception:
                return False, 0

        def _done(online, ms):
            try:
                from qgis.PyQt import sip

                if sip.isdeleted(self):
                    return
            except (RuntimeError, ReferenceError):
                return
            finally:
                self._ping_running = False

            if online:
                self._ping_timer.stop()
                set_text(
                    self._ping_label,
                    f"<span style='color:#27ae60; font-weight:bold;'>STAC is back online! ({ms}ms)</span>",
                )
                if self._on_recovered:
                    self._on_recovered(ms)
                QTimer.singleShot(STAC_RECOVERED_CLOSE_MS, self.accept)
            else:
                set_text(self._ping_label, "Server still unreachable. Next check in 30 s...")

        def _run():
            online, ms = _check()
            _invoke_on_ui_thread(lambda o=online, m=ms: _done(o, m))

        threading.Thread(target=_run, daemon=True).start()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    def closeEvent(self, event):
        self._ping_timer.stop()
        super().closeEvent(event)

    def reject(self):
        self._ping_timer.stop()
        super().reject()
