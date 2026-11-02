"""Per-band missing values declared by WTSS describe_coverage."""

from unittest.mock import MagicMock, patch

import pytest

import bdc_loader_plugin.extraction.wtss_extractor as wtss

# Shape of GET /v4/describe_coverage?name=LANDSAT-16D-1 (trimmed).
_DESCRIBE = {
    "attributes": [
        {"name": "red", "datatype": "uint16", "missing_value": 0.0, "valid_range": {"min": 0.0, "max": 10000.0}},
        {
            "name": "NDVI",
            "datatype": "int16",
            "missing_value": -9999.0,
            "valid_range": {"min": -10000.0, "max": 10000.0},
        },
        {"name": "CLEAROB", "datatype": "uint8"},
    ]
}


@pytest.fixture(autouse=True)
def _empty_cache():
    wtss._attr_cache.clear()
    yield
    wtss._attr_cache.clear()


def _response(status, payload=None):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload or {}
    return resp


def test_band_missing_value_is_dropped():
    data = {
        "result": {
            "timeline": ["2000-01-01", "2000-01-17", "2000-02-02"],
            "attributes": [{"attribute": "red", "values": [1175, 0, 1039]}],
        }
    }

    result = wtss._parse_get_response(data, ["red"], {"red": 0.0})

    assert [v for _, v in result["red"]] == [1175.0, 1039.0]


def test_zero_is_kept_when_the_band_declares_another_missing_value():
    data = {
        "result": {
            "timeline": ["2000-01-01", "2000-01-17"],
            "attributes": [{"attribute": "NDVI", "values": [0, -9999]}],
        }
    }

    result = wtss._parse_get_response(data, ["NDVI"], {"NDVI": -9999.0})

    assert [v for _, v in result["NDVI"]] == [0.0]


def test_describe_coverage_is_parsed_and_cached():
    with patch.object(wtss.requests, "get", return_value=_response(200, _DESCRIBE)) as get:
        first = wtss._coverage_missing_values("LANDSAT-16D-1")
        second = wtss._coverage_missing_values("LANDSAT-16D-1")

    assert first == {"red": 0.0, "NDVI": -9999.0}
    assert second == first
    get.assert_called_once_with(wtss._DESCRIBE_URL, params={"name": "LANDSAT-16D-1"}, timeout=15)


def test_failed_describe_is_not_cached():
    with patch.object(wtss.requests, "get", side_effect=[_response(503), _response(200, _DESCRIBE)]) as get:
        assert wtss._coverage_missing_values("LANDSAT-16D-1") == {}
        assert wtss._coverage_missing_values("LANDSAT-16D-1") == {"red": 0.0, "NDVI": -9999.0}

    assert get.call_count == 2


def test_single_point_extraction_applies_declared_missing_values():
    ts = {
        "result": {
            "timeline": ["2000-01-01", "2000-01-17"],
            "attributes": [{"attribute": "red", "values": [1175, 0]}],
        }
    }
    with (
        patch.object(wtss, "_wtss_get", return_value=ts),
        patch.object(wtss, "_coverage_missing_values", return_value={"red": 0.0}) as missing,
    ):
        result = wtss._extract_wtss_single_point("LANDSAT-16D-1", ["red"], -15.78, -47.93, "2000-01-01", "2000-12-31")

    missing.assert_called_once_with("LANDSAT-16D-1")
    assert [v for _, v in result["red"]] == [1175.0]


def test_valid_ranges_come_from_describe_coverage():
    with patch.object(wtss.requests, "get", return_value=_response(200, _DESCRIBE)):
        ranges = wtss.coverage_valid_ranges("LANDSAT-16D-1")

    assert ranges == {"red": (0.0, 10000.0), "NDVI": (-10000.0, 10000.0)}
