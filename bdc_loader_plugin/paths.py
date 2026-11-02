"""Folders the plugin writes to.

They live under the QGIS profile, in ``<profile>/bdc_loader/``. The plugin's
own folder is never written to: a system-wide install can be read-only, and
an update replaces it. Nothing is written under the profile's
``python/plugins`` either, where QGIS looks for plugins.
"""

import errno
import glob
import os
import tempfile


def _profile_dir():
    try:
        from qgis.core import QgsApplication

        base = QgsApplication.qgisSettingsDirPath()
    except Exception:
        base = None
    # Outside QGIS (tests, scripts) there is no profile to write into.
    return base if isinstance(base, str) and base else tempfile.gettempdir()


def data_dir(*parts):
    """``<profile>/bdc_loader/<parts>``, created if missing."""
    path = os.path.join(_profile_dir(), "bdc_loader", *parts)
    os.makedirs(path, exist_ok=True)
    return path


def usable_folder(path, fallback):
    """``(folder, problem)`` for a folder the user chose.

    ``path`` is created if missing and returned with ``problem`` None. When it
    cannot hold files (a link to a folder that is gone, a file with that name,
    no write permission, a drive that is not mounted), the folder is
    ``<profile>/bdc_loader/<fallback>`` and ``problem`` is the error. The
    setting itself is left as it is, so the chosen folder is used again once it
    is back.
    """
    try:
        os.makedirs(path, exist_ok=True)
        if not os.access(path, os.W_OK):
            raise PermissionError(errno.EACCES, "no write permission", path)
        return path, None
    except OSError as exc:
        return data_dir(fallback), exc


def grids_dir():
    """Folder of the downloaded BDC tile grids."""
    return data_dir("grids")


def temp_files():
    """What the plugin leaves in the system temp folder: the thumbnail cache and
    every cutline file (``bdc_cutline_*``, ``bdc_shape_cutline_*``,
    ``bdc_extent_cutline_*``)."""
    tmp = tempfile.gettempdir()
    thumbs = os.path.join(tmp, "bdc_loader_thumbs")
    found = [thumbs] if os.path.isdir(thumbs) else []
    return found + sorted(glob.glob(os.path.join(tmp, "bdc_*cutline_*")))
