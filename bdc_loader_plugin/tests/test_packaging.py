#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_packaging.py — Tests for package_plugin.py, the release-ZIP builder.

Guards that the distributed package carries the runtime plugin and nothing else:
no unit suite, no caches, no per-install runtime logs and no hidden files.
"""

import os
import unittest
import zipfile

import check_package
import package_plugin


class TestShouldInclude(unittest.TestCase):
    """The path-level exclusion predicate."""

    def test_excludes_test_suite(self):
        self.assertFalse(package_plugin.should_include("tests/test_download.py"))

    def test_excludes_pycache_anywhere(self):
        self.assertFalse(package_plugin.should_include("core/__pycache__/download.cpython-313.pyc"))

    def test_excludes_compiled_python(self):
        self.assertFalse(package_plugin.should_include("core/download.pyc"))

    def test_excludes_runtime_logs(self):
        self.assertFalse(package_plugin.should_include("logs/bdc_loader.jsonl"))
        self.assertFalse(package_plugin.should_include("logs/anything.jsonl"))

    def test_excludes_gitignore(self):
        self.assertFalse(package_plugin.should_include(".gitignore"))

    def test_excludes_hidden_files_and_folders(self):
        for excluded in (
            ".DS_Store",
            "nested/.coverage",
            ".vscode/settings.json",
            ".idea/workspace.xml",
            "nested/.hidden/config.json",
        ):
            self.assertFalse(package_plugin.should_include(excluded), msg=excluded)

    def test_excludes_files_the_plugin_never_reads(self):
        self.assertFalse(package_plugin.should_include("VERSION"))
        self.assertFalse(package_plugin.should_include("lib/pystac_client/cli.py"))
        self.assertTrue(package_plugin.should_include("lib/pystac_client/client.py"))

    def test_includes_source_and_metadata(self):
        for keep in ("core/download.py", "metadata.txt", "__init__.py", "README.md", "lib/pystac/item.py"):
            self.assertTrue(package_plugin.should_include(keep), msg=keep)


class TestIterPackageFiles(unittest.TestCase):
    """The full walk over the real plugin tree."""

    def setUp(self):
        self.arcnames = [arc for _abs, arc in package_plugin.iter_package_files()]

    def test_every_entry_is_under_the_plugin_folder(self):
        self.assertTrue(self.arcnames)
        for arc in self.arcnames:
            self.assertTrue(arc.startswith("bdc_loader_plugin/"), msg=arc)

    def test_essential_files_present(self):
        for essential in (
            "bdc_loader_plugin/metadata.txt",
            "bdc_loader_plugin/__init__.py",
            "bdc_loader_plugin/LICENSE",
            "bdc_loader_plugin/core/download.py",
            "bdc_loader_plugin/core/vrt_builder.py",
        ):
            self.assertIn(essential, self.arcnames)

    def test_no_dev_or_runtime_artifacts(self):
        for arc in self.arcnames:
            self.assertNotIn("/tests/", "/" + arc)
            self.assertNotIn("__pycache__", arc)
            self.assertNotIn("/logs/", "/" + arc)
            self.assertFalse(any(part.startswith(".") for part in arc.split("/")), msg=arc)
            self.assertFalse(arc.endswith(".pyc"), msg=arc)
            self.assertFalse(arc.endswith(".jsonl"), msg=arc)


class TestCleanMetadata(unittest.TestCase):
    """The archive-only metadata rewrite preserves unrelated INI content."""

    def _clean(self, content, version="9.9.9"):
        import tempfile

        with tempfile.TemporaryDirectory(prefix="bdc_metadata_test_") as work:
            metadata_path = os.path.join(work, "metadata.txt")
            with open(metadata_path, "w", encoding="utf-8") as f:
                f.write(content)
            cleaned = package_plugin._get_clean_metadata(metadata_path, version)
            with open(metadata_path, encoding="utf-8") as f:
                source_after = f.read()
        return cleaned, source_after

    def test_replaces_only_changelog_continuation_lines(self):
        source = (
            "[general]\n"
            "name=BDC Loader — test\n"
            "changelog=old same-line note\n"
            "    1.0.0:\n"
            "    - old note GH-123\n"
            "\n"
            "    - old note after an empty line\n"
            "experimental=False\n"
            "deprecated=False\n"
            "\n"
            "[extra]\n"
            "preserve=yes\n"
        )

        cleaned, source_after = self._clean(source)

        self.assertEqual(source_after, source)
        self.assertEqual(cleaned.count("changelog="), 1)
        self.assertIn("    9.9.9:", cleaned)
        self.assertNotIn("GH-123", cleaned)
        self.assertNotIn("old note after an empty line", cleaned)
        self.assertIn("name=BDC Loader — test", cleaned)
        self.assertIn("experimental=False", cleaned)
        self.assertIn("deprecated=False", cleaned)
        self.assertIn("[extra]\npreserve=yes", cleaned)

    def test_inserts_missing_changelog_in_general_section(self):
        source = "[general]\nname=x\n\n[extra]\npreserve=yes\n"

        cleaned, source_after = self._clean(source)

        self.assertEqual(source_after, source)
        self.assertLess(cleaned.index("changelog="), cleaned.index("[extra]"))
        self.assertIn("[extra]\npreserve=yes", cleaned)

    def test_rejects_metadata_without_general_section(self):
        with self.assertRaisesRegex(ValueError, r"\[general\]"):
            self._clean("[extra]\nname=x\n")


class TestPublicChangelog(unittest.TestCase):
    """The ZIP's changelog comes from docs/CHANGELOG.md, without ticket codes or file names."""

    SAMPLE = (
        "# Changelog\n\n## [Unreleased]\n\n### Added\n- Draft feature: not released yet.\n\n"
        "## [2.0.0] — 2026-01-01\n\n### Added\n- Offline mode (`core/local_catalog.py`): Search lists the\n"
        "  downloaded images. More detail here.\n- Faster loads (GH-12).\n\n### Fixed\n- A fix that stays out.\n"
    )

    def _changelog(self, version):
        import tempfile

        with tempfile.TemporaryDirectory(prefix="bdc_changelog_test_") as work:
            path = os.path.join(work, "CHANGELOG.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.SAMPLE)
            return package_plugin.public_changelog(version, path)

    def test_the_version_section_gives_the_added_entries(self):
        block = self._changelog("2.0.0")
        self.assertEqual(
            block.splitlines(),
            [
                "changelog=",
                "    2.0.0:",
                "    - Offline mode: Search lists the downloaded images.",
                "    - Faster loads.",
                "    - Fixes and other changes: docs/CHANGELOG.md in the repository.",
            ],
        )

    def test_a_version_without_a_section_uses_unreleased(self):
        self.assertIn("    - Draft feature: not released yet.", self._changelog("3.0.0"))

    def test_the_real_changelog_has_no_fixed_initial_release_text(self):
        block = package_plugin.public_changelog(package_plugin.read_version())
        self.assertNotIn("Initial release", block)
        self.assertNotRegex(block, r"[A-Z]{2,5}-\d+|\.py\b")


class TestBuildZip(unittest.TestCase):
    """build_zip on a synthetic tree exercises the real ZIP writer + filter."""

    def _make_plugin_tree(self, root):
        layout = {
            "__init__.py": b"# plugin",
            "metadata.txt": b"[general]\nname=x\nchangelog=\n    1.0.0:\n    - old notes\n",
            "core/download.py": b"code",
            "core/__pycache__/download.cpython-313.pyc": b"\x00",
            "tests/test_x.py": b"assert True",
            "logs/bdc_loader.jsonl": b'{"msg":"x"}\n',
            ".vscode/settings.json": b"{}",
            "nested/.hidden/notes.txt": b"notes",
            ".gitignore": b"__pycache__/\n",
        }
        for rel, data in layout.items():
            path = os.path.join(root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)

    def test_zip_contains_only_shipped_files(self):
        import shutil
        import tempfile

        work = tempfile.mkdtemp(prefix="bdc_pkg_test_")
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        plugin_dir = os.path.join(work, "bdc_loader_plugin")
        os.makedirs(plugin_dir)
        self._make_plugin_tree(plugin_dir)

        out_dir = os.path.join(work, "out")
        os.makedirs(out_dir)
        zip_path = package_plugin.build_zip(output_dir=out_dir, plugin_dir=plugin_dir, version="9.9.9")

        self.assertTrue(zip_path.endswith("bdc_loader_plugin_v9.9.9.zip"))
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            meta = zf.read("bdc_loader_plugin/metadata.txt").decode("utf-8")
            license_content = zf.read("bdc_loader_plugin/LICENSE")

        self.assertIn("bdc_loader_plugin/__init__.py", names)
        self.assertIn("bdc_loader_plugin/metadata.txt", names)
        self.assertIn("bdc_loader_plugin/LICENSE", names)
        self.assertIn("bdc_loader_plugin/core/download.py", names)
        self.assertIn("9.9.9:", meta)
        with open(package_plugin.LICENSE_FILE, "rb") as f:
            self.assertEqual(license_content, f.read())
        # Excluded artifacts must not appear.
        for name in names:
            self.assertNotIn("__pycache__", name)
            self.assertNotIn("/tests/", "/" + name)
            self.assertNotIn("/logs/", "/" + name)
            self.assertFalse(any(part.startswith(".") for part in name.split("/")), msg=name)
            self.assertFalse(name.endswith(".pyc"), msg=name)
            self.assertFalse(name.endswith(".jsonl"), msg=name)
            self.assertFalse(name.endswith(".gitignore"), msg=name)


class TestCheckPackage(unittest.TestCase):
    """check_package.py: the plugins.qgis.org rules on the release ZIP."""

    def _zip(self, files):
        import shutil
        import tempfile

        work = tempfile.mkdtemp(prefix="bdc_check_test_")
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        path = os.path.join(work, "plugin.zip")
        with zipfile.ZipFile(path, "w") as zf:
            for name, data in files.items():
                zf.writestr(name, data)
        return path

    def test_the_release_zip_passes(self):
        import shutil
        import tempfile

        work = tempfile.mkdtemp(prefix="bdc_check_real_")
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        self.assertEqual(check_package.check_zip(package_plugin.build_zip(output_dir=work)), [])

    def test_missing_files_fields_and_binaries_are_reported(self):
        path = self._zip(
            {
                "9plugin/__init__.py": "",
                "9plugin/metadata.txt": "[general]\nname=x\nversion=1.0\nhomepage=http://example.org\n",
                "9plugin/lib/fast.so": "\x00",
                "9plugin/.hidden": "",
            }
        )
        problems = "\n".join(check_package.check_zip(path))
        for expected in (
            "folder name '9plugin'",
            "LICENSE is missing",
            "lacks repository",
            "lacks tracker",
            "homepage is not an https link",
            "version must be MAJOR.MINOR.PATCH",
            "binary file: 9plugin/lib/fast.so",
            "hidden or cache file: 9plugin/.hidden",
        ):
            self.assertIn(expected, problems)

    def test_files_outside_one_folder_are_reported(self):
        path = self._zip({"metadata.txt": "", "plugin/__init__.py": ""})
        self.assertIn("one top-level folder", check_package.check_zip(path)[0])


if __name__ == "__main__":
    unittest.main()
