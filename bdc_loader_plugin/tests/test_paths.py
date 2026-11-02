"""Folders the plugin writes to sit under the QGIS profile, not in the plugin folder (paths.py)."""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from bdc_loader_plugin import paths


class TestDataFolders(unittest.TestCase):
    def setUp(self):
        self.profile = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.profile, True)
        patcher = patch.object(paths, "_profile_dir", return_value=self.profile)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_logs_and_grids_are_under_the_profile(self):
        self.assertEqual(paths.data_dir("logs"), os.path.join(self.profile, "bdc_loader", "logs"))
        self.assertEqual(paths.grids_dir(), os.path.join(self.profile, "bdc_loader", "grids"))
        self.assertTrue(os.path.isdir(os.path.join(self.profile, "bdc_loader", "logs")))

    def test_nothing_is_written_inside_the_plugin_folder(self):
        plugin_dir = os.path.dirname(os.path.abspath(paths.__file__))
        for path in (paths.data_dir("logs"), paths.grids_dir()):
            self.assertFalse(os.path.abspath(path).startswith(plugin_dir + os.sep), path)


class TestUsableFolder(unittest.TestCase):
    """A folder chosen in Settings that cannot hold files falls back to the profile."""

    def setUp(self):
        self.profile = tempfile.mkdtemp()
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.profile, True)
        self.addCleanup(shutil.rmtree, self.root, True)
        patcher = patch.object(paths, "_profile_dir", return_value=self.profile)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fallback = os.path.join(self.profile, "bdc_loader", "downloads")

    def test_a_missing_folder_is_created_and_used(self):
        chosen = os.path.join(self.root, "new", "bdc_downloads")
        self.assertEqual(paths.usable_folder(chosen, "downloads"), (chosen, None))
        self.assertTrue(os.path.isdir(chosen))

    @unittest.skipUnless(hasattr(os, "symlink"), "needs symbolic links")
    def test_a_link_to_a_folder_that_is_gone_falls_back(self):
        chosen = os.path.join(self.root, "bdc_downloads")
        os.symlink(os.path.join(self.root, "unmounted", "bdc_downloads"), chosen)
        folder, problem = paths.usable_folder(chosen, "downloads")
        self.assertEqual(folder, self.fallback)
        self.assertIsInstance(problem, OSError)
        self.assertTrue(os.path.isdir(folder))
        self.assertTrue(os.path.islink(chosen))

    def test_a_file_with_the_folder_name_falls_back(self):
        chosen = os.path.join(self.root, "bdc_downloads")
        with open(chosen, "w") as f:
            f.write("")
        folder, problem = paths.usable_folder(chosen, "downloads")
        self.assertEqual(folder, self.fallback)
        self.assertIsInstance(problem, OSError)

    def test_a_folder_without_write_permission_falls_back(self):
        chosen = os.path.join(self.root, "bdc_downloads")
        os.makedirs(chosen)
        with patch.object(paths.os, "access", return_value=False):
            folder, problem = paths.usable_folder(chosen, "downloads")
        self.assertEqual(folder, self.fallback)
        self.assertIsInstance(problem, PermissionError)


class TestProfileFolder(unittest.TestCase):
    def test_without_a_qgis_profile_path_the_temp_folder_is_used(self):
        """A mocked QgsApplication returns a MagicMock, which must not become a folder name."""
        from unittest.mock import MagicMock

        with patch("qgis.core.QgsApplication.qgisSettingsDirPath", MagicMock(return_value=MagicMock())):
            folder = paths._profile_dir()

        self.assertEqual(folder, tempfile.gettempdir())


def test_temp_files_lists_every_cutline_kind():
    import os
    import tempfile

    from bdc_loader_plugin.paths import temp_files
    from bdc_loader_plugin.ui.settings_storage import StorageTab

    tmp = tempfile.gettempdir()
    made = []
    # mkstemp names are unique, so the files of a running QGIS are not touched.
    for prefix in ("bdc_cutline_", "bdc_shape_cutline_", "bdc_extent_cutline_"):
        fd, path = tempfile.mkstemp(prefix=prefix, suffix=".geojson")
        os.close(fd)
        made.append(path)
    try:
        assert set(made) <= set(temp_files())
        assert set(made) <= set(StorageTab._temp_bdc_paths())
        assert all(os.path.dirname(p) == tmp for p in made)
    finally:
        for path in made:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
