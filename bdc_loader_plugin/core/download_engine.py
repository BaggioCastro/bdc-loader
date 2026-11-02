# -*- coding: utf-8 -*-
"""
Accelerated HTTP download engine — thread-safe, pure functions with no Qt dependency.

Server-side throughput is capped per connection and chunk_size has no effect on
it, while concurrent connections scale throughput close to linearly. So the
fast path is more concurrent HTTP connections: either across files (multiple
bands/tiles at once) or, when there are only one or two files to fetch, by
splitting a single file into byte-range segments downloaded in parallel — this
module does both, sharing one connection budget between them.

The server also limits how many connections one client may hold. When it
answers 429 (Too Many Requests) the budget is halved, down to
MIN_WORKERS, and stays lowered for the rest of the process, so a client on a
throttled network settles at what the server accepts instead of failing.
"""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from ..net import METADATA_S, TRANSFER_S

# Each connection to data.inpe.br carries a limited rate, so the transfer
# scales with the connection count up to a ceiling the server tolerates.
DEFAULT_MAX_WORKERS = 24
MIN_WORKERS = 4
MAX_WORKERS_LIMIT = 48
# Below this, segmenting a file adds more HTTP overhead (extra requests, extra
# TCP slow starts) than the parallelism saves.
MIN_SEGMENT_SIZE = 4 * 1024 * 1024
CHUNK_SIZE = 256 * 1024


class DownloadCancelled(Exception):
    """Raised to unwind a download early; callers should catch and clean up."""


class ProgressCounter:
    """Thread-safe scalar shared between worker threads and the UI thread.

    Producers on worker threads write with exactly one of two disciplines,
    chosen by the caller and never mixed on the same counter:

    - add(delta): accumulate a signed delta onto the running total. Used for
      quantities that arrive incrementally, e.g. bytes transferred (positive
      chunks) or an active-download count (+1 when a file starts, -1 when it
      ends). Negative deltas are valid; the total may therefore rise and fall.
    - set(absolute): overwrite the total with an absolute value. Used when the
      producer already knows the current value outright, e.g. a 0.0-1.0
      fraction from a GDAL progress callback.

    value() reads the current total. Every method takes the lock, so each call
    is atomic and concurrent add()s from many threads sum without lost updates;
    the lock does not span multiple calls, so a read-modify-write across
    separate calls is still the caller's responsibility.

    This class stores whatever numbers it is given — it does not clamp to a
    unit range or reject out-of-range values. A fraction slightly past 1.0 or a
    transiently negative running total is kept as-is; any range shaping (e.g.
    min(100, int(fraction * 100)) for a percent bar) belongs in the UI layer
    that consumes value().
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._value = 0

    def add(self, delta):
        """Add a signed delta to the running total (cumulative discipline)."""
        with self._lock:
            self._value += delta

    def set(self, absolute):
        """Replace the running total with an absolute value."""
        with self._lock:
            self._value = absolute

    def value(self):
        """Return the current total."""
        with self._lock:
            return self._value


_ceiling_lock = threading.Lock()
_session_ceiling = None  # lowest budget the server accepted in this process


def effective_workers(requested):
    """``requested`` capped by any throttling seen earlier in this process."""
    requested = max(MIN_WORKERS, int(requested))
    with _ceiling_lock:
        if _session_ceiling is None:
            return requested
        return max(MIN_WORKERS, min(requested, _session_ceiling))


def _lower_session_ceiling(limit):
    global _session_ceiling
    with _ceiling_lock:
        if _session_ceiling is None or limit < _session_ceiling:
            _session_ceiling = limit


def reset_throttling():
    """Forget the connection cap learned from HTTP 429 answers.

    Called when the user saves new settings, so a changed Download
    Connections value applies in full; tests call it between cases.
    """
    global _session_ceiling
    with _ceiling_lock:
        _session_ceiling = None


class ConnectionLimiter:
    """Caps concurrent HTTP requests; ``throttle()`` halves the cap.

    Requests already running finish normally; the lower cap applies to the
    ones that start afterwards.
    """

    def __init__(self, limit, clock=time.monotonic):
        self._limit = max(MIN_WORKERS, int(limit))
        self._active = 0
        self._cond = threading.Condition()
        self._clock = clock
        self._last_throttle = None

    @property
    def limit(self):
        with self._cond:
            return self._limit

    def acquire(self):
        with self._cond:
            while self._active >= self._limit:
                self._cond.wait()
            self._active += 1

    def release(self):
        with self._cond:
            self._active -= 1
            self._cond.notify_all()

    def throttle(self):
        """Halve the cap (not below MIN_WORKERS); returns True when it changed.

        The many 429s of one burst count once: a second cut waits until
        _THROTTLE_COOLDOWN_S has passed, so the reduced cap gets a chance.
        """
        with self._cond:
            now = self._clock()
            if self._last_throttle is not None and now - self._last_throttle < _THROTTLE_COOLDOWN_S:
                return False
            self._last_throttle = now
            lowered = max(MIN_WORKERS, self._limit // 2)
            changed = lowered < self._limit
            self._limit = lowered
            self._cond.notify_all()
        if changed:
            _lower_session_ceiling(lowered)
        return changed

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_exc):
        self.release()
        return False


class _ThrottleAwareRetry(Retry):
    """urllib3 Retry that reports every 429 it retries to ``on_throttle``."""

    def __init__(self, *args, on_throttle=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.on_throttle = on_throttle

    def new(self, **kw):
        retry = super().new(**kw)
        retry.on_throttle = self.on_throttle
        return retry

    def increment(self, method=None, url=None, response=None, error=None, _pool=None, _stacktrace=None):
        if response is not None and getattr(response, "status", None) == 429 and self.on_throttle:
            self.on_throttle()
        return super().increment(method, url, response, error, _pool, _stacktrace)


def _is_throttled(exc):
    text = str(exc)
    return "429" in text or "Too Many Requests" in text


# A transfer that still meets 429 after the session's own retries is tried
# again this many times, each after lowering the budget and a short pause.
_THROTTLED_ATTEMPTS = 3
_THROTTLE_PAUSE_S = 1.0
_THROTTLE_COOLDOWN_S = 2.0


def make_session(pool_size=DEFAULT_MAX_WORKERS, on_throttle=None):
    """A requests.Session with connection pooling and retry/backoff for 429/5xx,
    sized for a caller that may issue up to pool_size concurrent requests on it.

    Rate limiting clears up quickly at the connection counts this module
    targets, so the backoff stays short and bounded — a longer exponential
    backoff would make an interactive download stall for tens of seconds
    waiting on a single retry.
    """
    session = requests.Session()
    retry = _ThrottleAwareRetry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
        on_throttle=on_throttle,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=pool_size, pool_maxsize=pool_size)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def probe(url, session, timeout=METADATA_S):
    """Return (size, supports_range) via a lightweight HEAD request. On any
    failure, returns (0, False) so callers fall back to a plain single-stream
    download rather than failing outright."""
    try:
        resp = session.head(url, timeout=timeout, allow_redirects=True)
        size = int(resp.headers.get("Content-Length", 0) or 0)
        supports_range = resp.headers.get("Accept-Ranges", "").strip().lower() == "bytes"
        return size, supports_range
    except Exception:
        return 0, False


def probe_all(urls, max_workers=DEFAULT_MAX_WORKERS, session=None):
    """Return {url: (size, supports_range)} for each distinct url via concurrent
    HEAD requests. Lets a caller both size a progress bar (sum the sizes) and
    hand each result to download_files(..., probes=...) so the transfer reuses
    it instead of issuing a second HEAD per file. Failed probes map to
    (0, False), same as probe()."""
    urls = list(dict.fromkeys(urls))  # de-duplicate, preserving first-seen order
    if not urls:
        return {}
    own_session = session is None
    session = session or make_session(max_workers)
    try:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(urls))) as executor:
            return dict(executor.map(lambda u: (u, probe(u, session)), urls))
    finally:
        if own_session:
            session.close()


def _segment_ranges(total_size, n_segments):
    segment_size = total_size // n_segments
    ranges = []
    for i in range(n_segments):
        start = i * segment_size
        end = start + segment_size - 1 if i < n_segments - 1 else total_size - 1
        ranges.append((start, end))
    return ranges


def _write_chunks(resp, f, progress_cb, cancel_check):
    """Copy the body of ``resp`` into ``f`` and return the number of bytes written."""
    received = 0
    for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
        if cancel_check and cancel_check():
            raise DownloadCancelled()
        if chunk:
            f.write(chunk)
            received += len(chunk)
            if progress_cb:
                progress_cb(len(chunk))
    return received


def _stream_whole(url, dest_path, session, progress_cb, cancel_check, timeout):
    resp = session.get(url, stream=True, timeout=timeout)
    resp.raise_for_status()
    try:
        with open(dest_path, "wb") as f:
            received = _write_chunks(resp, f, progress_cb, cancel_check)
        # A body cut short ends the iteration quietly on urllib3 1.x, so the
        # announced length is the only sign of it. A compressed body has no
        # comparable length.
        expected = resp.headers.get("Content-Length")
        if expected and "Content-Encoding" not in resp.headers and received != int(expected):
            raise RuntimeError(f"incomplete download: {received} of {expected} bytes")
    finally:
        resp.close()


def _download_segment(url, dest_path, start, end, session, progress_cb, cancel_check, timeout):
    resp = session.get(url, headers={"Range": f"bytes={start}-{end}"}, stream=True, timeout=timeout)
    try:
        if resp.status_code != 206:
            raise RuntimeError(f"server did not honor byte-range request (status {resp.status_code})")
        with open(dest_path, "r+b") as f:
            f.seek(start)
            received = _write_chunks(resp, f, progress_cb, cancel_check)
        if received != end - start + 1:
            raise RuntimeError(f"incomplete byte range {start}-{end}: {received} of {end - start + 1} bytes")
    finally:
        resp.close()


def _with_throttle_retry(transfer, limiter, progress_cb):
    """Run ``transfer(progress)`` inside a limiter slot, retrying when throttled.

    Bytes reported by a failed attempt are taken back from ``progress_cb``,
    so the progress total never counts a range twice.
    """
    for attempt in range(_THROTTLED_ATTEMPTS):
        written = [0]

        def progress(n, written=written):
            written[0] += n
            if progress_cb:
                progress_cb(n)

        try:
            with limiter:
                transfer(progress)
            return
        except DownloadCancelled:
            raise
        except Exception as exc:
            if progress_cb and written[0]:
                progress_cb(-written[0])
            if attempt == _THROTTLED_ATTEMPTS - 1 or not _is_throttled(exc):
                raise
            limiter.throttle()
            time.sleep(_THROTTLE_PAUSE_S * (attempt + 1))


def download_file(
    url,
    dest_path,
    max_workers=DEFAULT_MAX_WORKERS,
    session=None,
    progress_cb=None,
    cancel_check=None,
    probe_result=None,
    limiter=None,
):
    """Download one URL to dest_path, splitting it into up to max_workers parallel
    byte-range segments when the server supports Range requests and the file is
    large enough to be worth splitting. Falls back to a plain single-connection
    stream otherwise (small file, no Range support, or max_workers <= 1).

    probe_result, if given, is a (size, supports_range) pair already obtained for
    this url (e.g. from probe_all); it is used verbatim so this call skips its own
    HEAD. When None, this issues one HEAD via probe() as before.

    progress_cb(bytes_delta), if given, is invoked from worker threads — never
    touch Qt/UI state directly from it; aggregate into a ProgressCounter and
    poll it from the main thread instead.
    """
    limiter = limiter or ConnectionLimiter(effective_workers(max_workers))
    own_session = session is None
    session = session or make_session(max_workers, on_throttle=limiter.throttle)
    # The bytes go to a ``.part`` sibling that replaces dest_path only when every
    # byte has arrived, so an interrupted transfer never leaves a file that
    # looks finished.
    part_path = dest_path + ".part"
    try:
        size, supports_range = probe(url, session) if probe_result is None else probe_result
        n_segments = 1
        if supports_range and max_workers > 1 and size >= MIN_SEGMENT_SIZE * 2:
            n_segments = max(1, min(max_workers, size // MIN_SEGMENT_SIZE))

        if n_segments <= 1:
            _with_throttle_retry(
                lambda progress: _stream_whole(url, part_path, session, progress, cancel_check, timeout=TRANSFER_S),
                limiter,
                progress_cb,
            )
        else:
            with open(part_path, "wb") as f:
                f.truncate(size)

            def _segment(start, end):
                _with_throttle_retry(
                    lambda progress: _download_segment(
                        url, part_path, start, end, session, progress, cancel_check, TRANSFER_S
                    ),
                    limiter,
                    progress_cb,
                )

            ranges = _segment_ranges(size, n_segments)
            with ThreadPoolExecutor(max_workers=n_segments) as executor:
                futures = [executor.submit(_segment, start, end) for start, end in ranges]
                for future in as_completed(futures):
                    future.result()
        os.replace(part_path, dest_path)
    finally:
        if os.path.exists(part_path):
            try:
                os.remove(part_path)
            except OSError:
                pass
        if own_session:
            session.close()


def download_files(
    tasks, max_workers=DEFAULT_MAX_WORKERS, progress_cb=None, cancel_check=None, active_cb=None, probes=None
):
    """Download several (url, dest_path) pairs concurrently, sharing one
    connection budget between "how many files at once" and "how many segments
    per file": with N files pending, each gets roughly max_workers // N
    parallel segments (at least 1), so total concurrent connections stay near
    max_workers whether there's 1 huge file or 20 small ones.

    active_cb(delta), if given, is called with +1 when a file's download
    starts and -1 when it ends, so a caller polling from the main thread can
    show how many files are downloading at once.

    probes, if given, is a {url: (size, supports_range)} mapping (e.g. from
    probe_all) reused per file so each transfer skips its own HEAD; a url absent
    from the mapping falls back to probing itself.

    Returns a list of (url, dest_path, error_message) for failed downloads;
    empty list means everything succeeded. Stops issuing new work (but lets
    in-flight requests finish) as soon as cancel_check() returns True.
    """
    tasks = list(tasks)
    if not tasks:
        return []

    n_files = len(tasks)
    file_workers = min(max_workers, n_files)
    segments_per_file = max(1, max_workers // n_files)

    limiter = ConnectionLimiter(effective_workers(max_workers))

    def _run_one(url, dest_path):
        if active_cb:
            active_cb(1)
        try:
            probe_result = probes.get(url) if probes else None
            download_file(url, dest_path, segments_per_file, session, progress_cb, cancel_check, probe_result, limiter)
        finally:
            if active_cb:
                active_cb(-1)

    session = make_session(max_workers, on_throttle=limiter.throttle)
    errors = []
    try:
        with ThreadPoolExecutor(max_workers=file_workers) as executor:
            futures = {}
            for url, dest_path in tasks:
                if cancel_check and cancel_check():
                    break
                futures[executor.submit(_run_one, url, dest_path)] = (url, dest_path)
            for future in as_completed(futures):
                url, dest_path = futures[future]
                try:
                    future.result()
                except Exception as e:
                    errors.append((url, dest_path, str(e)))
                    if os.path.exists(dest_path):
                        try:
                            os.remove(dest_path)
                        except OSError:
                            pass
    finally:
        session.close()
    return errors
