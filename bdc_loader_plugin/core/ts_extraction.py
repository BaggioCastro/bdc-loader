# -*- coding: utf-8 -*-
"""
TSExtractionEngine — Time series extraction for the time series panel.

Handles STAC item search, WTSS / STAC+VRT extraction, progress tracking,
and integration of extracted data into the history.
"""

import logging
import threading
from datetime import datetime

_logger = logging.getLogger("bdc_loader")

from qgis.PyQt.QtCore import QCoreApplication, QTimer
from qgis.PyQt.QtWidgets import QMessageBox

from ..extraction.band_scaling import band_entry, collection_band_info, declared_valid_range, display_scaling
from ..extraction.point_series import assign_items_to_points, extract_points_timeseries, item_datetime
from ..extraction.wtss_extractor import (
    collection_has_wtss,
    coverage_valid_ranges,
    extract_wtss_multi_points,
)
from ..i18n import count_label, failure_text, set_text
from ..logger import error as _log_error
from ..stac.client import search_items
from ..timing import MISSING_BANDS_FETCH_MS
from .ts_constants import _INDEX_DEFS
from .ui_wait import WaitCancelled, run_in_worker

# Items per page of a time series search; every page is followed, so a
# long series is never cut at a fixed item count.
_SEARCH_PAGE = 500
# Degrees around a point searched again when the point search gave it no
# values; 0.27 degrees was the gap seen at a MODIS tile edge.
_POINT_SEARCH_MARGIN = 0.5
# Spectral indices are stored x10000.
_INDEX_RANGE = (-10000.0, 10000.0)
# Points whose item lists are kept for bands requested later.
_POINT_ITEMS_CACHE_SIZE = 200
# The point items cache is read and filled by the UI thread and by worker threads.
_POINT_ITEMS_LOCK = threading.Lock()


_CANCEL_BUTTON_STYLE = """
    QPushButton {
        background-color: #e74c3c; color: white; border: none; border-radius: 4px;
        font-size: 10px; font-weight: bold; padding: 4px 12px;
    }
    QPushButton:hover { background-color: #c0392b; }
"""
_CANCELLING_BUTTON_STYLE = """
    QPushButton {
        background-color: #95a5a6; color: white; border: none; border-radius: 4px;
        font-size: 10px; font-weight: bold; padding: 4px 12px;
    }
"""


def _point_key(cid, point, start, end):
    return cid, round(float(point[0]), 6), round(float(point[1]), 6), str(start), str(end)


def _wtss_gaps(points_work, data_by_point):
    """{point index: bands requested for it that WTSS returned no series for}."""
    gaps = {}
    for i, work in enumerate(points_work):
        missing = [band for band in work[3] if band not in data_by_point.get(i, {})]
        if missing:
            gaps[i] = missing
    return gaps


def _display_scalings(band_info, point_data):
    """{band: (a, b)} drawing each reflectance band of ``point_data`` as reflectance x 10^4."""
    scalings = {}
    for band in point_data:
        scaling = display_scaling(band_entry(band_info, band))
        if scaling:
            scalings[band] = scaling
    return scalings


class TSExtractionEngine:
    """STAC search and time series extraction (WTSS + VRT)."""

    def _find_existing_entry(self, lon, lat, cid, start, end):
        for entry in self._history:
            if (
                abs(entry["lon"] - lon) < 1e-6
                and abs(entry["lat"] - lat) < 1e-6
                and entry["collection"] == cid
                and entry["start"] == start
                and entry["end"] == end
            ):
                return entry
        return None

    def _get_missing_bands(self, entry, bands):
        existing_bands = set(entry["bands"])
        return [b for b in bands if b not in existing_bands]

    def _search_points_items(self, collection_id, points, start_date, end_date):
        """Every item covering any of ``points`` [(lon, lat)], in one search."""
        client = self._get_stac_client()
        if not client:
            return []
        if len(points) == 1:
            geometry = {"type": "Point", "coordinates": list(points[0])}
        else:
            geometry = {"type": "MultiPoint", "coordinates": [list(p) for p in points]}
        search = client.search(
            collections=[collection_id],
            datetime=f"{start_date}/{end_date}",
            intersects=geometry,
            max_items=None,
            limit=_SEARCH_PAGE,
        )
        items = list(search_items(search))
        items.sort(key=self._get_item_date)
        return items

    def _remember_point_items(self, cid, point, start, end, items):
        """Keep the items found for one point, for bands requested later."""
        cache = getattr(self, "_point_items_cache", None)
        if cache is None or not items:
            return
        with _POINT_ITEMS_LOCK:
            if len(cache) >= _POINT_ITEMS_CACHE_SIZE:
                cache.pop(next(iter(cache)))
            cache[_point_key(cid, point, start, end)] = list(items)

    def _point_items(self, cid, point, start, end):
        """Items covering ``point``: remembered from an earlier search, else searched.

        Safe from worker threads. A point the search misses is searched again
        around it, as in _read_series_from_cogs.
        """
        cache = getattr(self, "_point_items_cache", None)
        key = _point_key(cid, point, start, end)
        with _POINT_ITEMS_LOCK:
            cached = cache.get(key) if cache is not None else None
        if cached is not None:
            return cached
        items = assign_items_to_points(self._search_points_items(cid, [point], start, end), [point])[0]
        if not items:
            items = assign_items_to_points(self._search_around_point(cid, point, start, end), [point])[0]
        self._remember_point_items(cid, point, start, end, items)
        return items

    def _search_around_point(self, collection_id, point, start_date, end_date, margin=_POINT_SEARCH_MARGIN):
        """Items whose bbox meets a square of ``margin`` degrees around ``point``."""
        client = self._get_stac_client()
        if not client:
            return []
        lon, lat = point
        try:
            search = client.search(
                collections=[collection_id],
                datetime=f"{start_date}/{end_date}",
                bbox=[lon - margin, lat - margin, lon + margin, lat + margin],
                max_items=None,
                limit=_SEARCH_PAGE,
            )
            return list(search_items(search))
        except Exception as exc:
            _log_error(f"STAC search around point failed: {exc}")
            return []

    def _collection_band_info(self, cid):
        """Band scale, offset and valid range of ``cid``, fetched in a worker."""
        return run_in_worker(collection_band_info, cid)

    def _read_series_from_cogs(self, cid, works, bands_per_work, start, end):
        """Series of ``works`` (points_work rows) read from the COGs.

        One search for all points, then each file read once for every point
        it covers. Runs in a worker while the UI polls progress and cancel.
        Returns ({work index: {band: [(date, value)]}}, failed pixel reads).
        """
        points = [(w[0], w[1]) for w in works]
        all_bands = list(dict.fromkeys(b for bands in bands_per_work for b in bands))
        progress = {"stage": "search", "done": 0, "total": 0}
        lock = threading.Lock()

        def _on_progress(done, total):
            with lock:
                progress.update(stage="read", done=done, total=total)

        def _extract(items_per_point, indices):
            series, failed = extract_points_timeseries(
                items_per_point,
                [points[i] for i in indices],
                all_bands,
                cancel_flag=self._cancel_extraction.is_set,
                progress_callback=_on_progress,
                bands_per_point=[set(bands_per_work[i]) for i in indices],
            )
            return {indices[k]: v for k, v in series.items()}, failed

        def _run():
            items = self._search_points_items(cid, points, start, end)
            with lock:
                progress["items"] = len(items)
            if self._cancel_extraction.is_set():
                return {}, 0
            series, failed = {}, 0
            per_point = assign_items_to_points(items, points) if items else [[] for _ in points]
            for i, point_items in enumerate(per_point):
                self._remember_point_items(cid, points[i], start, end, point_items)
            if items:
                series, failed = _extract(per_point, list(range(len(points))))
            # The BDC search can miss an item whose returned footprint covers
            # the point (MODIS tiles near their edges): a point left without
            # values is searched again with a margin and matched locally.
            seen = {getattr(item, "id", None) for item in items}
            for i in range(len(points)):
                if self._cancel_extraction.is_set() or any(series.get(i, {}).values()):
                    continue
                extra = [it for it in self._search_around_point(cid, points[i], start, end) if it.id not in seen]
                if not extra:
                    continue
                covering = assign_items_to_points(extra, [points[i]])[0]
                if covering:
                    self._remember_point_items(cid, points[i], start, end, covering)
                    found, more_failed = _extract([covering], [i])
                    series.update(found)
                    failed += more_failed
            return series, failed

        self._set_status(f"Searching images for {count_label(len(points), 'point', 'points')} (STAC)...", "loading", 0)
        self.progress_bar.setMaximum(0)
        QCoreApplication.processEvents()

        def _show_progress():
            with lock:
                snapshot = dict(progress)
            if snapshot["stage"] == "read" and snapshot["total"]:
                self.progress_bar.setMaximum(snapshot["total"])
                self.progress_bar.setValue(snapshot["done"])
                self._set_status(
                    f"Extracting time series (STAC): {snapshot['done']}/{snapshot['total']} files "
                    f"of {count_label(snapshot.get('items', 0), 'image', 'images')}, "
                    f"{count_label(len(points), 'point', 'points')}",
                    "loading",
                    0,
                )

        # A cancel ends the wait at once; the reads already running end on
        # their own within GDAL_HTTP_TIMEOUT and their values are dropped.
        try:
            return run_in_worker(_run, on_wait=_show_progress, cancelled=self._cancel_extraction.is_set)
        except WaitCancelled:
            return {}, 0

    def _extract_time_series(self, picker_overlay_text=None):
        """Extract the selected bands for every point and add them to the history."""
        request = self._extraction_request()
        if request is None:
            return
        cid, selected_bands = request
        extraction_bands, index_names, requested_indices = self._plan_extraction_bands(cid, selected_bands)
        start = self.range_slider.get_start_date().toString("yyyy-MM-dd")
        end = self.range_slider.get_end_date().toString("yyyy-MM-dd")
        points_work, skipped, merged = self._plan_point_work(cid, start, end, extraction_bands, index_names)
        if not points_work:
            text = "The point is already extracted." if skipped == 1 else f"All {skipped} points are already extracted."
            self._set_status(text, "warning")
            return
        self._announce_reuse(skipped, merged)
        self._begin_extraction(picker_overlay_text)
        use_wtss = collection_has_wtss(cid)
        try:
            fetched = self._fetch_point_series(cid, points_work, start, end, use_wtss)
            if fetched is None:
                self._set_status("Time series extraction cancelled.", "warning")
                return
            data_by_point, failed_reads = fetched
            new_entries, merged_entries = self._store_point_series(
                cid,
                start,
                end,
                points_work,
                data_by_point,
                (extraction_bands, index_names, requested_indices),
                use_wtss,
            )
            self._show_extraction_result(new_entries, merged_entries, points_work, skipped, failed_reads, use_wtss)
        except Exception as e:
            self._set_status(failure_text("Time series extraction", str(e)[:150]), "error", 0)
            if use_wtss:
                self._set_wtss_indicator(False)
            _log_error("Error during time series extraction", exc_info=True)
        finally:
            self._end_extraction(picker_overlay_text)

    def _extraction_request(self):
        """(collection id, selected bands), or None after telling the user what is missing."""
        if not self._current_points:
            QMessageBox.warning(self, "Warning", "Add at least one point.")
            return None
        cid = self.ts_collection_combo.currentData()
        if not cid:
            QMessageBox.warning(self, "Warning", "Select a collection.")
            return None
        selected_bands = self._get_selected_bands()
        if not selected_bands:
            QMessageBox.warning(self, "Warning", "Select at least one band.")
            return None
        return cid, selected_bands

    def _plan_extraction_bands(self, cid, selected_bands):
        """(bands to read, index output names, requested index keys).

        An index (NDVI, EVI) adds the bands it is computed from to the read.
        """
        requested_indices = [b for b in selected_bands if b in _INDEX_DEFS]
        if not requested_indices:
            return list(selected_bands), [], []
        extraction_bands = [b for b in selected_bands if b not in _INDEX_DEFS]
        sources = set()
        for idx_key in requested_indices:
            for common_name in _INDEX_DEFS[idx_key]["requires"]:
                band = self._resolve_common_band(cid, common_name)
                if band:
                    sources.add(band)
        extraction_bands += [band for band in sorted(sources) if band not in extraction_bands]
        return extraction_bands, [_INDEX_DEFS[k]["output"] for k in requested_indices], requested_indices

    def _plan_point_work(self, cid, start, end, extraction_bands, index_names):
        """([(lon, lat, label, bands to read, existing entry or None)], skipped, merged).

        A point already in the history for this collection and period only
        reads the bands it lacks; when an index is missing, all its bands.
        """
        points_work, skipped, merged = [], 0, 0
        for lon, lat, label in self._current_points:
            existing = self._find_existing_entry(lon, lat, cid, start, end)
            if not existing:
                points_work.append((lon, lat, label, list(extraction_bands), None))
                continue
            missing = self._get_missing_bands(existing, extraction_bands)
            if not missing and any(name not in existing.get("data", {}) for name in index_names):
                missing = list(extraction_bands)
            if missing:
                points_work.append((lon, lat, label, missing, existing))
                merged += 1
            else:
                skipped += 1
        return points_work, skipped, merged

    def _announce_reuse(self, skipped, merged):
        parts = []
        if skipped > 0:
            parts.append(f"{count_label(skipped, 'point', 'points')} already extracted")
        if merged > 0:
            parts.append(f"{count_label(merged, 'point', 'points')} with new bands")
        if parts:
            text = f"Extracting time series ({', '.join(parts)})..."
            self._set_status(text, "loading", 0)
            QCoreApplication.processEvents()

    def _begin_extraction(self, picker_overlay_text):
        self.extract_btn.setEnabled(False)
        self.clear_hist_btn.setEnabled(False)
        self.progress_container.setVisible(True)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setMaximum(0)
        self._cancel_extraction = threading.Event()
        QCoreApplication.processEvents()
        self._ensure_chart_dock()
        if picker_overlay_text and self.chart_dock:
            self.chart_dock.show_loading_overlay(picker_overlay_text)

    def _end_extraction(self, picker_overlay_text):
        if picker_overlay_text and self.chart_dock:
            self.chart_dock.hide_loading_overlay()
        self.extract_btn.setEnabled(True)
        self.clear_hist_btn.setEnabled(True)
        self.progress_container.setVisible(False)
        # A fresh event instead of clear(): a worker left running by a cancel
        # holds the old one and must keep seeing it set.
        self._cancel_extraction = threading.Event()
        set_text(self.cancel_btn, "Cancel")
        self.cancel_btn.setStyleSheet(_CANCEL_BUTTON_STYLE)

    def _fetch_point_series(self, cid, points_work, start, end, use_wtss):
        """({work index: {band: series}}, failed reads), or None when cancelled.

        WTSS serves what it covers; the COGs serve the rest, or everything
        for a collection WTSS does not cover.
        """
        if use_wtss:
            return self._fetch_wtss_series(cid, points_work, start, end)
        data_by_point, failed_reads = self._read_series_from_cogs(
            cid, points_work, [work[3] for work in points_work], start, end
        )
        if self._cancel_extraction.is_set():
            return None
        return data_by_point, failed_reads

    def _fetch_wtss_series(self, cid, points_work, start, end):
        total = len(points_work)
        self._set_status(f"Extracting time series of {count_label(total, 'point', 'points')} (WTSS)...", "loading", 0)
        self.progress_bar.setMaximum(total)
        QCoreApplication.processEvents()
        progress = {"done": 0}
        lock = threading.Lock()

        def _on_point(_index, _label, _data):
            with lock:
                progress["done"] += 1

        def _show_progress():
            with lock:
                done = progress["done"]
            if done > 0:
                self.progress_bar.setValue(done)
                self._set_status(f"Extracting time series (WTSS): {done}/{total}", "loading", 0)

        try:
            all_wtss = run_in_worker(
                extract_wtss_multi_points,
                cid,
                [(lon, lat, label, bands) for lon, lat, label, bands, _ in points_work],
                start,
                end,
                cancel_flag=self._cancel_extraction.is_set,
                progress_callback=_on_point,
                on_wait=_show_progress,
                cancelled=self._cancel_extraction.is_set,
            )
        except WaitCancelled:
            return None

        self._set_wtss_indicator(any(bool(v) for v in all_wtss.values()))
        if self._cancel_extraction.is_set():
            return None
        data_by_point = {i: dict(all_wtss.get(i, {})) for i in range(total)}
        failed_reads = 0
        # Bands WTSS does not serve for a point are read from the COGs.
        gaps = _wtss_gaps(points_work, data_by_point)
        if gaps:
            names = sorted({b for bands in gaps.values() for b in bands})
            self._set_status(f"Extracting {', '.join(names[:3])} (STAC), not served by WTSS...", "loading", 0)
            order = sorted(gaps)
            fetched, failed_reads = self._read_series_from_cogs(
                cid, [points_work[i] for i in order], [gaps[i] for i in order], start, end
            )
            for k, i in enumerate(order):
                data_by_point[i].update(fetched.get(k, {}))
        return data_by_point, failed_reads

    def _store_point_series(self, cid, start, end, points_work, data_by_point, bands_plan, use_wtss):
        """Merge each point's series into its history entry or add a new entry.

        Returns (new entries, merged entries). Indices are computed here, on
        reflectance, and every entry records the bands' valid ranges and
        chart scaling.
        """
        extraction_bands, index_names, requested_indices = bands_plan
        band_info = self._collection_band_info(cid)
        declared_ranges = {}
        for band in extraction_bands:
            band_range = declared_valid_range(band_info, band)
            if band_range:
                declared_ranges[band] = band_range
        for name in index_names:
            declared_ranges[name] = _INDEX_RANGE

        new_entries, merged_entries = [], []
        for index, (lon, lat, label, _bands, existing) in enumerate(points_work):
            if self._cancel_extraction.is_set():
                self._set_status("Time series extraction cancelled.", "warning")
                break
            point_data = data_by_point.get(index, {})
            if not point_data and not use_wtss:
                continue
            if requested_indices and point_data:
                self._compute_vegetation_indices(cid, point_data, requested_indices, band_info)
            valid_range = dict(declared_ranges)
            valid_range.update(coverage_valid_ranges(cid, fetch=False))
            scaling = _display_scalings(band_info, point_data)
            if existing:
                for band, values in point_data.items():
                    existing["data"][band] = values
                    if band not in existing["bands"]:
                        existing["bands"].append(band)
                existing.setdefault("valid_range", {}).update(valid_range)
                existing.setdefault("scaling", {}).update(scaling)
                merged_entries.append(existing)
                self._remove_point_from_temp_layer(existing["id"])
                self._add_point_to_temp_layer(existing)
                continue
            self._history_counter += 1
            entry = {
                "id": self._history_counter,
                "lon": lon,
                "lat": lat,
                "label": label,
                "collection": cid,
                "bands": list(extraction_bands) + index_names,
                "start": start,
                "end": end,
                "data": point_data,
                "valid_range": valid_range,
                "scaling": scaling,
            }
            self._history.append(entry)
            new_entries.append(entry)
            self._add_point_to_temp_layer(entry)
        return new_entries, merged_entries

    def _show_extraction_result(self, new_entries, merged_entries, points_work, skipped, failed_reads, use_wtss):
        """Refresh the history, chart the latest entry and report what was extracted."""
        self._refresh_history_list()
        last_entry = (new_entries or merged_entries or [None])[-1]
        # A row removed from the history while the extraction ran is gone.
        if last_entry is not None and last_entry not in self._history:
            last_entry = None
        if last_entry:
            self._update_rgb_combos(last_entry["bands"], last_entry.get("collection", ""))
            self._current_viz_index = self._history.index(last_entry)
        elif self._history:
            self._update_rgb_combos(self._history[-1]["bands"], self._history[-1].get("collection", ""))
            self._current_viz_index = len(self._history) - 1

        if not self._history:
            if not use_wtss:
                text = f"No images found for {'the point' if len(points_work) == 1 else 'the points'} in this period."
                self._set_status(text, "warning")
            return
        self._update_viz_navigation()
        self.chart_dock.reset_axis_ranges()
        self._plot_result(self._history[self._current_viz_index])
        self.chart_dock.export_csv_btn.setEnabled(True)
        self.chart_dock.export_shp_btn.setEnabled(True)
        if last_entry and self.chart_dock and self.chart_dock.rgb_mode_btn.isChecked():
            self._fetch_missing_rgb_bands_later(last_entry)

        read_bands = {band for work in points_work for band in work[3]}
        total_values = sum(sum(len(v) for v in e["data"].values()) for e in new_entries)
        total_values += sum(sum(len(v) for band, v in e["data"].items() if band in read_bands) for e in merged_entries)
        parts = []
        if new_entries:
            parts.append(count_label(len(new_entries), "new point", "new points"))
        if merged_entries:
            parts.append(f"{len(merged_entries)} updated")
        if skipped > 0:
            parts.append(f"{skipped} unchanged")
        message = f"{count_label(total_values, 'value', 'values')} extracted"
        if parts:
            message += ": " + ", ".join(parts)
        if failed_reads:
            reads = count_label(failed_reads, "pixel read", "pixel reads")
            message += f". {reads} failed after a retry; the series has gaps."
            self._set_status(message, "warning")
        else:
            message += "."
            self._set_status(message, "success")

    def _fetch_missing_rgb_bands_later(self, entry):
        """Queue the RGB bands ``entry`` lacks, so the RGB chart can be completed."""
        self._rgb_bands_downloading = False
        combos = (self.chart_dock.rgb_r_combo, self.chart_dock.rgb_g_combo, self.chart_dock.rgb_b_combo)
        missing = [b for b in (combo.currentData() for combo in combos) if b and b not in entry.get("data", {})]
        if missing:
            QTimer.singleShot(
                MISSING_BANDS_FETCH_MS,
                lambda e=entry, m=list(dict.fromkeys(missing)): self._fetch_additional_bands(e, m),
            )

    def _on_cancel_extraction(self):
        self._cancel_extraction.set()
        self.cancel_btn.setEnabled(False)
        set_text(self.cancel_btn, "Cancelling...")
        self.cancel_btn.setStyleSheet(_CANCELLING_BUTTON_STYLE)
        self._set_status("Cancelling time series extraction...", "loading", 0)

    def _search_items(self, collection_id, lon, lat, start_date, end_date, max_items=None):
        client = self._get_stac_client()
        if not client:
            return []
        try:
            search = client.search(
                collections=[collection_id],
                datetime=f"{start_date}/{end_date}",
                intersects={"type": "Point", "coordinates": [lon, lat]},
                max_items=max_items,
                limit=min(max_items, _SEARCH_PAGE) if max_items else _SEARCH_PAGE,
            )
            items = list(search_items(search))
            items.sort(key=self._get_item_date)
            return items
        except Exception as e:
            _log_error(f"STAC search error: {e}")
            return []

    def _get_item_date(self, item):
        return item_datetime(item) or datetime.min
