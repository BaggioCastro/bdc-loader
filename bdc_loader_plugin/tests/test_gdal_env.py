"""The plugin's GDAL settings stay out of other layers and plugins (core/gdal_env.py).

Each check runs real GDAL in a fresh interpreter: GDAL's configuration is
process-wide, and the rest of the suite runs against a fake osgeo.
"""

import json
import os
import subprocess
import sys
import textwrap
import unittest

import pytest

WORKSPACE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _interpreter_has_gdal():
    """Whether a fresh interpreter can import the real binding (the suite's own osgeo is a fake)."""
    probe = subprocess.run([sys.executable, "-c", "from osgeo import gdal"], capture_output=True, timeout=60)
    return probe.returncode == 0


pytestmark = [
    pytest.mark.gdal,
    pytest.mark.skipif(not _interpreter_has_gdal(), reason="real GDAL Python binding not available"),
]

_PRELUDE = """
import json, os, sys, tempfile, threading, warnings
warnings.simplefilter("ignore")
from osgeo import gdal
sys.path.insert(0, {workspace!r})
import importlib.util
spec = importlib.util.spec_from_file_location(
    "gdal_env", os.path.join({workspace!r}, "bdc_loader_plugin", "core", "gdal_env.py"))
env = importlib.util.module_from_spec(spec); spec.loader.exec_module(env)


def local_raster_with_sidecars():
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "plain.tif")
    gdal.GetDriverByName("GTiff").Create(path, 64, 64, 1)
    with open(os.path.join(folder, "plain.tfw"), "w") as f:
        f.write("10\\n0\\n0\\n-10\\n500000\\n7000000\\n")
    ds = gdal.Open(path)
    ds.BuildOverviews("NEAREST", [2])
    ds = None
    return path


def read_back(path):
    ds = gdal.Open(path)
    return [ds.GetGeoTransform()[0], ds.GetRasterBand(1).GetOverviewCount()]
"""


def _run(body):
    code = textwrap.dedent(_PRELUDE).format(workspace=WORKSPACE) + textwrap.dedent(body)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout.strip().splitlines()[-1])


class TestGdalSettingsScope(unittest.TestCase):
    def test_local_files_keep_their_world_file_and_overviews(self):
        result = _run(
            """
            gdal.UseExceptions()
            path = local_raster_with_sidecars()
            with env.plugin_gdal():
                inside = read_back(path)
            print(json.dumps({"inside": inside, "after": read_back(path)}))
            """
        )

        self.assertEqual(result["after"], [499995.0, 1])
        if result.get("inside") is not None:
            self.assertEqual(result["inside"], [499995.0, 1])

    def test_directory_listing_is_off_for_bdc_urls_only(self):
        result = _run(
            """
            env.apply_session_options()
            bdc = "/vsicurl/https://data.inpe.br/bdc/data/x/y_B04.tif"
            other = "/vsicurl/https://example.org/data/y.tif"
            print(json.dumps([gdal.GetPathSpecificOption(p, "GDAL_DISABLE_READDIR_ON_OPEN", None)
                              for p in (bdc, other, "/tmp/y.tif")]))
            """
        )

        self.assertEqual(result, ["EMPTY_DIR", None, None])

    def test_cache_options_apply_inside_the_block_on_its_thread_only(self):
        result = _run(
            """
            seen = {}
            entered, leave = threading.Event(), threading.Event()

            def plugin_worker():
                with env.plugin_gdal({"VSI_CACHE_SIZE": "123"}):
                    seen["worker"] = [gdal.GetConfigOption(k) for k in ("VSI_CACHE", "VSI_CACHE_SIZE")]
                    entered.set(); leave.wait(5)

            t = threading.Thread(target=plugin_worker); t.start(); entered.wait(5)
            seen["other_thread"] = [gdal.GetConfigOption(k) for k in ("VSI_CACHE", "VSI_CACHE_SIZE")]
            leave.set(); t.join()
            seen["retry"] = gdal.GetConfigOption("GDAL_HTTP_MAX_RETRY")
            print(json.dumps(seen))
            """
        )

        self.assertEqual(result["worker"], ["YES", "123"])
        self.assertEqual(result["other_thread"], [None, None])
        self.assertEqual(result["retry"], "3")

    def test_nested_block_keeps_the_outer_options(self):
        result = _run(
            """
            with env.plugin_gdal({"VSI_CACHE_SIZE": "123"}):
                with env.plugin_gdal():
                    inner = gdal.GetConfigOption("VSI_CACHE_SIZE")
                outer = gdal.GetConfigOption("VSI_CACHE_SIZE")
            print(json.dumps([inner, outer, gdal.GetConfigOption("VSI_CACHE_SIZE")]))
            """
        )

        self.assertEqual(result, ["123", "123", None])

    def test_exception_mode_of_other_code_is_left_alone(self):
        result = _run(
            """
            if not hasattr(gdal, "ExceptionMgr"):
                print(json.dumps(None)); sys.exit(0)
            gdal.DontUseExceptions()  # as another plugin may leave it
            with env.plugin_gdal():
                try:
                    gdal.Open("/nonexistent/x.tif"); inside = "none"
                except RuntimeError:
                    inside = "raised"
            print(json.dumps([inside, gdal.GetUseExceptions()]))
            """
        )

        if result is None:
            self.skipTest("GDAL without ExceptionMgr turns exceptions on for the process")
        self.assertEqual(result, ["raised", 0])


if __name__ == "__main__":
    unittest.main()
