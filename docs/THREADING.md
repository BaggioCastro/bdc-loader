# Threading

Widgets, layers and the QGIS project are touched only on the Qt main thread. Network reads, GDAL work and
downloads run in worker threads, and their results come back to the main thread through
`ui/thumbnails.py::_invoke_on_ui_thread(callback)`, which emits a Qt signal from the worker; the receiving
object lives on the main thread, so the callback runs there.

`QTimer.singleShot` is used only from the main thread. Called from a plain Python thread it would need an
event loop that thread does not have.

## The main thread waits in short slices

`core/ui_wait.py` holds the only waits of the main thread on its workers. `run_in_worker(fn, ...)` and
`wait_for(future, ...)` wait for one result in slices of `POLL_INTERVAL_S` (0.05 s) and call
`QCoreApplication.processEvents()` between them; `on_wait` runs on the main thread after each slice, to show
progress, `budget_s` ends the wait with `TimeoutError`, and `cancelled()` ends it with `WaitCancelled`, leaving
the worker to finish on its own. `wait_slice(pending)` waits one slice for any of several futures.

The search opens the STAC client with a 15 s budget, after which it searches the downloaded images, and pages
through the results. The time series panel loads its collections and reads point series from the COGs and
from WTSS; Cancel ends those waits at once. The downloads, the windowed exports, the copy of the blocks of an
area and the grid download wait the same way.

The load phases (`core/vrt_generator.py`, `core/vrt_overview_run.py`, `core/vrt_layers.py`) start their
workers and call `wait_slice` until every future is done, under a time budget (`_VRT_BUILD_BUDGET_S`,
`_OVERVIEW_PHASE_BUDGET_S`). The dialog keeps painting and the Cancel button keeps working. While a load runs,
Load layers is disabled, so a click during `processEvents()` cannot start a second load.

## Network time limits

`net.py` names the time limits of the HTTP requests by kind: `PING_S` (8 s), `METADATA_S` (15 s), `STAC_PAGE_S`
(10 s to connect, 30 s of silence), `WTSS_SERIES_S` (30 s) and `TRANSFER_S` (60 s of silence inside a
transfer). The bundled pystac_client sends its requests without a limit, so `stac/client.py::open_stac_client`
gives its session `STAC_PAGE_S`. GDAL reads of time series pixels take `GDAL_HTTP_CONNECTTIMEOUT` and
`GDAL_HTTP_TIMEOUT` from the `http_timeout` setting.

## Worker pools

| Where | Workers | Work |
|---|---|---|
| `core/vrt_generator.py` | 8 | one VRT per selected result |
| `core/vrt_overview_run.py` | 4 | overview and display range of each remote layer |
| `core/vrt_layers.py` | 8, then 4 | display ranges; then opening the layers |
| `extraction/point_series.py` | `max_threads` | pixel series read from the COGs |
| `extraction/wtss_extractor.py` | `wtss_workers` | WTSS point extraction, one request per worker |
| `core/download_engine.py` | `download_connections` | downloads |
| `core/cog_window.py` | 4 files, segments per file | windowed COG downloads |
| `core/crop_preview.py` | 8 | crop thumbnails |
| `ui/thumbnails.py` | 4 (module level) | result thumbnails |
| `core/ui_wait.py::run_in_worker` | 1 | one call at a time, waited for in 0.05 s slices |

Daemon `threading.Thread`s fetch the collection list and temporal extents (`core/catalog.py`), extra bands for
the chart (`core/ts_bands.py`), the image of a clicked chart date (`core/ts_visualization.py`) and the offline
catalog (`ui/stac_offline_dialog.py`).

## Settings and where they act

| Setting | Read by | Not used for |
|---|---|---|
| `max_threads` | time series read from the COGs | VRT build, overviews, layer opening |
| `wtss_workers` | WTSS extraction and its request semaphore | anything else |
| `gdal_cache_mb`, `http_timeout` | GDAL options of the COG time series threads | the rest of the plugin, which uses `core/gdal_env.py` |
| `download_connections` | downloads | anything else |

## GDAL

`core/gdal_env.py::plugin_gdal(extra)` sets the plugin's options as thread-local config options for the
block it wraps and restores them after, so other layers and plugins in QGIS keep theirs. Each worker opens its
own GDAL datasets; datasets are never shared between threads.

## Shared state

| Lock | Module | Guards |
|---|---|---|
| `_session_lock` | `core/gdal_env.py` | the process-wide GDAL options, set once |
| `_cb_lock` | `extraction/wtss_extractor.py` | the WTSS circuit breaker counters |
| `_REQUEST_SEMAPHORE` | `extraction/wtss_extractor.py` | WTSS requests open at once |
| `_POINT_ITEMS_LOCK` | `core/ts_extraction.py` | the items remembered per point, filled by several threads |
| `_STAC_CLIENT_LOCK` | `core/ts_collections.py` | creation of the shared STAC client |

`core/catalog.py` keeps one STAC health check running at a time with `_stac_ping_running`. Extraction stops
cooperatively through `threading.Event` (`_cancel_extraction`), checked between files and bands.
