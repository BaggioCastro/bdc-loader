"""Access to the vendored pystac_client.

pystac and pystac_client live in lib/ as subpackages of the plugin
(``bdc_loader_plugin.lib.pystac``), so they never replace, or get replaced by,
another plugin's copy in ``sys.modules``. Their remaining dependencies
(requests, python-dateutil) come with QGIS.
"""

import importlib

from qgis.PyQt.QtWidgets import QMessageBox


def ensure_pystac_client():
    """Return the vendored pystac_client module."""
    try:
        return importlib.import_module(f"{__package__}.lib.pystac_client")
    except ModuleNotFoundError as exc:
        QMessageBox.critical(
            None,
            "Missing dependency",
            f"The Python module '{exc.name}' needed by BDC Loader was not found. "
            "Reinstall the plugin from its ZIP; if the module is not part of the plugin, "
            "install it in the Python used by QGIS and restart QGIS.",
        )
        raise RuntimeError(f"Python module '{exc.name}' is not available to BDC Loader.") from exc
