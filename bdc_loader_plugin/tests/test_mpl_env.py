"""matplotlib for the chart: install hints, version pins and what is downloaded (chart/mpl_env.py)."""

import importlib.metadata
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from bdc_loader_plugin.chart import mpl_env


class TestInstallHint(unittest.TestCase):
    def test_each_distribution_gets_its_package_manager(self):
        cases = {
            "ID=arch\n": "sudo pacman -S python-matplotlib",
            "ID=ubuntu\nID_LIKE=debian\n": "sudo apt install python3-matplotlib",
            'ID=linuxmint\nID_LIKE="ubuntu debian"\n': "sudo apt install python3-matplotlib",
            "ID=fedora\n": "sudo dnf install python3-matplotlib",
            'ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n': "sudo zypper install python3-matplotlib",
        }
        for release, hint in cases.items():
            self.assertEqual(mpl_env.system_install_hint("linux", release), hint, release)

    def test_windows_points_to_osgeo4w(self):
        self.assertIn("python3-matplotlib", mpl_env.system_install_hint("win32"))
        self.assertIn("OSGeo4W", mpl_env.system_install_hint("win32"))


class TestPins(unittest.TestCase):
    def test_packages_qgis_has_are_pinned_and_bogus_versions_skipped(self):
        versions = {"numpy": "1.24.2", "pillow": "9.4.0", "kiwisolver": "0.0.0"}

        def version_of(name):
            if name not in versions:
                raise importlib.metadata.PackageNotFoundError(name)
            return versions[name]

        self.assertEqual(mpl_env.shared_pins(version_of), ["numpy==1.24.2", "pillow==9.4.0"])

    def test_only_packages_qgis_lacks_are_downloaded(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        report = os.path.join(folder, "report.json")
        names = [
            ("matplotlib", "3.10.9"),
            ("numpy", "1.24.2"),
            ("Pillow", "9.4.0"),
            ("python_dateutil", "2.8.2"),
            ("six", "1.17.0"),
        ]
        with open(report, "w") as f:
            json.dump({"install": [{"metadata": {"name": n, "version": v}} for n, v in names]}, f)

        wanted = mpl_env.packages_to_download(report, ["numpy==1.24.2", "pillow==9.4.0", "python-dateutil==2.8.2"])

        self.assertEqual(wanted, ["matplotlib==3.10.9", "six==1.17.0"])


class TestPythonExecutable(unittest.TestCase):
    def test_qgis_binary_is_never_run_and_a_matching_python_is_used(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        qgis_bin = os.path.join(folder, "qgis-bin.exe")
        python = os.path.join(folder, "python.exe")
        for path in (qgis_bin, python):
            open(path, "w").close()
        version = f"{sys.version_info[0]}.{sys.version_info[1]}"
        ran = []

        def fake_run(cmd, timeout=None):
            ran.append(cmd[0])
            return type("Out", (), {"returncode": 0, "stdout": version + "\n"})()

        with (
            patch.object(mpl_env.sys, "executable", qgis_bin),
            patch.object(mpl_env.sys, "_base_executable", qgis_bin, create=True),
            patch.object(mpl_env.sys, "exec_prefix", folder),
            patch.object(mpl_env.shutil, "which", return_value=None),
            patch.object(mpl_env, "_run", fake_run),
        ):
            self.assertEqual(mpl_env.python_executable(), python)
        self.assertNotIn(qgis_bin, ran)


class TestPrivateFolder(unittest.TestCase):
    def test_the_plugin_folder_goes_last_on_sys_path(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        saved = list(sys.path)
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), saved))
        with patch.object(mpl_env, "private_dir", return_value=folder):
            mpl_env.add_private_dir()
            mpl_env.add_private_dir()

        self.assertEqual(sys.path[-1], folder)
        self.assertEqual(sys.path.count(folder), 1)
        self.assertEqual(sys.path[: len(saved)], saved)


if __name__ == "__main__":
    unittest.main()
