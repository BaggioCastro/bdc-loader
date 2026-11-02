"""What the chart area shows when no usable matplotlib can be imported: why, how to get it, and a button that installs it for the plugin."""

import threading

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from ..i18n import set_text
from ..ui.thumbnails import _invoke_on_ui_thread
from . import mpl_env


class MatplotlibMissing(QWidget):
    """Explains the missing chart and installs matplotlib on request; emits ``installed`` when done."""

    installed = pyqtSignal(str)

    def __init__(self, parent=None, state=None, platform=None, os_release=None):
        super().__init__(parent)
        state, version = state or mpl_env.status()
        self._installer = None
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if state == "too_old":
            text = (
                f"The chart needs matplotlib 3.5 or newer; this QGIS has {version}.\n"
                "Update it with the package manager or installer QGIS came from:"
            )
        else:
            text = (
                "The chart needs matplotlib, which this QGIS installation does not have.\n"
                "Install a version compatible with the plugin, or add it to QGIS with:"
            )
        self.message = QLabel(text)
        self.message.setWordWrap(True)
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setStyleSheet("color: #2c3e50; font-size: 11px;")
        self.hint = QLabel(mpl_env.system_install_hint(platform, os_release))
        self.hint.setWordWrap(True)
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.hint.setStyleSheet("font-family: monospace; font-size: 11px; color: #24292f;")

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.install_btn = QPushButton("Install matplotlib for the plugin")
        self.install_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.install_btn.clicked.connect(self._confirm_install)
        self.install_btn.setVisible(state == "missing")
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._cancel)
        self.cancel_btn.setVisible(False)
        buttons.addWidget(self.install_btn)
        buttons.addWidget(self.cancel_btn)
        buttons.addStretch()

        self.progress = QLabel("")
        self.progress.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress.setWordWrap(True)
        self.progress.setStyleSheet("font-size: 10px; color: #57606a;")

        for widget in (self.message, self.hint):
            layout.addWidget(widget)
        layout.addLayout(buttons)
        layout.addWidget(self.progress)

    def _confirm_install(self):
        answer = QMessageBox.question(
            self,
            "Install matplotlib",
            "Install the matplotlib version compatible with BDC Loader?\n\n"
            "It is downloaded once and kept in the plugin's own folder. "
            "Packages QGIS already has are used as they are.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.start_install()

    def start_install(self):
        self.install_btn.setVisible(False)
        self.cancel_btn.setVisible(True)
        set_text(self.progress, "Starting...")
        self._installer = mpl_env.Installer(
            progress=lambda text: _invoke_on_ui_thread(lambda: self.progress.setText(text))
        )
        threading.Thread(target=self._run, args=(self._installer,), daemon=True, name="bdc-mpl-install").start()

    def _run(self, installer):
        try:
            result = ("ok", installer.run())
        except mpl_env.InstallCancelled:
            result = ("cancelled", "")
        except Exception as exc:
            result = ("error", str(exc))
        _invoke_on_ui_thread(lambda: self._finished(*result))

    def _cancel(self):
        if self._installer is not None:
            set_text(self.progress, "Cancelling...")
            self._installer.cancel()

    def _finished(self, outcome, detail):
        self._installer = None
        self.cancel_btn.setVisible(False)
        if outcome == "ok" and mpl_env.load_matplotlib() is not None:
            set_text(self.progress, f"matplotlib {detail} installed.")
            self.installed.emit(detail)
            return
        self.install_btn.setVisible(True)
        if outcome == "cancelled":
            set_text(self.progress, "Installation cancelled.")
        else:
            set_text(self.progress, f"Installation failed: {detail or 'matplotlib still cannot be imported.'}")
