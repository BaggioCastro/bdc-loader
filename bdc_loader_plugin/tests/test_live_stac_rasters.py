"""Live STAC/COG check of collection names, values, rendering ranges, and overviews.

These tests are intentionally excluded from the default suite. Run them with:

    pytest -m integration -s bdc_loader_plugin/tests/test_live_stac_rasters.py

The check reads only reduced 64 x 64 samples. It never downloads a full raster.
"""

import json
import math
import os
import shutil
import subprocess
from types import SimpleNamespace
from urllib.parse import quote, urljoin

import pytest
import requests

from bdc_loader_plugin.core.band_selection import available_bands_for_items, unavailable_band_reasons
from bdc_loader_plugin.core.render_ranges import calculate_render_range
from bdc_loader_plugin.stac.client import STAC_URL, is_supported_image_collection
from bdc_loader_plugin.stac.parsers import extract_bands_from_assets, extract_tile_from_item

pytestmark = pytest.mark.integration

_GDAL_ENV = {
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.TIF,.tiff,.vrt",
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "GDAL_HTTP_MAX_RETRY": "3",
    "GDAL_HTTP_RETRY_DELAY": "1",
}
_BAD_ASSET_PARTS = (
    "mask",
    "qa",
    "qc",
    "quality",
    "totalob",
    "cloud",
    "angle",
    "thumbnail",
    "overview",
    "metadata",
)
_PREFERRED_ASSET_PARTS = (
    "visual",
    "tci",
    "rgb",
    "gamma0_vv",
    "gamma0_vh",
    "red",
    "b04",
    "lst",
    "band",
    "ndvi",
    "nir",
    "swir",
)
_REPORTED_SENTINEL1_DV_ITEM = "S1A_IW_RTCH_1SDV_20260620_065050_0832F0_8892"


def _require_cli(*commands):
    missing = [command for command in commands if shutil.which(command) is None]
    if missing:
        pytest.skip(f"GDAL command(s) unavailable: {', '.join(missing)}")


def _request_json(url, *, params=None, timeout=60):
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _all_supported_collections():
    collections = []
    next_url = f"{STAC_URL}collections"
    while next_url:
        page = _request_json(next_url)
        collections.extend(page.get("collections", []))
        next_url = next(
            (link.get("href") for link in page.get("links", []) if link.get("rel") == "next"),
            None,
        )

    selected = [collection for collection in collections if is_supported_image_collection(collection)]
    requested = {value.strip() for value in os.environ.get("BDC_LIVE_COLLECTIONS", "").split(",") if value.strip()}
    if requested:
        selected = [collection for collection in selected if collection.get("id") in requested]
    return selected


def _first_item(collection_id):
    url = f"{STAC_URL}collections/{quote(collection_id, safe='')}/items"
    page = _request_json(url, params={"limit": 1})
    features = page.get("features", [])
    return features[0] if features else None


def _is_geotiff_asset(asset):
    media_type = str(asset.get("type", "")).lower()
    href = str(asset.get("href", "")).lower().split("?", 1)[0]
    return "image/tiff" in media_type or "application/geotiff" in media_type or href.endswith((".tif", ".tiff"))


def _choose_raster_asset(item):
    candidates = []
    for key, asset in item.get("assets", {}).items():
        if not isinstance(asset, dict) or not asset.get("href") or not _is_geotiff_asset(asset):
            continue

        normalized = key.lower()
        roles = {str(role).lower() for role in asset.get("roles", [])}
        score = 20 if "data" in roles else 0
        score += 30 if "visual" in roles else 0
        for index, preferred in enumerate(_PREFERRED_ASSET_PARTS):
            if preferred in normalized:
                score += 100 - index
                break
        if any(part in normalized for part in _BAD_ASSET_PARTS):
            score -= 200
        candidates.append((score, key, asset))

    if not candidates:
        return None, None
    _, key, asset = max(candidates, key=lambda candidate: (candidate[0], candidate[1]))
    return key, asset


def _run_gdal(command, timeout=120):
    env = os.environ.copy()
    env.update(_GDAL_ENV)
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise AssertionError(f"{' '.join(command[:2])} failed: {detail[-600:]}")
    return result.stdout


def _remote_path(href):
    absolute = urljoin(STAC_URL, href)
    return absolute if absolute.startswith("/vsicurl/") else f"/vsicurl/{absolute}"


def _gdal_info(href):
    output = _run_gdal(["gdalinfo", "-json", _remote_path(href)])
    return json.loads(output)


def _sample_band(href, band_number):
    output = _run_gdal(
        [
            "gdal_translate",
            "-q",
            "-of",
            "XYZ",
            "-outsize",
            "64",
            "64",
            "-r",
            "nearest",
            "-b",
            str(band_number),
            _remote_path(href),
            "/vsistdout/",
        ]
    )
    values = []
    for line in output.splitlines():
        fields = line.rsplit(maxsplit=1)
        if len(fields) != 2:
            continue
        try:
            values.append(float(fields[1]))
        except ValueError:
            continue
    return values


def _usable_values(values, nodata):
    finite = [value for value in values if math.isfinite(value)]
    try:
        nodata_value = float(nodata)
    except (TypeError, ValueError):
        nodata_value = None
    if nodata_value is not None and math.isfinite(nodata_value):
        finite = [value for value in finite if value != nodata_value]
    return finite


def _check_collection(collection):
    collection_id = collection["id"]
    item = _first_item(collection_id)
    if item is None:
        raise AssertionError("collection returned no items")

    item_id = str(item.get("id", "")).strip()
    if not item_id:
        raise AssertionError("item has no id")
    display_name = extract_tile_from_item(SimpleNamespace(id=item_id, properties=item.get("properties", {})))
    if display_name.upper() in {"", "NA", "N/A", "NONE"}:
        raise AssertionError(f"invalid display name: {display_name!r}")

    asset_key, asset = _choose_raster_asset(item)
    if asset is None:
        raise AssertionError("item has no usable GeoTIFF asset")

    # What the server holds, which the plugin handles (no internal overviews:

    # a non-COG warning and a local overview); printed, not failed.

    notes = []
    href = asset["href"]
    info = _gdal_info(href)
    size = info.get("size", [])
    bands = info.get("bands", [])
    if len(size) != 2 or min(size) <= 0:
        raise AssertionError(f"invalid raster size: {size!r}")
    if not bands:
        raise AssertionError("raster reports no bands")

    if max(size) > 2048 and not any(band.get("overviews") for band in bands):
        notes.append(f"large raster {size} has no internal overviews")

    band_count = min(3, len(bands))
    samples = []
    for band_number in range(1, band_count + 1):
        band_info = bands[band_number - 1]
        block = band_info.get("block", [])
        if len(block) != 2 or min(block) <= 0:
            raise AssertionError(f"band {band_number} has invalid block size: {block!r}")

        raw_values = _sample_band(href, band_number)
        values = _usable_values(raw_values, band_info.get("noDataValue"))
        if not values:
            raise AssertionError(f"band {band_number} sample has no finite data")

        render_range = calculate_render_range(values, band_info.get("noDataValue"))
        if render_range is None:
            raise AssertionError(
                f"band {band_number} has no usable display range (min={min(values):g}, max={max(values):g})"
            )

        zero_fraction = sum(value == 0 for value in values) / len(values)
        if zero_fraction >= 0.95 and len(set(values)) > 16:
            notes.append(f"band {band_number} sample is {zero_fraction:.1%} zero")
        samples.append(
            {
                "band": band_number,
                "dtype": band_info.get("type"),
                "min": min(values),
                "max": max(values),
                "range": render_range,
                "zero_fraction": zero_fraction,
                "overviews": len(band_info.get("overviews", [])),
            }
        )

    return {
        "collection": collection_id,
        "item": item_id,
        "display": display_name,
        "asset": asset_key,
        "size": size,
        "samples": samples,
        "notes": notes,
    }


def test_all_available_image_collections_have_consistent_live_rasters():
    _require_cli("gdalinfo", "gdal_translate")
    collections = _all_supported_collections()
    assert collections, "STAC returned no supported image collections"

    failures = []
    reports = []
    for collection in collections:
        collection_id = collection.get("id", "<missing-id>")
        try:
            report = _check_collection(collection)
            reports.append(report)
            ranges = ", ".join(
                f"B{sample['band']}={sample['range'][0]:g}..{sample['range'][1]:g}"
                f"/zero={sample['zero_fraction']:.1%}"
                f"/ovr={sample['overviews']}"
                for sample in report["samples"]
            )
            print(
                f"CHECK OK {collection_id} item={report['item']} "
                f"display={report['display']} asset={report['asset']} "
                f"size={report['size']} {ranges}"
            )
            for note in report["notes"]:
                print(f"CHECK NOTE {collection_id}: {note}")
        except Exception as exc:
            failures.append(f"{collection_id}: {exc}")
            print(f"CHECK FAIL {collection_id}: {exc}")

    noted = sum(1 for report in reports if report["notes"])
    print(f"CHECK SUMMARY checked={len(collections)} ok={len(reports)} with_notes={noted} failed={len(failures)}")
    if failures:
        pytest.fail("Live collection failures:\n" + "\n".join(failures))


def test_sentinel1_vrt_external_overview_is_recognized(tmp_path):
    _require_cli("gdalinfo", "gdalbuildvrt", "gdalwarp")
    collection = next(
        (candidate for candidate in _all_supported_collections() if "sentinel-1" in candidate.get("id", "").lower()),
        None,
    )
    if collection is None:
        pytest.skip("No Sentinel-1 collection is currently available")

    item = _first_item(collection["id"])
    asset_key, asset = _choose_raster_asset(item)
    assert asset is not None, "Sentinel-1 item has no usable GeoTIFF asset"

    vrt_path = tmp_path / "sentinel1.vrt"
    ovr_path = tmp_path / "sentinel1.vrt.ovr"
    _run_gdal(["gdalbuildvrt", "-overwrite", str(vrt_path), _remote_path(asset["href"])])
    _run_gdal(
        [
            "gdalwarp",
            "-q",
            "-overwrite",
            "-of",
            "GTiff",
            "-ts",
            "512",
            "0",
            "-r",
            "nearest",
            "-co",
            "COMPRESS=DEFLATE",
            "-co",
            "TILED=YES",
            str(vrt_path),
            str(ovr_path),
        ],
        timeout=180,
    )

    overview_info = json.loads(_run_gdal(["gdalinfo", "-json", str(ovr_path)]))
    assert overview_info.get("driverShortName") == "GTiff"
    assert max(overview_info["size"]) <= 512
    assert len(overview_info.get("bands", [])) >= 1
    print(f"OVR OK collection={collection['id']} asset={asset_key} size={overview_info['size']} path={ovr_path.name}")


def test_reported_sentinel1_dv_item_has_consistent_bands_and_render_ranges():
    """Collection polarizations must be narrowed to the assets of the reported DV item."""
    _require_cli("gdalinfo", "gdal_translate")
    collection_id = "sentinel-1-rtc-1"
    collection = _request_json(f"{STAC_URL}collections/{collection_id}")
    item = _request_json(f"{STAC_URL}collections/{collection_id}/items/{_REPORTED_SENTINEL1_DV_ITEM}")

    collection_bands = extract_bands_from_assets(collection.get("item_assets", {}))
    selected_item = SimpleNamespace(id=item["id"], assets=item.get("assets", {}))
    available = available_bands_for_items(collection_bands, [selected_item])
    unavailable = unavailable_band_reasons(collection_bands, [selected_item])

    assert "Gamma0_HH" in collection_bands
    assert "Gamma0_HV" in collection_bands
    assert "Gamma0_HH" not in available
    assert "Gamma0_HV" not in available
    assert set(unavailable) == {"Gamma0_HH", "Gamma0_HV"}
    assert unavailable["Gamma0_HH"] == "Not available."
    assert "Gamma0_VH" in available
    assert "Gamma0_VV" in available

    for band_name in ("Gamma0_VH", "Gamma0_VV"):
        asset = item["assets"][band_name]
        info = _gdal_info(asset["href"])
        band_info = info["bands"][0]
        values = _usable_values(_sample_band(asset["href"], 1), band_info.get("noDataValue"))
        render_range = calculate_render_range(values, band_info.get("noDataValue"))

        assert values, f"{band_name} sample has no finite values"
        assert render_range is not None, f"{band_name} sample has no usable render range"
        assert render_range[0] < render_range[1], f"{band_name} render range collapsed to {render_range}"
        assert any(value != 0 for value in values), f"{band_name} sample contains only zeros"
        assert band_info.get("overviews"), f"{band_name} has no internal overviews"
        print(
            f"S1 BAND OK item={item['id']} band={band_name} "
            f"range={render_range[0]:g}..{render_range[1]:g} "
            f"min={min(values):g} max={max(values):g} "
            f"ovr={len(band_info['overviews'])}"
        )
