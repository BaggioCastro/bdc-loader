"""The plugin leaves the Python process as other plugins expect it (imports, sys.path)."""

import importlib
import os
import subprocess
import sys
import textwrap
import unittest

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE = os.path.dirname(PLUGIN_DIR)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _run(code):
    """Run ``code`` in a fresh interpreter that sees the workspace, return its stdout lines."""
    env = {**os.environ, "PYTHONPATH": WORKSPACE}
    out = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)], env=env, capture_output=True, text=True, timeout=60
    )
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return out.stdout.split()


class TestVendoredPackages(unittest.TestCase):
    def test_vendored_pystac_is_a_subpackage_and_sys_path_is_untouched(self):
        lines = _run(
            """
            import sys
            before = list(sys.path)
            from bdc_loader_plugin.lib import pystac, pystac_client
            print(pystac.__name__, pystac_client.__name__, pystac.__version__)
            print(sys.path == before, "pystac" in sys.modules, "pystac_client" in sys.modules)
            """
        )

        self.assertEqual(lines[:3], ["bdc_loader_plugin.lib.pystac", "bdc_loader_plugin.lib.pystac_client", "1.3.0"])
        self.assertEqual(lines[3:], ["True", "False", "False"])

    def test_another_pystac_already_loaded_is_neither_used_nor_replaced(self):
        lines = _run(
            """
            import sys, types
            other = types.ModuleType("pystac")
            other.__version__ = "99.0-other-plugin"
            sys.modules["pystac"] = other
            from bdc_loader_plugin.lib.pystac_client import Client
            from bdc_loader_plugin.lib import pystac
            print(sys.modules["pystac"] is other, pystac.__version__, Client.__module__)
            """
        )

        self.assertEqual(lines, ["True", "1.3.0", "bdc_loader_plugin.lib.pystac_client.client"])

    def test_vendored_imports_are_all_relative(self):
        sys.path.insert(0, WORKSPACE)
        try:
            vendor_imports = importlib.import_module("vendor_imports")
        finally:
            sys.path.remove(WORKSPACE)
        pending = [p for p in vendor_imports.vendored_files() if vendor_imports.rewrite_file(p) != _read(p)]

        self.assertEqual(pending, [])

    def test_plugin_package_does_not_import_by_bare_module_name(self):
        """``from timeseries_panel import`` would load any other plugin's module of that name."""
        import ast

        own = set()
        for root, dirs, files in os.walk(PLUGIN_DIR):
            dirs[:] = [d for d in dirs if d not in ("lib", "tests", "__pycache__")]
            own.update(f[:-3] for f in files if f.endswith(".py"))
            own.update(dirs)
        offenders = []
        for root, dirs, files in os.walk(PLUGIN_DIR):
            dirs[:] = [d for d in dirs if d not in ("lib", "tests", "__pycache__")]
            for f in files:
                if not f.endswith(".py"):
                    continue
                path = os.path.join(root, f)
                for node in ast.walk(ast.parse(open(path, encoding="utf-8").read())):
                    names = []
                    if isinstance(node, ast.Import):
                        names = [a.name for a in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                        names = [node.module]
                    offenders += [
                        f"{os.path.relpath(path, PLUGIN_DIR)}:{node.lineno} {n}"
                        for n in names
                        if n.split(".")[0] in own
                    ]

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
