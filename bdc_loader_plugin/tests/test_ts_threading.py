#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_ts_threading.py — Thread safety tests for time series extraction pipeline.

Covers: the single time series search, extract_wtss_multi_points parallel
workers, extract_multi_band_timeseries flat parallel strategy, thread-safe
progress callbacks, concurrent exception isolation.

Run: python3 -m pytest bdc_loader_plugin/tests/test_ts_threading.py -v
"""

import threading
import time
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

# ── _search_points_items ─────────────────────────────────────────────────────


class TestSearchPointsItems(unittest.TestCase):
    """TSExtractionEngine._search_points_items: one paginated search for all points."""

    def _make_engine(self, items):
        from bdc_loader_plugin.core.ts_extraction import TSExtractionEngine

        eng = TSExtractionEngine.__new__(TSExtractionEngine)
        client = MagicMock()
        client.search.return_value.items.return_value = iter(items)
        eng._get_stac_client = MagicMock(return_value=client)
        return eng, client

    def test_several_points_are_one_multipoint_search_without_item_cap(self):
        late = MagicMock(datetime=datetime(2023, 6, 1))
        early = MagicMock(datetime=datetime(2023, 1, 1))
        eng, client = self._make_engine([late, early])

        items = eng._search_points_items("landsat-2", [(-47.2, -21.2), (-43.95, -20.15)], "2023-01-01", "2023-12-31")

        client.search.assert_called_once()
        kwargs = client.search.call_args.kwargs
        self.assertEqual(
            kwargs["intersects"], {"type": "MultiPoint", "coordinates": [[-47.2, -21.2], [-43.95, -20.15]]}
        )
        self.assertIsNone(kwargs["max_items"])
        self.assertEqual(kwargs["collections"], ["landsat-2"])
        self.assertEqual(kwargs["datetime"], "2023-01-01/2023-12-31")
        self.assertEqual(items, [early, late])

    def test_single_point_is_a_point_search(self):
        eng, client = self._make_engine([])
        eng._search_points_items("S2-16D-2", [(-45.0, -12.0)], "2023-01-01", "2023-12-31")
        self.assertEqual(client.search.call_args.kwargs["intersects"], {"type": "Point", "coordinates": [-45.0, -12.0]})

    def test_point_search_follows_every_page(self):
        from bdc_loader_plugin.core.ts_extraction import TSExtractionEngine

        eng, client = self._make_engine([])
        TSExtractionEngine._search_items(eng, "landsat-2", -47.2, -21.2, "2016-01-01", "2026-12-31")
        self.assertIsNone(client.search.call_args.kwargs["max_items"])

    def test_point_search_keeps_an_explicit_cap(self):
        from bdc_loader_plugin.core.ts_extraction import TSExtractionEngine

        eng, client = self._make_engine([])
        TSExtractionEngine._search_items(eng, "landsat-2", -47.2, -21.2, "2023-01-01", "2023-12-31", max_items=5)
        self.assertEqual(client.search.call_args.kwargs["max_items"], 5)
        self.assertEqual(client.search.call_args.kwargs["limit"], 5)


class TestReadSeriesFromCogs(unittest.TestCase):
    """TSExtractionEngine._read_series_from_cogs wires the search to the grouped reader."""

    def _make_engine(self):
        from bdc_loader_plugin.core.ts_extraction import TSExtractionEngine

        eng = TSExtractionEngine.__new__(TSExtractionEngine)
        eng._cancel_extraction = threading.Event()
        eng._set_status = MagicMock()
        eng.progress_bar = MagicMock()
        eng._search_around_point = MagicMock(return_value=[])
        return eng

    def test_point_left_empty_is_searched_again_and_matched_locally(self):
        eng = self._make_engine()
        near = MagicMock(id="h10")
        edge = MagicMock(id="h09")
        eng._search_points_items = MagicMock(return_value=[near])
        eng._search_around_point = MagicMock(return_value=[near, edge])
        calls = []

        def _extract(items_per_point, points, bands, **kwargs):
            calls.append([[it.id for it in items] for items in items_per_point])
            if [it.id for it in items_per_point[0]] == ["h09"]:
                return {0: {"red": [("2026-08-21", 951.0)]}}, 0
            return {0: {}}, 0

        def _assign(items, points):
            return [[it for it in items if it.id == "h09"]] if len(items) == 1 and items[0].id == "h09" else [items]

        with (
            patch("bdc_loader_plugin.core.ts_extraction.extract_points_timeseries", side_effect=_extract),
            patch("bdc_loader_plugin.core.ts_extraction.assign_items_to_points", side_effect=_assign),
        ):
            series, failed = eng._read_series_from_cogs(
                "myd13q1-6.1", [(-80.23, -3.85, "P", ["red"], None)], [["red"]], "2026-04-23", "2026-08-22"
            )

        eng._search_around_point.assert_called_once_with("myd13q1-6.1", (-80.23, -3.85), "2026-04-23", "2026-08-22")
        # The second read covers only the item the first search missed.
        self.assertEqual(calls, [[["h10"]], [["h09"]]])
        self.assertEqual(series, {0: {"red": [("2026-08-21", 951.0)]}})

    def test_one_search_and_per_point_bands(self):
        eng = self._make_engine()
        items = [MagicMock(id="a"), MagicMock(id="b")]
        eng._search_points_items = MagicMock(return_value=items)
        works = [(-47.2, -21.2, "Q1", ["red", "nir08"], None), (-43.95, -20.15, "Q2", ["red"], None)]
        with (
            patch(
                "bdc_loader_plugin.core.ts_extraction.assign_items_to_points", return_value=[items, items[:1]]
            ) as assign,
            patch(
                "bdc_loader_plugin.core.ts_extraction.extract_points_timeseries", return_value=({0: {"red": []}}, 3)
            ) as extract,
        ):
            result = eng._read_series_from_cogs("landsat-2", works, [w[3] for w in works], "2024-01-01", "2024-12-31")

        eng._search_points_items.assert_called_once_with(
            "landsat-2", [(-47.2, -21.2), (-43.95, -20.15)], "2024-01-01", "2024-12-31"
        )
        assign.assert_called_once_with(items, [(-47.2, -21.2), (-43.95, -20.15)])
        args, kwargs = extract.call_args
        self.assertEqual(args, ([items, items[:1]], [(-47.2, -21.2), (-43.95, -20.15)], ["red", "nir08"]))
        self.assertEqual(kwargs["bands_per_point"], [{"red", "nir08"}, {"red"}])
        self.assertEqual(result, ({0: {"red": []}}, 3))

    def test_no_items_reads_nothing(self):
        eng = self._make_engine()
        eng._search_points_items = MagicMock(return_value=[])
        with patch("bdc_loader_plugin.core.ts_extraction.extract_points_timeseries") as extract:
            result = eng._read_series_from_cogs("landsat-2", [(0.0, 0.0, "P", ["red"], None)], [["red"]], "a", "b")
        extract.assert_not_called()
        self.assertEqual(result, ({}, 0))

    def test_cancel_ends_the_wait_while_a_read_hangs(self):
        eng = self._make_engine()
        eng._search_points_items = MagicMock(return_value=[MagicMock(id="a")])
        release = threading.Event()

        def _hang(*args, **kwargs):
            release.wait(10)
            return {0: {"red": [("2024-01-01", 1.0)]}}, 0

        threading.Timer(0.3, eng._cancel_extraction.set).start()
        started = time.monotonic()
        try:
            with (
                patch("bdc_loader_plugin.core.ts_extraction.assign_items_to_points", return_value=[[MagicMock()]]),
                patch("bdc_loader_plugin.core.ts_extraction.extract_points_timeseries", side_effect=_hang),
            ):
                result = eng._read_series_from_cogs("S2-16D-2", [(0.0, 0.0, "P", ["red"], None)], [["red"]], "a", "b")
        finally:
            release.set()
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(result, ({}, 0))


# ── extract_wtss_multi_points ────────────────────────────────────────────────


class TestWtssMultiPointsThreading(unittest.TestCase):
    """Thread safety for extract_wtss_multi_points."""

    def test_parallel_extraction_returns_per_point(self):
        """Each point gets its own result dict."""
        with patch("bdc_loader_plugin.extraction.wtss_extractor._cb_is_open", return_value=False):
            with patch("bdc_loader_plugin.extraction.wtss_extractor._extract_wtss_single_point") as mock_ext:
                d = datetime(2023, 6, 1)
                mock_ext.side_effect = lambda cid, bands, lat, lon, s, e: {"B04": [(d, 5000.0 + lon)]}
                from bdc_loader_plugin.extraction.wtss_extractor import extract_wtss_multi_points

                points = [
                    (-45.0, -12.0, "P1", ["B04"]),
                    (-46.0, -13.0, "P2", ["B04"]),
                    (-47.0, -14.0, "P3", ["B04"]),
                ]
                results = extract_wtss_multi_points("S2-16D-2", points, "2023-01-01", "2023-12-31")

        self.assertEqual(len(results), 3)
        for idx in range(3):
            self.assertIn("B04", results[idx])

    def test_one_point_failure_doesnt_crash_others(self):
        """Exception in one point → {} for that point, others succeed."""
        with patch("bdc_loader_plugin.extraction.wtss_extractor._cb_is_open", return_value=False):
            with patch("bdc_loader_plugin.extraction.wtss_extractor._extract_wtss_single_point") as mock_ext:

                def _side(cid, bands, lat, lon, s, e):
                    if lon == -46.0:
                        raise RuntimeError("WTSS timeout")
                    return {"B04": [(datetime(2023, 1, 1), 5000.0)]}

                mock_ext.side_effect = _side
                from bdc_loader_plugin.extraction.wtss_extractor import extract_wtss_multi_points

                points = [
                    (-45.0, -12.0, "P1", ["B04"]),
                    (-46.0, -13.0, "P2", ["B04"]),
                    (-47.0, -14.0, "P3", ["B04"]),
                ]
                results = extract_wtss_multi_points("S2-16D-2", points, "2023-01-01", "2023-12-31")

        self.assertIn("B04", results[0])
        self.assertEqual(results[1], {})
        self.assertIn("B04", results[2])

    def test_circuit_breaker_open_returns_empty(self):
        """When CB is open, all points get {} without calling WTSS."""
        with patch("bdc_loader_plugin.extraction.wtss_extractor._cb_is_open", return_value=True):
            with patch("bdc_loader_plugin.extraction.wtss_extractor._extract_wtss_single_point") as mock_ext:
                from bdc_loader_plugin.extraction.wtss_extractor import extract_wtss_multi_points

                points = [(-45.0, -12.0, "P1", ["B04"]), (-46.0, -13.0, "P2", ["B04"])]
                results = extract_wtss_multi_points("S2-16D-2", points, "2023-01-01", "2023-12-31")

        self.assertEqual(results, {0: {}, 1: {}})
        mock_ext.assert_not_called()

    def test_progress_callback_called_per_point(self):
        """progress_callback receives (pt_idx, label, data) per point."""
        callback_calls = []

        with patch("bdc_loader_plugin.extraction.wtss_extractor._cb_is_open", return_value=False):
            with patch("bdc_loader_plugin.extraction.wtss_extractor._extract_wtss_single_point") as mock_ext:
                mock_ext.return_value = {"B04": [(datetime(2023, 1, 1), 5000.0)]}
                from bdc_loader_plugin.extraction.wtss_extractor import extract_wtss_multi_points

                points = [(-45.0, -12.0, "P1", ["B04"]), (-46.0, -13.0, "P2", ["B04"])]
                extract_wtss_multi_points(
                    "S2-16D-2",
                    points,
                    "2023-01-01",
                    "2023-12-31",
                    progress_callback=lambda idx, lbl, data: callback_calls.append((idx, lbl)),
                )

        self.assertEqual(len(callback_calls), 2)
        labels = {c[1] for c in callback_calls}
        self.assertEqual(labels, {"P1", "P2"})

    def test_thread_safe_progress_callback(self):
        """Progress callback must handle concurrent invocations safely."""
        lock = threading.Lock()
        progress = {"count": 0}

        def _safe_cb(idx, label, data):
            with lock:
                progress["count"] += 1

        with patch("bdc_loader_plugin.extraction.wtss_extractor._cb_is_open", return_value=False):
            with patch("bdc_loader_plugin.extraction.wtss_extractor._extract_wtss_single_point") as mock_ext:

                def _slow(cid, bands, lat, lon, s, e):
                    time.sleep(0.01)
                    return {"B04": [(datetime(2023, 1, 1), 5000.0)]}

                mock_ext.side_effect = _slow
                from bdc_loader_plugin.extraction.wtss_extractor import extract_wtss_multi_points

                points = [(float(i), float(i), f"P{i}", ["B04"]) for i in range(6)]
                extract_wtss_multi_points("S2-16D-2", points, "2023-01-01", "2023-12-31", progress_callback=_safe_cb)

        self.assertEqual(progress["count"], 6)


# ── extract_multi_band_timeseries flat parallel ──────────────────────────────


# ── Thread-safe data structures ──────────────────────────────────────────────


# ── extract_pixel_timeseries_vrt threading ───────────────────────────────────


# ── point items cache ────────────────────────────────────────────────────────


class _SlowDict(dict):
    """A dict whose eviction pauses, so threads that evict at once overlap."""

    def pop(self, key, *default):
        time.sleep(0.002)
        return super().pop(key, *default)


class TestPointItemsCache(unittest.TestCase):
    def test_workers_filling_a_full_cache_at_once_do_not_fail(self):
        from bdc_loader_plugin.core import ts_extraction
        from bdc_loader_plugin.core.ts_extraction import TSExtractionEngine

        eng = TSExtractionEngine.__new__(TSExtractionEngine)
        eng._point_items_cache = _SlowDict()
        errors = []
        start = threading.Barrier(8)

        def fill(worker):
            start.wait()
            try:
                for n in range(20):
                    eng._remember_point_items("S2-16D-2", (worker, n), "2019", "2023", ["item"])
            except Exception as exc:  # what a race raises: KeyError or RuntimeError
                errors.append(exc)

        with patch.object(ts_extraction, "_POINT_ITEMS_CACHE_SIZE", 4):
            threads = [threading.Thread(target=fill, args=(w,)) for w in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(errors, [])
        self.assertLessEqual(len(eng._point_items_cache), 4)


def test_wtss_gaps_lists_only_the_bands_wtss_did_not_return():
    from bdc_loader_plugin.core.ts_extraction import _wtss_gaps

    works = [(-45.0, -12.0, "P1", ["B04", "B08", "NDVI"], None), (-46.0, -13.0, "P2", ["B04"], None)]
    data = {0: {"B04": [(1, 2)]}, 1: {"B04": [(1, 3)]}}
    assert _wtss_gaps(works, data) == {0: ["B08", "NDVI"]}
    assert _wtss_gaps(works, {}) == {0: ["B04", "B08", "NDVI"], 1: ["B04"]}


# ── STAC client opened off the UI thread ─────────────────────────────────────


def _search_owner():
    from bdc_loader_plugin.core.search import SearchEngine

    owner = MagicMock()
    owner.client = None
    return SearchEngine, owner


def test_the_stac_client_opens_in_a_worker_while_the_ui_keeps_processing_events():
    SearchEngine, owner = _search_owner()
    opened_in = {}

    def _open(pystac_client, url):
        opened_in["thread"] = threading.current_thread()
        time.sleep(0.3)
        return "client"

    with (
        patch("bdc_loader_plugin.core.search.open_stac_client", side_effect=_open),
        patch("bdc_loader_plugin.core.ui_wait.QCoreApplication.processEvents") as events,
    ):
        assert SearchEngine._ensure_stac_client(owner, MagicMock(), "https://stac") is True
    assert owner.client == "client"
    assert opened_in["thread"] is not threading.main_thread()
    assert events.call_count >= 3


def test_a_stac_server_that_does_not_answer_switches_to_the_downloaded_images():
    SearchEngine, owner = _search_owner()
    release = threading.Event()
    try:
        with (
            patch("bdc_loader_plugin.core.search.open_stac_client", side_effect=lambda *a: release.wait(5)),
            patch("bdc_loader_plugin.core.search._CLIENT_OPEN_BUDGET_S", 0.3),
            patch("bdc_loader_plugin.core.ui_wait.QCoreApplication.processEvents"),
        ):
            started = time.monotonic()
            assert SearchEngine._ensure_stac_client(owner, MagicMock(), "https://stac") is False
            waited = time.monotonic() - started
    finally:
        release.set()
    assert waited < 2
    assert owner._stac_online is False
    owner._set_stac_status.assert_called_once_with(False)


if __name__ == "__main__":
    unittest.main()
