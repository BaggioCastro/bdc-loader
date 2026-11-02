# -*- coding: utf-8 -*-
"""BDC Loader - Main QGIS plugin class."""

import os
import shutil

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMenu, QToolButton

from .paths import temp_files


class BDCLoaderPlugin:
    """Main BDC Loader plugin class."""

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.tool_button = None
        self.action_loader = None
        self.action_ts = None
        self._toolbar_widget_action = None  # QAction returned by addWidget
        self.dialog = None
        self.timeline_toolbar = None

    @staticmethod
    def _cleanup_temp_files():
        """Remove the temp files of earlier sessions."""
        for p in temp_files():
            try:
                os.remove(p) if os.path.isfile(p) else shutil.rmtree(p, ignore_errors=True)
            except OSError:
                pass

    def initGui(self):
        """Initialize the plugin interface."""
        self._cleanup_temp_files()
        # BDC layers restored with a project are read with the plugin's
        # network options before the plugin itself runs.
        from .core.gdal_env import apply_session_options

        apply_session_options()

        icon_path = os.path.join(self.plugin_dir, "icon.png")
        icon = QIcon(icon_path)
        mw = self.iface.mainWindow()

        # --- Action: Open Loader ---
        self.action_loader = QAction(icon, "BDC Loader", mw)
        self.action_loader.setWhatsThis("Opens the Brazil Data Cube data loader")
        self.action_loader.triggered.connect(self.run)

        # --- Action: Open Time Series ---
        self.action_ts = QAction(icon, "BDC Time Series", mw)
        self.action_ts.setWhatsThis("Opens the BDC time series panel")
        self.action_ts.triggered.connect(self._open_ts_panel)

        # --- Menu dropdown ---
        menu = QMenu(mw)
        menu.addAction(self.action_loader)
        menu.addAction(self.action_ts)

        # --- QToolButton with a menu arrow ---
        self.tool_button = QToolButton(mw)
        self.tool_button.setIcon(icon)
        self.tool_button.setToolTip("BDC Loader")
        self.tool_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.tool_button.setMenu(menu)
        self.tool_button.setDefaultAction(self.action_loader)

        # Add button to the QGIS toolbar
        self._toolbar_widget_action = self.iface.pluginToolBar().addWidget(self.tool_button)

        # Raster menu entries
        self.iface.addPluginToRasterMenu("&BDC Loader", self.action_loader)
        self.iface.addPluginToRasterMenu("&BDC Loader", self.action_ts)

        # Timeline toolbar in the QGIS main window
        from .widgets import cursors
        from .widgets.timeline_slider import VRTTimelineSlider

        self.timeline_toolbar = VRTTimelineSlider(self.iface)
        cursors.watch(self.timeline_toolbar)
        self.iface.mainWindow().addToolBar(Qt.ToolBarArea.TopToolBarArea, self.timeline_toolbar)
        self.timeline_toolbar.setVisible(False)  # Hidden until VRTs are loaded
        self.timeline_toolbar.scan_project_layers()  # Check existing VRTs

    def unload(self):
        """Remove the plugin from the interface."""
        self.iface.removePluginRasterMenu("&BDC Loader", self.action_loader)
        self.iface.removePluginRasterMenu("&BDC Loader", self.action_ts)

        if self._toolbar_widget_action:
            self.iface.pluginToolBar().removeAction(self._toolbar_widget_action)
            self._toolbar_widget_action = None

        if self.tool_button:
            self.tool_button.deleteLater()
            self.tool_button = None

        # Remove timeline toolbar
        if self.timeline_toolbar:
            self.timeline_toolbar.cleanup()
            self.iface.mainWindow().removeToolBar(self.timeline_toolbar)
            self.timeline_toolbar.deleteLater()
            self.timeline_toolbar = None

        # Shut down the thumbnail thread pool to avoid dangling threads
        try:
            from .ui.thumbnails import shutdown_thumb_executor

            shutdown_thumb_executor()
        except Exception:
            pass

        if self.dialog:
            # Close time series panel if it exists
            if hasattr(self.dialog, "_ts_panel") and self.dialog._ts_panel:
                self.dialog._ts_panel.remove_temp_layer()
                # Remove the separate chart dock
                if hasattr(self.dialog._ts_panel, "chart_dock") and self.dialog._ts_panel.chart_dock:
                    self.iface.removeDockWidget(self.dialog._ts_panel.chart_dock)
                    self.dialog._ts_panel.chart_dock.close()
                    self.dialog._ts_panel.chart_dock = None
                self.iface.removeDockWidget(self.dialog._ts_panel)
                self.dialog._ts_panel.close()
                self.dialog._ts_panel = None
            self.dialog.close()
            self.dialog = None

    def run(self):
        """Open the BDC Loader dialog."""
        from .ui.main_dialog import BDCLoaderDialog

        if not self.dialog:
            self.dialog = BDCLoaderDialog(self.iface, timeline_toolbar=self.timeline_toolbar)

        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def _open_ts_panel(self):
        """Open the BDC Time Series panel directly."""
        from .ui.main_dialog import BDCLoaderDialog

        # Ensure dialog exists (ts_panel is managed by it)
        if not self.dialog:
            self.dialog = BDCLoaderDialog(self.iface, timeline_toolbar=self.timeline_toolbar)

        # Open/show the time series panel
        self.dialog._toggle_timeseries_panel(True)
