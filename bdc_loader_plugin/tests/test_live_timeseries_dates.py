"""Time series of the plugin against the raw answers of the BDC servers (needs the network and real GDAL).

For one point of the tutorial, S2-16D-2, August and September 2022: the WTSS
series has the dates and values of the raw WTSS timeline without its missing
values, the series read from the COGs has the dates of the raw STAC items that
cover the point, and the two agree on every date they share. Run with
``pytest -m integration bdc_loader_plugin/tests/test_live_timeseries_dates.py``.
"""

import json
import os
import subprocess
import sys
import textwrap

import pytest

WORKSPACE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytestmark = pytest.mark.integration

_SCRIPT = """
import json, sys, warnings
warnings.simplefilter("ignore")
from osgeo import gdal, ogr, osr
real = {name: sys.modules[name] for name in ("osgeo", "osgeo.gdal", "osgeo.ogr", "osgeo.osr")}
sys.path.insert(0, @WORKSPACE@)
from bdc_loader_plugin.tests.qgis_mock import install_mocks
install_mocks()
sys.modules.update(real)  # the plugin reads the COGs with the real GDAL
import requests
from bdc_loader_plugin.core.ts_extraction import TSExtractionEngine
from bdc_loader_plugin.extraction.point_series import assign_items_to_points, extract_points_timeseries
from bdc_loader_plugin.extraction.wtss_extractor import _DESCRIBE_URL, _TS_URL, extract_wtss_multi_points
from bdc_loader_plugin.stac.client import STAC_URL, open_stac_client
from bdc_loader_plugin.vendored import ensure_pystac_client

CID, BANDS, START, END = "S2-16D-2", ["B04", "B08", "NDVI"], "2022-08-01", "2022-09-30"
LON, LAT = -45.11375, -13.82825
missing = {a["name"]: a.get("missing_value") for a in requests.get(_DESCRIBE_URL, params={"name": CID}, timeout=30).json()["attributes"]}
raw = requests.get(_TS_URL, params={"coverage": CID, "attributes": ",".join(BANDS), "latitude": LAT, "longitude": LON,
                                     "start_date": START, "end_date": END}, timeout=60).json()["result"]
timeline = [t[:10] for t in raw["timeline"]]
stac = requests.post(STAC_URL + "search", json={"collections": [CID], "intersects": {"type": "Point", "coordinates": [LON, LAT]},
                     "datetime": START + "T00:00:00Z/" + END + "T23:59:59Z", "limit": 100}, timeout=60).json()["features"]
wtss = extract_wtss_multi_points(CID, [(LON, LAT, "P", BANDS)], START, END)[0]
engine = TSExtractionEngine.__new__(TSExtractionEngine)
client = open_stac_client(ensure_pystac_client(), STAC_URL)
engine._get_stac_client = lambda: client
items = engine._search_points_items(CID, [(LON, LAT)], START, END)
cog, failed = extract_points_timeseries(assign_items_to_points(items, [(LON, LAT)]), [(LON, LAT)], BANDS)
out = {"timeline": timeline, "stac_dates": sorted({f["properties"]["datetime"][:10] for f in stac}), "failed": failed, "bands": {}}
for attr in raw["attributes"]:
    band = attr["attribute"]
    out["bands"][band] = {
        "server": {d: float(v) for d, v in zip(timeline, attr["values"]) if v is not None and v != -9999 and v != missing.get(band)},
        "wtss": {dt.strftime("%Y-%m-%d"): v for dt, v in wtss.get(band, [])},
        "cog": {dt.strftime("%Y-%m-%d"): v for dt, v in cog.get(0, {}).get(band, [])},
    }
print(json.dumps(out))
"""


@pytest.fixture(scope="module")
def series():
    probe = subprocess.run([sys.executable, "-c", "from osgeo import gdal"], capture_output=True, timeout=60)
    if probe.returncode != 0:
        pytest.skip("real GDAL Python binding not available")
    code = textwrap.dedent(_SCRIPT).replace("@WORKSPACE@", repr(WORKSPACE))
    run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=600)
    assert run.returncode == 0, run.stderr[-2000:]
    return json.loads(run.stdout.strip().splitlines()[-1])


def test_wtss_series_has_the_dates_and_values_of_the_server(series):
    for band, data in series["bands"].items():
        assert data["wtss"] == data["server"], band


def test_cog_series_has_the_dates_of_the_stac_items(series):
    assert series["failed"] == 0
    for band, data in series["bands"].items():
        assert set(data["cog"]) <= set(series["stac_dates"]), band
        assert data["cog"], band


def test_wtss_and_cog_agree_on_the_dates_they_share(series):
    assert series["timeline"] == series["stac_dates"]
    for band, data in series["bands"].items():
        common = set(data["wtss"]) & set(data["cog"])
        assert common, band
        assert {d: data["wtss"][d] for d in common} == {d: data["cog"][d] for d in common}, band
