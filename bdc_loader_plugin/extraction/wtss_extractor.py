"""WTSS v4 HTTP client — direct requests, no package dependency.

API v4 endpoints used:
  GET /v4/time_series
  Params:
    coverage    = collection name  (e.g. S2-16D-2)
    attributes  = comma-separated bands  (e.g. NDVI,B04,B08)
    latitude    = decimal latitude (WGS84)
    longitude   = decimal longitude (WGS84)
    start_date  = YYYY-MM-DD
    end_date    = YYYY-MM-DD
  Response:
    {
      "result": {
        "attributes": [{"attribute": "NDVI", "values": [5759, 6258, ...]}, ...],
        "timeline":   ["2025-01-01", "2025-01-17", ...]
      }
    }

  GET /v4/describe_coverage?name=<collection>  → lists available bands

VALUES: raw integers — same as GDAL reads from COGs (no scale factor).
        e.g. NDVI S2 = 6258 (= 0.6258 × 10 000)

The server answers POST /{collection}/timeseries with HTTP 500, so the
client always sends GET /time_series with the parameters above.
"""

import threading
import time as _time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Optional

import requests

from ..logger import error as _log_error
from ..logger import info as _log_info
from ..logger import warning as _log_warning
from ..net import METADATA_S, PING_S, WTSS_SERIES_S

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WTSS_BASE = "https://data.inpe.br/bdc/wtss"
WTSS_V4 = f"{WTSS_BASE}/v4"
_TS_URL = f"{WTSS_V4}/time_series"
_DESCRIBE_URL = f"{WTSS_V4}/describe_coverage"

# Collections whose time series the client reads with GET /time_series.
WTSS_COVERAGES = {
    "S2-16D-2",
    "LANDSAT-16D-1",
    "mod13q1-6.1",
    "myd13q1-6.1",
    "mod11a2-6.1",
    "myd11a2-6.1",
    "CBERS4-WFI-16D-2",
    "CBERS-WFI-8D-1",
    "CBERS4-MUX-2M-1",
}

# Known bands per collection, used to validate requests before sending them to the server.
WTSS_BANDS: dict[str, set] = {
    "S2-16D-2": {
        "CLEAROB",
        "TOTALOB",
        "PROVENANCE",
        "SCL",
        "B01",
        "B02",
        "B03",
        "B04",
        "B05",
        "B06",
        "B07",
        "B08",
        "B8A",
        "B09",
        "B11",
        "B12",
        "EVI",
        "NDVI",
        "NBR",
    },
    "LANDSAT-16D-1": {
        "NDVI",
        "EVI",
        "CLEAROB",
        "TOTALOB",
        "PROVENANCE",
        "DATASOURCE",
        "coastal",
        "blue",
        "green",
        "red",
        "nir08",
        "swir16",
        "swir22",
        "qa_pixel",
    },
    "mod13q1-6.1": {
        "NDVI",
        "EVI",
        "VI_Quality",
        "composite_day_of_the_year",
        "pixel_reliability",
        "blue_reflectance",
        "red_reflectance",
        "NIR_reflectance",
        "MIR_reflectance",
        "view_zenith_angle",
        "sun_zenith_angle",
        "relative_azimuth_angle",
    },
    "myd13q1-6.1": {
        "NDVI",
        "EVI",
        "VI_Quality",
        "composite_day_of_the_year",
        "pixel_reliability",
        "blue_reflectance",
        "red_reflectance",
        "NIR_reflectance",
        "MIR_reflectance",
        "view_zenith_angle",
        "sun_zenith_angle",
        "relative_azimuth_angle",
    },
    "mod11a2-6.1": {
        "LST_Day_1km",
        "QC_Day",
        "Day_view_time",
        "Day_view_angl",
        "LST_Night_1km",
        "QC_Night",
        "Night_view_time",
        "Night_view_angl",
        "Emis_31",
        "Emis_32",
        "Clear_sky_days",
        "Clear_sky_nights",
    },
    "myd11a2-6.1": {
        "LST_Day_1km",
        "QC_Day",
        "Day_view_time",
        "Day_view_angl",
        "LST_Night_1km",
        "QC_Night",
        "Night_view_time",
        "Night_view_angl",
        "Emis_31",
        "Emis_32",
        "Clear_sky_days",
        "Clear_sky_nights",
    },
    "CBERS4-WFI-16D-2": {
        "BAND13",
        "BAND14",
        "BAND15",
        "BAND16",
        "CMASK",
        "CLEAROB",
        "TOTALOB",
        "PROVENANCE",
        "EVI",
        "NDVI",
    },
    "CBERS-WFI-8D-1": {
        "BAND13",
        "BAND14",
        "BAND15",
        "BAND16",
        "CMASK",
        "CLEAROB",
        "TOTALOB",
        "DATASOURCE",
        "PROVENANCE",
        "EVI",
        "NDVI",
    },
    "CBERS4-MUX-2M-1": {"BAND5", "BAND6", "BAND7", "BAND8", "NDVI", "CMASK", "CLEAROB", "TOTALOB", "PROVENANCE", "EVI"},
}

# Nodata sentinel values (raw integers as read from GDAL/WTSS)
_NODATA_VALUES = {-9999, -9999.0, None}

_MAX_RETRIES = 4
_RETRY_DELAY = 0.15  # base seconds — increases linearly per attempt
_DEFAULT_WTSS_WORKERS = 3  # conservative — avoids overloading server DB connections

# ---------------------------------------------------------------------------
# Circuit breaker per collection
# ---------------------------------------------------------------------------
_cb_lock = threading.Lock()
_cb_state: dict[str, dict] = {}  # {cov_id: {"failures": int, "until": float}}

_CB_THRESHOLD = 6  # consecutive failures to open (more tolerant — intermittent 500s)
_CB_COOLDOWN = 120.0  # seconds before retrying


def _cb_success(collection_id: str):
    with _cb_lock:
        if collection_id in _cb_state:
            _cb_state[collection_id]["failures"] = 0


def _cb_failure(collection_id: str):
    with _cb_lock:
        s = _cb_state.setdefault(collection_id, {"failures": 0, "until": 0.0})
        s["failures"] += 1
        if s["failures"] >= _CB_THRESHOLD:
            s["until"] = _time.monotonic() + _CB_COOLDOWN
            _log_warning(f"Circuit breaker OPEN for '{collection_id}' — unavailable for {_CB_COOLDOWN // 60:.0f} min")


def _cb_is_open(collection_id: str) -> bool:
    with _cb_lock:
        s = _cb_state.get(collection_id)
        if not s or s["until"] == 0.0:
            return False
        if _time.monotonic() >= s["until"]:
            s["until"] = 0.0
            s["failures"] = 0
            _log_info(f"Circuit breaker HALF-OPEN for '{collection_id}'")
            return False
        return True


def _get_wtss_workers() -> int:
    try:
        from ..config import get_performance_config

        return get_performance_config().get("wtss_workers", _DEFAULT_WTSS_WORKERS)
    except Exception:
        return _DEFAULT_WTSS_WORKERS


def _make_request_semaphore() -> threading.Semaphore:
    """Create the WTSS HTTP semaphore sized to the configured worker count.

    Sized to wtss_workers so that every worker can hold one connection;
    the server-side limit is enforced by the BDC PostgreSQL connection pool.
    """
    return threading.Semaphore(_get_wtss_workers())


# Limits simultaneous WTSS HTTP requests — sized to configured wtss_workers.
# Prevents "too many connections" on the BDC server's PostgreSQL pool.
_REQUEST_SEMAPHORE = _make_request_semaphore()


def reset_request_semaphore():
    """Recreate _REQUEST_SEMAPHORE from the current wtss_workers config.

    Call this after applying new performance settings so the updated concurrency
    limit takes effect for subsequent WTSS requests.
    """
    global _REQUEST_SEMAPHORE
    _REQUEST_SEMAPHORE = _make_request_semaphore()


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def collection_has_wtss(collection_id: str) -> bool:
    """Return True if the collection has WTSS coverage."""
    return collection_id in WTSS_COVERAGES


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Lightweight health check: list_coverages does not query the database
# ---------------------------------------------------------------------------


def get_wtss_status() -> tuple:
    """Return (online: bool, latency_ms: float).

    Uses GET /v4/list_coverages — a lightweight endpoint that does not hit the DB.
    Ideal for checking availability without overloading the server.
    """
    try:
        t0 = _time.perf_counter()
        r = requests.get(f"{WTSS_V4}/list_coverages", timeout=PING_S)
        ms = (_time.perf_counter() - t0) * 1000
        if r.status_code == 200:
            return True, ms
        return False, ms
    except Exception as _e:
        _log_warning(f"WTSS health check failed: {_e}")
        return False, 0.0


# ---------------------------------------------------------------------------
# Core GET helper — GET /v4/time_series (only functional endpoint)
# ---------------------------------------------------------------------------


def _wtss_get(collection_id: str, bands: list, lat: float, lon: float, start_date: str, end_date: str) -> dict:
    """GET /v4/time_series with retry for 5xx and network errors.

    Returns the full JSON response on success (HTTP 200).
    Raises RuntimeError on permanent failure or parameter error (4xx).
    """
    if _cb_is_open(collection_id):
        raise RuntimeError(f"WTSS circuit breaker open for '{collection_id}'")

    # Filter out locally-unknown bands (avoid unnecessary 400)
    known = WTSS_BANDS.get(collection_id)
    valid_bands = [b for b in bands if (not known) or (b in known)]
    if not valid_bands:
        raise RuntimeError(f"No valid bands for WTSS '{collection_id}': {bands}")

    params = {
        "coverage": collection_id,
        "attributes": ",".join(valid_bands),
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date,
        "end_date": end_date,
    }
    last_exc: Exception | None = None

    for attempt in range(_MAX_RETRIES):
        try:
            with _REQUEST_SEMAPHORE:  # limit simultaneous connections to the server
                resp = requests.get(_TS_URL, params=params, timeout=WTSS_SERIES_S)

            if resp.status_code == 200:
                _cb_success(collection_id)
                return resp.json()

            # 4xx = parameter error (non-existent band etc.) — do not retry
            if 400 <= resp.status_code < 500:
                try:
                    err = resp.json()
                except Exception:
                    err = {"description": resp.text[:120]}
                raise RuntimeError(f"WTSS HTTP {resp.status_code} for '{collection_id}': {err.get('description', '')}")

            # 5xx / 502 — unhealthy node, load balancer may route to another; retry
            try:
                err_desc = resp.json().get("description", resp.text[:80])
            except Exception:
                err_desc = resp.text[:80]
            last_exc = Exception(f"HTTP {resp.status_code}: {err_desc}")

        except RuntimeError:
            raise
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc

        if attempt < _MAX_RETRIES - 1:
            _time.sleep(_RETRY_DELAY * (attempt + 1))

    _cb_failure(collection_id)
    raise RuntimeError(f"WTSS '{collection_id}' failed after {_MAX_RETRIES} attempts: {last_exc}")


# ---------------------------------------------------------------------------
# Per-band attributes declared by describe_coverage
# ---------------------------------------------------------------------------
_attr_lock = threading.Lock()
_attr_cache: dict[str, dict] = {}  # {coverage: {band: {"missing": float|None, "min": float|None, "max": float|None}}}


def _as_float(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _coverage_attributes(collection_id: str, fetch: bool = True) -> dict:
    """Return {band: {"missing", "min", "max"}} declared by WTSS describe_coverage.

    ``missing`` is the band's ``missing_value`` and ``min``/``max`` its
    ``valid_range``; each is None when the server does not declare it.
    Successful answers are cached per coverage; on failure an empty dict is
    returned and the next call asks again. With ``fetch=False`` only the cache
    is read, so the call never touches the network.
    """
    with _attr_lock:
        cached = _attr_cache.get(collection_id)
    if cached is not None:
        return cached
    if not fetch:
        return {}
    try:
        resp = requests.get(_DESCRIBE_URL, params={"name": collection_id}, timeout=METADATA_S)
        if resp.status_code != 200:
            return {}
        attrs = {}
        for attr in resp.json().get("attributes", []):
            name = attr.get("name")
            if not name:
                continue
            valid = attr.get("valid_range") or {}
            attrs[name] = {
                "missing": _as_float(attr.get("missing_value")),
                "min": _as_float(valid.get("min")),
                "max": _as_float(valid.get("max")),
            }
    except Exception as exc:
        _log_warning(f"WTSS describe_coverage failed for '{collection_id}': {exc}")
        return {}
    with _attr_lock:
        _attr_cache[collection_id] = attrs
    return attrs


def _coverage_missing_values(collection_id: str) -> dict:
    """Return {band: missing_value} for the bands that declare one.

    Bands such as Landsat ``red`` (uint16) use 0 as missing value, which the
    -9999 sentinel does not cover.
    """
    return {
        band: info["missing"]
        for band, info in _coverage_attributes(collection_id).items()
        if info["missing"] is not None
    }


def coverage_valid_ranges(collection_id: str, fetch: bool = True) -> dict:
    """Return {band: (min, max)} for the bands whose valid_range is declared.

    ``fetch=False`` reads only what an earlier extraction already cached.
    """
    return {
        band: (info["min"], info["max"])
        for band, info in _coverage_attributes(collection_id, fetch).items()
        if info["min"] is not None and info["max"] is not None and info["min"] < info["max"]
    }


# ---------------------------------------------------------------------------
# Parse response GET → {band: [(datetime, raw_value), ...]}
# ---------------------------------------------------------------------------


def _parse_get_response(data: dict, bands: list, missing_values: Optional[dict] = None) -> dict:
    """Convert GET /time_series response to {band: [(datetime, raw_int), ...]}.

    Values are raw integers — identical to those read via GDAL from BDC COGs.
    No scale factor is applied: NDVI of S2-16D-2 stays 6258, not 0.6258.
    Observations equal to -9999 or to the band's entry in ``missing_values``
    are dropped.
    """
    missing_values = missing_values or {}
    result_block = data.get("result", {})
    timeline = result_block.get("timeline", [])
    attrs = result_block.get("attributes", [])

    if not timeline or not attrs:
        return {}  # point outside coverage or no data

    # Index by band name
    values_by_band = {a["attribute"]: a.get("values", []) for a in attrs}

    result = {}
    for band in bands:
        raw_vals = values_by_band.get(band)
        if not raw_vals:
            continue
        band_data = []
        band_missing = missing_values.get(band)
        for date_str, val in zip(timeline, raw_vals):
            if val is None or val in _NODATA_VALUES or (band_missing is not None and val == band_missing):
                continue
            try:
                dt = datetime.strptime(str(date_str)[:10], "%Y-%m-%d")
            except (ValueError, TypeError):
                continue
            band_data.append((dt, float(val)))
        if band_data:
            band_data.sort(key=lambda x: x[0])
            result[band] = band_data

    return result


# ---------------------------------------------------------------------------
# Single-point extraction
# ---------------------------------------------------------------------------


def _extract_wtss_single_point(
    collection_id: str, bands: list, lat: float, lon: float, start_date: str, end_date: str
) -> dict:
    """Extract all bands for a single point via GET /v4/time_series.

    Returns {band: [(datetime, raw_value), ...]} — raw values identical to GDAL.
    Returns {} if the point is outside coverage (empty timeline).
    Raises RuntimeError on persistent server or network error.
    """
    data = _wtss_get(collection_id, bands, lat, lon, start_date, end_date)
    return _parse_get_response(data, bands, _coverage_missing_values(collection_id))


# ---------------------------------------------------------------------------
# Multi-point extraction (parallel workers)
# ---------------------------------------------------------------------------


def extract_wtss_multi_points(
    collection_id: str, points_bands: list, start_date: str, end_date: str, cancel_flag=None, progress_callback=None
) -> dict:
    """Extract time series for multiple points in parallel.

    points_bands: list of (lon, lat, label, bands_list)
    Returns: {pt_idx: {band: [(datetime, value), ...]}}

    Points without data (outside coverage) return {} — caller falls back to STAC.
    The circuit breaker protects against fully unavailable servers.
    No separate probe — each point has its own retries + CB.
    """
    if not points_bands:
        return {}

    if _cb_is_open(collection_id):
        _log_warning(f"Circuit breaker open for '{collection_id}' — using STAC+VRT")
        return {i: {} for i in range(len(points_bands))}

    n_workers = min(len(points_bands), _get_wtss_workers())
    results: dict = {}

    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        future_to_idx = {}
        for pt_idx, (lon, lat, label, bands) in enumerate(points_bands):
            if cancel_flag and cancel_flag():
                break
            f = executor.submit(
                _extract_wtss_single_point,
                collection_id,
                bands,
                lat,
                lon,
                start_date,
                end_date,
            )
            future_to_idx[f] = (pt_idx, label)

        for future in as_completed(future_to_idx):
            pt_idx, label = future_to_idx[future]
            if cancel_flag and cancel_flag():
                # Points still queued are dropped; leaving the with block
                # would otherwise wait for every one of them.
                for queued in future_to_idx:
                    queued.cancel()
                break
            try:
                point_data = future.result()
                results[pt_idx] = point_data
                if progress_callback:
                    progress_callback(pt_idx, label, point_data)
            except Exception as exc:
                _log_error(f"'{label}' failed: {exc}")
                results[pt_idx] = {}

    return results
