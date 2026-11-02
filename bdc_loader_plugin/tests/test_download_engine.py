#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_download_engine.py — Tests for core/download_engine.py, the parallel
byte-range-segmented HTTP downloader.

Runs a real local HTTP server (with Range-request support, which Python's
stdlib SimpleHTTPRequestHandler lacks) so these tests exercise real sockets,
real threading, and real multi-segment reassembly — not just mocks — while
staying fast and fully offline.

Run: python3 -m pytest bdc_loader_plugin/tests/test_download_engine.py -v
"""

import hashlib
import http.server
import os
import tempfile
import threading
import unittest
from unittest.mock import patch


class _RangeHTTPHandler(http.server.BaseHTTPRequestHandler):
    """Serves in-memory byte payloads registered in `routes`, with Range support."""

    routes = {}  # path -> (bytes, supports_range: bool)
    fail_paths = set()  # paths that should return 500
    no_content_length = set()  # paths that omit the Content-Length header
    method_counts = {}  # (method, path) -> count, for asserting HEAD/GET counts
    throttle_gets = {}  # path -> how many more GETs answer 429 Too Many Requests
    _counts_lock = threading.Lock()

    @classmethod
    def count(cls, method, path):
        with cls._counts_lock:
            return cls.method_counts.get((method, path), 0)

    def _record(self, method):
        with self._counts_lock:
            key = (method, self.path)
            self.method_counts[key] = self.method_counts.get(key, 0) + 1

    def do_HEAD(self):
        self._record("HEAD")
        self._respond(head_only=True)

    def do_GET(self):
        self._record("GET")
        with self._counts_lock:
            remaining = self.throttle_gets.get(self.path, 0)
            if remaining:
                self.throttle_gets[self.path] = remaining - 1
        if remaining:
            body = b'{"code": 429, "message": "Too Many Requests"}'
            self.send_response(429)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._respond(head_only=False)

    def _respond(self, head_only):
        if self.path in self.fail_paths:
            self.send_response(500)
            self.end_headers()
            return
        if self.path not in self.routes:
            self.send_response(404)
            self.end_headers()
            return

        data, supports_range = self.routes[self.path]
        send_length = self.path not in self.no_content_length
        range_header = self.headers.get("Range") if not head_only else None

        if range_header and supports_range:
            spec = range_header.replace("bytes=", "")
            start_s, end_s = spec.split("-")
            start = int(start_s)
            end = int(end_s) if end_s else len(data) - 1
            chunk = data[start : end + 1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
            self.send_header("Content-Length", str(len(chunk)))
            if supports_range:
                self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            if not head_only:
                self.wfile.write(chunk)
            return

        self.send_response(200)
        if send_length:
            self.send_header("Content-Length", str(len(data)))
        if supports_range:
            self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        if not head_only:
            self.wfile.write(data)

    def log_message(self, format, *args):
        pass  # keep test output quiet


class _TestServer:
    """A background ThreadingHTTPServer bound to localhost:<random port>."""

    def __init__(self):
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _RangeHTTPHandler)
        self.port = self.httpd.server_port
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def register(self, path, data, supports_range=True, content_length=True):
        _RangeHTTPHandler.routes[path] = (data, supports_range)
        if not content_length:
            _RangeHTTPHandler.no_content_length.add(path)

    def fail(self, path):
        _RangeHTTPHandler.fail_paths.add(path)

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class _DownloadEngineTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = _TestServer()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def setUp(self):
        _RangeHTTPHandler.routes.clear()
        _RangeHTTPHandler.fail_paths.clear()
        _RangeHTTPHandler.no_content_length.clear()
        _RangeHTTPHandler.method_counts.clear()
        _RangeHTTPHandler.throttle_gets.clear()
        self.tmp_dir = tempfile.mkdtemp(prefix="bdc_dl_engine_test_")
        self.addCleanup(self._rm_tmp_dir)

    def _rm_tmp_dir(self):
        import shutil

        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _dest(self, name="out.bin"):
        return os.path.join(self.tmp_dir, name)


class TestDownloadFileSingleStream(_DownloadEngineTestCase):
    def test_small_file_reconstructs_byte_perfect(self):
        from bdc_loader_plugin.core import download_engine as module

        payload = os.urandom(4096)
        self.server.register("/small.bin", payload, supports_range=True)
        dest = self._dest()

        module.download_file(self.server.url("/small.bin"), dest, max_workers=8)

        with open(dest, "rb") as f:
            self.assertEqual(f.read(), payload)

    def test_server_without_accept_ranges_falls_back_to_single_stream(self):
        from bdc_loader_plugin.core import download_engine as module

        payload = os.urandom(20000)
        self.server.register("/norange.bin", payload, supports_range=False)
        dest = self._dest()

        with patch.object(module, "MIN_SEGMENT_SIZE", 1024):
            module.download_file(self.server.url("/norange.bin"), dest, max_workers=8)

        with open(dest, "rb") as f:
            self.assertEqual(f.read(), payload)


class TestDownloadFileSegmented(_DownloadEngineTestCase):
    def test_large_file_splits_into_segments_and_reassembles_correctly(self):
        from bdc_loader_plugin.core import download_engine as module

        # Deterministic, non-repeating payload so a byte-offset bug in the
        # segment writer would actually change the checksum, not silently
        # produce a plausible-looking-but-wrong file.
        payload = bytes((i * 2654435761) % 256 for i in range(200_000))
        self.server.register("/large.bin", payload, supports_range=True)
        dest = self._dest()

        with patch.object(module, "MIN_SEGMENT_SIZE", 4096):
            module.download_file(self.server.url("/large.bin"), dest, max_workers=8)

        with open(dest, "rb") as f:
            downloaded = f.read()
        self.assertEqual(len(downloaded), len(payload))
        self.assertEqual(hashlib.sha256(downloaded).hexdigest(), hashlib.sha256(payload).hexdigest())

    def test_progress_callback_sums_to_total_bytes(self):
        from bdc_loader_plugin.core import download_engine as module

        payload = os.urandom(100_000)
        self.server.register("/progress.bin", payload, supports_range=True)
        dest = self._dest()
        counter = module.ProgressCounter()

        with patch.object(module, "MIN_SEGMENT_SIZE", 4096):
            module.download_file(self.server.url("/progress.bin"), dest, max_workers=4, progress_cb=counter.add)

        self.assertEqual(counter.value(), len(payload))

    def test_server_rejecting_range_mid_download_raises(self):
        """If Accept-Ranges was advertised but a Range request somehow doesn't
        come back as 206, that segment must fail loudly, not silently write
        the wrong bytes at the wrong offset."""
        from bdc_loader_plugin.core import download_engine as module

        payload = os.urandom(50_000)
        # Route advertises no range support even though the probe HEAD would
        # have seen Accept-Ranges on a real flaky server; force the code path
        # by monkeypatching probe() to lie about support.
        self.server.register("/flaky.bin", payload, supports_range=False)
        dest = self._dest()

        with (
            patch.object(module, "MIN_SEGMENT_SIZE", 4096),
            patch.object(module, "probe", return_value=(len(payload), True)),
        ):
            with self.assertRaises(Exception):
                module.download_file(self.server.url("/flaky.bin"), dest, max_workers=4)


class TestDownloadFiles(_DownloadEngineTestCase):
    def test_multiple_files_all_succeed_and_are_byte_perfect(self):
        from bdc_loader_plugin.core import download_engine as module

        payloads = {f"/f{i}.bin": os.urandom(5000) for i in range(4)}
        for path, data in payloads.items():
            self.server.register(path, data, supports_range=True)

        tasks = [(self.server.url(path), self._dest(f"out{i}.bin")) for i, path in enumerate(payloads)]
        errors = module.download_files(tasks, max_workers=8)

        self.assertEqual(errors, [])
        for (path, _data), (_url, dest) in zip(payloads.items(), tasks):
            with open(dest, "rb") as f:
                self.assertEqual(f.read(), payloads[path])

    def test_failing_url_is_reported_and_partial_file_removed(self):
        from bdc_loader_plugin.core import download_engine as module

        self.server.register("/ok.bin", os.urandom(2000), supports_range=True)
        self.server.fail("/bad.bin")
        dest_ok = self._dest("ok.bin")
        dest_bad = self._dest("bad.bin")

        errors = module.download_files(
            [(self.server.url("/ok.bin"), dest_ok), (self.server.url("/bad.bin"), dest_bad)],
            max_workers=4,
        )

        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0][1], dest_bad)
        self.assertTrue(os.path.exists(dest_ok))
        self.assertFalse(os.path.exists(dest_bad))

    def test_empty_task_list_returns_no_errors(self):
        from bdc_loader_plugin.core import download_engine as module

        self.assertEqual(module.download_files([]), [])

    def test_cancel_check_stops_further_files(self):
        from bdc_loader_plugin.core import download_engine as module

        payloads = {f"/c{i}.bin": os.urandom(2000) for i in range(6)}
        for path, data in payloads.items():
            self.server.register(path, data, supports_range=True)
        tasks = [(self.server.url(path), self._dest(f"c{i}.bin")) for i, path in enumerate(payloads)]

        state = {"n": 0}

        def cancel_after_first():
            state["n"] += 1
            return state["n"] > 2  # let a couple of probes/segments through, then stop

        module.download_files(tasks, max_workers=2, cancel_check=cancel_after_first)
        finished = [dest for _url, dest in tasks if os.path.exists(dest)]
        self.assertLess(len(finished), len(tasks))
        leftovers = [name for name in os.listdir(self.tmp_dir) if name.endswith(".part")]
        self.assertEqual(leftovers, [])

    def test_cancel_before_the_start_downloads_nothing(self):
        from bdc_loader_plugin.core import download_engine as module

        self.server.register("/never.bin", os.urandom(2000), supports_range=True)
        dest = self._dest("never.bin")

        errors = module.download_files([(self.server.url("/never.bin"), dest)], cancel_check=lambda: True)

        self.assertEqual(errors, [])
        self.assertEqual(os.listdir(self.tmp_dir), [])
        self.assertEqual(_RangeHTTPHandler.count("GET", "/never.bin"), 0)

    def test_cancel_during_a_transfer_removes_the_partial_file(self):
        from bdc_loader_plugin.core import download_engine as module

        self.server.register("/stop.bin", os.urandom(300_000), supports_range=True)
        dest = self._dest("stop.bin")
        seen = []

        def cancel_after_some_bytes():
            seen.append(1)
            return len(seen) > 3

        with patch.object(module, "CHUNK_SIZE", 4096):
            errors = module.download_files(
                [(self.server.url("/stop.bin"), dest)], max_workers=1, cancel_check=cancel_after_some_bytes
            )

        self.assertEqual(len(errors), 1)
        self.assertEqual(os.listdir(self.tmp_dir), [])

    def test_active_cb_reports_files_starting_and_finishing(self):
        from bdc_loader_plugin.core import download_engine as module

        payloads = {f"/a{i}.bin": os.urandom(2000) for i in range(4)}
        for path, data in payloads.items():
            self.server.register(path, data, supports_range=True)
        tasks = [(self.server.url(path), self._dest(f"a{i}.bin")) for i, path in enumerate(payloads)]

        deltas = []
        lock = threading.Lock()

        def active_cb(delta):
            with lock:
                deltas.append(delta)

        errors = module.download_files(tasks, max_workers=4, active_cb=active_cb)

        self.assertEqual(errors, [])
        self.assertEqual(len(deltas), 8)  # one +1 and one -1 per file
        self.assertEqual(sum(deltas), 0)  # every start is matched by an end
        running = 0
        for d in deltas:
            running += d
            self.assertGreaterEqual(running, 0)


class TestProbeReuse(_DownloadEngineTestCase):
    """The masked-prefetch path probes every tile once for a size hint, then
    transfers it — historically two HEADs per file. probe_all + probes= collapse
    that to one HEAD reused for the transfer, while the no-probe path keeps its
    own HEAD for backward compatibility."""

    def test_probe_all_returns_size_and_range_per_url(self):
        from bdc_loader_plugin.core import download_engine as module

        self.server.register("/a.bin", os.urandom(1000), supports_range=True)
        self.server.register("/b.bin", os.urandom(2000), supports_range=False)
        urls = [self.server.url("/a.bin"), self.server.url("/b.bin")]

        result = module.probe_all(urls)

        self.assertEqual(result[urls[0]], (1000, True))
        self.assertEqual(result[urls[1]], (2000, False))

    def test_probe_all_empty_returns_empty_mapping(self):
        from bdc_loader_plugin.core import download_engine as module

        self.assertEqual(module.probe_all([]), {})

    def test_probe_all_error_maps_to_zero_false(self):
        """A HEAD that raises (unreachable host) must surface as (0, False), not
        crash probe_all — the download then falls back to a single stream."""
        from bdc_loader_plugin.core import download_engine as module

        bad = "http://127.0.0.1:1/nope"
        result = module.probe_all([bad])

        self.assertEqual(result[bad], (0, False))

    def test_no_second_head_when_probe_reused(self):
        payload = os.urandom(30000)
        self.server.register("/reuse.bin", payload, supports_range=True)
        url = self.server.url("/reuse.bin")
        dest = self._dest("reuse.bin")
        from bdc_loader_plugin.core import download_engine as module

        probes = module.probe_all([url])
        self.assertEqual(_RangeHTTPHandler.count("HEAD", "/reuse.bin"), 1)

        errors = module.download_files([(url, dest)], probes=probes)

        self.assertEqual(errors, [])
        # The single probe_all HEAD is reused: 1 HEAD total, 1 GET, byte-perfect.
        self.assertEqual(_RangeHTTPHandler.count("HEAD", "/reuse.bin"), 1)
        self.assertEqual(_RangeHTTPHandler.count("GET", "/reuse.bin"), 1)
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), payload)

    def test_without_probe_download_files_issues_its_own_head(self):
        """Documents the duplication the probes= path removes: with no probe
        supplied, download_files HEADs the file itself, so probe_all + this call
        would total two HEADs for the same resource."""
        payload = os.urandom(30000)
        self.server.register("/dup.bin", payload, supports_range=True)
        url = self.server.url("/dup.bin")
        dest = self._dest("dup.bin")
        from bdc_loader_plugin.core import download_engine as module

        module.probe_all([url])
        self.assertEqual(_RangeHTTPHandler.count("HEAD", "/dup.bin"), 1)

        module.download_files([(url, dest)])  # no probes -> own HEAD

        self.assertEqual(_RangeHTTPHandler.count("HEAD", "/dup.bin"), 2)

    def test_reused_probe_without_content_length_single_streams(self):
        """A tile whose HEAD carries no Content-Length probes as size 0; the
        reused (0, True) result still yields a correct single-stream GET."""
        payload = os.urandom(20000)
        self.server.register("/nolen.bin", payload, supports_range=True, content_length=False)
        url = self.server.url("/nolen.bin")
        dest = self._dest("nolen.bin")
        from bdc_loader_plugin.core import download_engine as module

        probes = module.probe_all([url])
        self.assertEqual(probes[url], (0, True))

        errors = module.download_files([(url, dest)], probes=probes)

        self.assertEqual(errors, [])
        self.assertEqual(_RangeHTTPHandler.count("HEAD", "/nolen.bin"), 1)
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), payload)

    def test_reused_probe_without_range_support_single_streams(self):
        """A reused (size, False) probe forces the single-stream path even for a
        large file, and still transfers it byte-perfect with no extra HEAD."""
        payload = os.urandom(60000)
        self.server.register("/norange2.bin", payload, supports_range=False)
        url = self.server.url("/norange2.bin")
        dest = self._dest("norange2.bin")
        from bdc_loader_plugin.core import download_engine as module

        with patch.object(module, "MIN_SEGMENT_SIZE", 4096):
            probes = module.probe_all([url])
            self.assertEqual(probes[url], (len(payload), False))
            errors = module.download_files([(url, dest)], probes=probes)

        self.assertEqual(errors, [])
        self.assertEqual(_RangeHTTPHandler.count("HEAD", "/norange2.bin"), 1)
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), payload)

    def test_download_file_uses_probe_result_without_heading(self):
        """download_file given probe_result must not HEAD at all — the caller
        already did. (download_files hands probe results down this way.)"""
        payload = os.urandom(5000)
        self.server.register("/direct.bin", payload, supports_range=True)
        url = self.server.url("/direct.bin")
        dest = self._dest("direct.bin")
        from bdc_loader_plugin.core import download_engine as module

        module.download_file(url, dest, max_workers=4, probe_result=(len(payload), False))

        self.assertEqual(_RangeHTTPHandler.count("HEAD", "/direct.bin"), 0)
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), payload)

    def test_url_missing_from_probes_falls_back_to_own_head(self):
        """download_files with a probes mapping that lacks a given url must
        still fetch it, probing that one file itself."""
        payload = os.urandom(4000)
        self.server.register("/missing.bin", payload, supports_range=True)
        url = self.server.url("/missing.bin")
        dest = self._dest("missing.bin")
        from bdc_loader_plugin.core import download_engine as module

        errors = module.download_files([(url, dest)], probes={"http://other/x": (10, True)})

        self.assertEqual(errors, [])
        self.assertEqual(_RangeHTTPHandler.count("HEAD", "/missing.bin"), 1)
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), payload)


class TestProgressCounter(unittest.TestCase):
    """ProgressCounter's two-discipline contract: add() accumulates signed
    deltas, set() overwrites with an absolute value, value() reads the total.
    The counter stores whatever it is given and does no range shaping."""

    def test_fresh_counter_reads_zero(self):
        from bdc_loader_plugin.core import download_engine as module

        self.assertEqual(module.ProgressCounter().value(), 0)

    def test_add_accumulates_positive_deltas(self):
        from bdc_loader_plugin.core import download_engine as module

        counter = module.ProgressCounter()
        counter.add(100)
        counter.add(256)
        self.assertEqual(counter.value(), 356)

    def test_add_accepts_negative_deltas(self):
        """The active-download counter relies on add(-1) to decrement, so a
        signed delta must lower the total, not be rejected or clamped."""
        from bdc_loader_plugin.core import download_engine as module

        counter = module.ProgressCounter()
        counter.add(1)
        counter.add(1)
        counter.add(-1)
        self.assertEqual(counter.value(), 1)

    def test_set_overwrites_with_absolute_value(self):
        from bdc_loader_plugin.core import download_engine as module

        counter = module.ProgressCounter()
        counter.add(10_000)
        counter.set(3)
        self.assertEqual(counter.value(), 3)

    def test_set_keeps_fractions_and_out_of_unit_values_unshaped(self):
        """A GDAL callback feeds set() a 0.0-1.0 fraction, but the counter must
        not clamp: it stores 0.5 as 0.5 and even a >1.0 value verbatim, leaving
        any percent clamping to the UI consumer."""
        from bdc_loader_plugin.core import download_engine as module

        counter = module.ProgressCounter()
        counter.set(0.5)
        self.assertEqual(counter.value(), 0.5)
        counter.set(1.5)
        self.assertEqual(counter.value(), 1.5)

    def test_concurrent_adds_sum_without_lost_updates(self):
        """Many threads each adding to the same counter must land on the exact
        arithmetic total — the lock makes each add() atomic."""
        from bdc_loader_plugin.core import download_engine as module

        counter = module.ProgressCounter()
        n_threads = 16
        per_thread = 5000

        def worker():
            for _ in range(per_thread):
                counter.add(1)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(counter.value(), n_threads * per_thread)


class TestThrottling(_DownloadEngineTestCase):
    """429 answers lower the connection budget instead of failing the download."""

    def setUp(self):
        super().setUp()
        from bdc_loader_plugin.core import download_engine

        self.engine = download_engine
        download_engine.reset_throttling()
        self.addCleanup(download_engine.reset_throttling)
        patcher = patch.object(download_engine, "_THROTTLE_PAUSE_S", 0.0)
        patcher.start()
        self.addCleanup(patcher.stop)
        backoff = patch.object(download_engine._ThrottleAwareRetry, "get_backoff_time", lambda self: 0)
        backoff.start()
        self.addCleanup(backoff.stop)

    def test_burst_of_429_still_gives_a_byte_perfect_file_and_lowers_the_budget(self):
        data = os.urandom(40 * 1024 * 1024)
        self.server.register("/big.tif", data)
        _RangeHTTPHandler.throttle_gets["/big.tif"] = 3
        dest = self._dest("big.tif")
        progress = []

        errors = self.engine.download_files([(self.server.url("/big.tif"), dest)], 24, progress.append)

        self.assertEqual(errors, [])
        with open(dest, "rb") as f:
            self.assertEqual(hashlib.sha256(f.read()).hexdigest(), hashlib.sha256(data).hexdigest())
        self.assertEqual(sum(progress), len(data))
        self.assertEqual(self.engine.effective_workers(24), 12)

    def test_transfer_is_retried_after_the_session_gives_up_on_429(self):
        # Four 429s in a row exhaust urllib3's three retries; the engine then
        # lowers the budget and tries the transfer again.
        data = b"x" * 1000
        self.server.register("/small.tif", data)
        _RangeHTTPHandler.throttle_gets["/small.tif"] = 4
        dest = self._dest("small.tif")
        progress = []

        errors = self.engine.download_files([(self.server.url("/small.tif"), dest)], 24, progress.append)

        self.assertEqual(errors, [])
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), data)
        self.assertEqual(sum(progress), len(data))
        self.assertLess(self.engine.effective_workers(24), 24)

    def test_server_that_never_stops_throttling_is_reported_as_an_error(self):
        self.server.register("/busy.tif", b"y" * 1000)
        _RangeHTTPHandler.throttle_gets["/busy.tif"] = 10_000

        errors = self.engine.download_files([(self.server.url("/busy.tif"), self._dest("busy.tif"))], 24)

        self.assertEqual(len(errors), 1)
        self.assertIn("429", errors[0][2])
        self.assertFalse(os.path.exists(self._dest("busy.tif")))


class TestConnectionLimiter(unittest.TestCase):
    def setUp(self):
        from bdc_loader_plugin.core import download_engine

        self.engine = download_engine
        download_engine.reset_throttling()
        self.addCleanup(download_engine.reset_throttling)

    def test_cap_holds_under_contention(self):
        import time

        limiter = self.engine.ConnectionLimiter(5)
        active, peak = [0], [0]
        lock = threading.Lock()

        def work():
            with limiter:
                with lock:
                    active[0] += 1
                    peak[0] = max(peak[0], active[0])
                time.sleep(0.01)
                with lock:
                    active[0] -= 1

        threads = [threading.Thread(target=work) for _ in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(peak[0], 5)

    def test_throttle_halves_down_to_the_floor_once_per_cooldown(self):
        now = [100.0]
        limiter = self.engine.ConnectionLimiter(24, clock=lambda: now[0])

        self.assertTrue(limiter.throttle())
        self.assertEqual(limiter.limit, 12)
        self.assertFalse(limiter.throttle())  # same burst
        self.assertEqual(limiter.limit, 12)
        for _ in range(5):
            now[0] += 10
            limiter.throttle()
        self.assertEqual(limiter.limit, self.engine.MIN_WORKERS)

    def test_lowered_budget_carries_over_to_later_downloads(self):
        self.assertEqual(self.engine.effective_workers(24), 24)
        self.engine.ConnectionLimiter(24).throttle()
        self.assertEqual(self.engine.effective_workers(24), 12)
        self.assertEqual(self.engine.effective_workers(8), 8)

    def test_retry_reports_429_and_keeps_its_callback_across_copies(self):
        calls = []
        retry = self.engine._ThrottleAwareRetry(total=3, status_forcelist=[429], on_throttle=lambda: calls.append(1))
        response = type("R", (), {"status": 429, "get_redirect_location": lambda self: None, "headers": {}})()

        retry = retry.increment("GET", "/x", response=response)
        retry.increment("GET", "/x", response=response)

        self.assertEqual(len(calls), 2)
        self.assertIsNotNone(retry.on_throttle)


class _CutResponse:
    """A response whose body ends before the length it announced."""

    def __init__(self, status_code, announced, sent):
        self.status_code = status_code
        self.headers = {"Content-Length": str(announced)}
        self._body = b"x" * sent

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        yield self._body

    def close(self):
        pass


class _CutSession:
    def __init__(self, response):
        self.response = response

    def get(self, url, **kwargs):
        return self.response


class TestIncompleteTransfers(_DownloadEngineTestCase):
    """urllib3 1.x ends ``iter_content`` quietly when the server closes early,
    so the engine counts the bytes itself."""

    def test_a_stream_shorter_than_its_content_length_is_an_error(self):
        from bdc_loader_plugin.core import download_engine as module

        session = _CutSession(_CutResponse(200, announced=1000, sent=400))
        with self.assertRaisesRegex(RuntimeError, "400 of 1000"):
            module._stream_whole("http://x/a", self._dest(), session, None, None, timeout=5)

    def test_a_byte_range_shorter_than_requested_is_an_error(self):
        from bdc_loader_plugin.core import download_engine as module

        dest = self._dest()
        with open(dest, "wb") as f:
            f.truncate(1000)
        session = _CutSession(_CutResponse(206, announced=500, sent=200))
        with self.assertRaisesRegex(RuntimeError, "200 of 500"):
            module._download_segment("http://x/a", dest, 500, 999, session, None, None, 5)

    def test_bytes_arrive_in_a_part_file_until_the_download_ends(self):
        from bdc_loader_plugin.core import download_engine as module

        payload = os.urandom(200_000)
        self.server.register("/large_part.bin", payload, supports_range=True)
        dest = self._dest()
        states = []

        def progress(_n):
            states.append((os.path.exists(dest), os.path.exists(dest + ".part")))

        with patch.object(module, "MIN_SEGMENT_SIZE", 50_000):
            module.download_file(self.server.url("/large_part.bin"), dest, max_workers=4, progress_cb=progress)

        self.assertTrue(states)
        self.assertEqual(set(states), {(False, True)})
        self.assertFalse(os.path.exists(dest + ".part"))
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), payload)

    def test_a_failed_download_leaves_neither_the_file_nor_its_part(self):
        from bdc_loader_plugin.core import download_engine as module

        dest = self._dest()
        session = _CutSession(_CutResponse(200, announced=1000, sent=400))
        with self.assertRaises(RuntimeError):
            module.download_file("http://x/a", dest, max_workers=1, session=session, probe_result=(1000, False))
        self.assertEqual(os.listdir(self.tmp_dir), [])


if __name__ == "__main__":
    unittest.main()
