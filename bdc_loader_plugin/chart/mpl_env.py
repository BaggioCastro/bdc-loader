"""matplotlib for the time series chart: the one QGIS has, or a copy the plugin installs for itself.

The plugin's copy lives in ``<profile>/bdc_loader/python`` and that folder is
added at the end of ``sys.path``, so any package QGIS or another plugin
provides is found first; the folder only supplies what is missing. The copy is
installed with pip (the one QGIS has when it is recent enough, else PyPA's
single-file ``pip.pyz``), limited to the matplotlib versions the chart was
tested with, and pinned to the numpy, Pillow and other packages QGIS already
has, which are left out of the folder.
"""

import importlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import tempfile

from ..net import TRANSFER_S
from ..paths import data_dir

# Versions the chart was exercised with (line and RGB plots, axis ranges, date
# double-click, PNG export) in QGIS 3.22 to 4.2.
SUPPORTED_SPEC = ">=3.5,<3.12"
MIN_VERSION = (3, 5)

PIP_PYZ_URL = "https://bootstrap.pypa.io/pip/pip.pyz"
# --dry-run --report needs pip 22.2.
_MIN_PIP = (22, 2)
# Packages matplotlib depends on that QGIS usually has; when present they are
# pinned to the installed version and not downloaded again.
_SHARED = (
    "numpy",
    "pillow",
    "python-dateutil",
    "packaging",
    "six",
    "pyparsing",
    "cycler",
    "kiwisolver",
    "fonttools",
    "contourpy",
)


def private_dir():
    return os.path.join(data_dir(), "python")


def add_private_dir():
    """Put the plugin's package folder at the end of sys.path, when it exists."""
    folder = private_dir()
    if os.path.isdir(folder) and folder not in sys.path:
        sys.path.append(folder)
        importlib.invalidate_caches()
    return folder


def _version_tuple(text):
    parts = []
    for piece in str(text).split(".")[:2]:
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def load_matplotlib():
    """``(FigureCanvas, Figure)`` or None when no usable matplotlib can be imported."""
    add_private_dir()
    try:
        import matplotlib
    except ImportError:
        return None
    if _version_tuple(matplotlib.__version__) < MIN_VERSION:
        return None
    try:
        # backend_qtagg follows the Qt binding QGIS already loaded (Qt5 or Qt6);
        # matplotlib before 3.5 only has backend_qt5agg.
        try:
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as canvas
        except ImportError:
            from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as canvas
        from matplotlib.figure import Figure
    except ImportError:
        return None
    return canvas, Figure


def status():
    """``("ok" | "missing" | "too_old", version or None)`` for the matplotlib Python would import."""
    add_private_dir()
    try:
        version = importlib.metadata.version("matplotlib")
    except importlib.metadata.PackageNotFoundError:
        return "missing", None
    return ("too_old" if _version_tuple(version) < MIN_VERSION else "ok"), version


def system_install_hint(platform=None, os_release=None):
    """The usual way to install matplotlib for QGIS on this system, as one line of text."""
    platform = platform or sys.platform
    if platform == "win32":
        return "OSGeo4W Setup: Advanced Install, then select the package python3-matplotlib."
    if platform == "darwin":
        return "The QGIS installer for macOS includes matplotlib; reinstall QGIS from qgis.org."
    if os_release is None:
        try:
            with open("/etc/os-release", encoding="utf-8") as f:
                os_release = f.read()
        except OSError:
            os_release = ""
    ids = set()
    for line in os_release.splitlines():
        key, _, value = line.partition("=")
        if key in ("ID", "ID_LIKE"):
            ids.update(value.strip().strip('"').split())
    if "arch" in ids:
        return "sudo pacman -S python-matplotlib"
    if ids & {"debian", "ubuntu"}:
        return "sudo apt install python3-matplotlib"
    if ids & {"fedora", "rhel", "centos"}:
        return "sudo dnf install python3-matplotlib"
    if ids & {"opensuse", "suse", "sles"}:
        return "sudo zypper install python3-matplotlib"
    return "Install the python3-matplotlib package of your distribution."


def python_executable():
    """The Python interpreter QGIS runs on, for pip. Inside QGIS on Windows
    ``sys.executable`` can be qgis-bin.exe, so candidates are checked by running them."""
    version = f"{sys.version_info[0]}.{sys.version_info[1]}"
    candidates = [sys.executable, getattr(sys, "_base_executable", None)]
    for folder in (sys.exec_prefix, os.path.join(sys.exec_prefix, "bin")):
        for name in ("python.exe", "python3.exe", f"python{version}", "python3", "python"):
            candidates.append(os.path.join(folder, name))
    candidates.append(shutil.which(f"python{version}"))
    seen = set()
    for exe in candidates:
        # Only interpreters: running qgis-bin.exe with -c would start QGIS.
        if not exe or exe in seen or not os.path.isfile(exe):
            continue
        if not os.path.basename(exe).lower().startswith("python"):
            continue
        seen.add(exe)
        try:
            out = _run([exe, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"], timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue
        if out.returncode == 0 and out.stdout.strip() == version:
            return exe
    return None


def _child_env():
    """QGIS's environment without the variables that would point pip at QGIS's own paths."""
    return {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONSTARTUP", "PIP_TARGET", "PIP_PREFIX")}


# No console window on Windows.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run(cmd, timeout=None):
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, env=_child_env(), creationflags=_NO_WINDOW
    )


def shared_pins(version_of=None):
    """``name==version`` for the matplotlib dependencies QGIS already has.

    A package whose metadata carries no real version (Debian ships
    python3-kiwisolver as 0.0.0) is left unpinned rather than asking pip for
    a release that does not exist.
    """
    version_of = version_of or importlib.metadata.version
    pins = []
    for name in _SHARED:
        try:
            version = version_of(name)
        except importlib.metadata.PackageNotFoundError:
            continue
        if _version_tuple(version) > (0, 0):
            pins.append(f"{name}=={version}")
    return pins


class Installer:
    """Installs matplotlib into ``private_dir()``; ``cancel()`` stops it from another thread."""

    def __init__(self, progress=None):
        self._progress = progress or (lambda text: None)
        self._process = None
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        if self._process is not None:
            try:
                self._process.terminate()
            except OSError:
                pass

    def _step(self, cmd):
        if self._cancelled:
            raise InstallCancelled()
        self._process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=_child_env(), creationflags=_NO_WINDOW
        )
        out, err = self._process.communicate()
        code, self._process = self._process.returncode, None
        if self._cancelled:
            raise InstallCancelled()
        if code != 0:
            raise InstallError((err or out).strip().splitlines()[-1:] or [f"exit status {code}"])
        return out

    def _pip(self, python):
        """The pip command: QGIS's own when recent enough, else pip.pyz (downloaded once)."""
        out = _run([python, "-m", "pip", "--version"], timeout=60)
        if out.returncode == 0:
            version = out.stdout.split()[1] if len(out.stdout.split()) > 1 else "0"
            if _version_tuple(version) >= _MIN_PIP:
                return [python, "-m", "pip"]
        pyz = os.path.join(data_dir(), "pip.pyz")
        if not os.path.isfile(pyz):
            self._progress("Downloading pip...")
            import requests

            response = requests.get(PIP_PYZ_URL, timeout=TRANSFER_S)
            response.raise_for_status()
            with open(pyz + ".part", "wb") as f:
                f.write(response.content)
            os.replace(pyz + ".part", pyz)
        return [python, pyz]

    def run(self):
        """Install; returns the matplotlib version installed. Raises InstallError or InstallCancelled."""
        python = python_executable()
        if python is None:
            raise InstallError(["The Python interpreter of QGIS was not found."])
        pip = self._pip(python)
        common = ["--disable-pip-version-check", "--no-input", "--only-binary=:all:"]
        work = tempfile.mkdtemp(prefix="bdc_mpl_")
        try:
            pins = shared_pins()
            constraints = os.path.join(work, "constraints.txt")
            with open(constraints, "w", encoding="utf-8") as f:
                f.write("\n".join(pins) + "\n")
            self._progress("Finding a compatible matplotlib...")
            report = os.path.join(work, "report.json")
            self._step(
                pip
                + [
                    "install",
                    *common,
                    "--dry-run",
                    "--ignore-installed",
                    "--report",
                    report,
                    "-c",
                    constraints,
                    f"matplotlib{SUPPORTED_SPEC}",
                ]
            )
            wanted = packages_to_download(report, pins)
            self._progress("Downloading matplotlib...")
            staging = os.path.join(work, "python")
            self._step(pip + ["install", *common, "--no-deps", "--target", staging, *wanted])
            target = private_dir()
            if os.path.isdir(target):
                shutil.rmtree(target, ignore_errors=True)
            shutil.move(staging, target)
            return next((w.split("==")[1] for w in wanted if w.lower().startswith("matplotlib==")), "")
        finally:
            shutil.rmtree(work, ignore_errors=True)


def packages_to_download(report_path, pins):
    """``name==version`` from a pip install report, minus what QGIS already has."""
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)
    have = {pin.split("==")[0].lower() for pin in pins}
    wanted = []
    for entry in report.get("install", []):
        meta = entry.get("metadata", {})
        name, version = meta.get("name", ""), meta.get("version", "")
        if name and name.lower().replace("_", "-") not in have:
            wanted.append(f"{name}=={version}")
    return wanted


class InstallError(Exception):
    def __init__(self, lines):
        super().__init__(" ".join(lines))


class InstallCancelled(Exception):
    pass
