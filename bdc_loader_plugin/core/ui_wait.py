"""The UI thread waiting on work that runs in workers.

The UI thread never blocks on a worker. It waits in slices of
``POLL_INTERVAL_S`` and runs ``QCoreApplication.processEvents()`` between
them, so the window repaints and the Cancel button keeps working.
"""

import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from concurrent.futures import TimeoutError as _FutureTimeout

from qgis.PyQt.QtCore import QCoreApplication

POLL_INTERVAL_S = 0.05


class WaitCancelled(Exception):
    """The user cancelled while the UI thread was waiting; the worker finishes on its own."""


def wait_for(future, budget_s=None, on_wait=None, cancelled=None):
    """Return ``future.result()`` while the UI thread keeps processing events.

    ``on_wait`` runs on the UI thread after each slice without a result.
    Raises TimeoutError after ``budget_s`` seconds and WaitCancelled as soon
    as ``cancelled()`` is true.
    """
    deadline = None if budget_s is None else time.monotonic() + budget_s
    while True:
        try:
            return future.result(timeout=POLL_INTERVAL_S)
        except _FutureTimeout:
            if cancelled and cancelled():
                raise WaitCancelled() from None
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError(f"no answer in {budget_s} s") from None
            if on_wait:
                on_wait()
            QCoreApplication.processEvents()


def run_in_worker(fn, *args, budget_s=None, on_wait=None, cancelled=None, **kwargs):
    """Return ``fn(*args, **kwargs)`` run in a worker, waited for with wait_for.

    On a timeout or a cancel the worker is left to finish on its own and its
    result is dropped.
    """
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        return wait_for(executor.submit(fn, *args, **kwargs), budget_s, on_wait, cancelled)
    finally:
        executor.shutdown(wait=False)


def wait_slice(pending):
    """Wait one slice for any of the futures in ``pending``, then process events.

    Returns ``(done, still_pending)``.
    """
    done, pending = wait(pending, timeout=POLL_INTERVAL_S, return_when=FIRST_COMPLETED)
    QCoreApplication.processEvents()
    return done, pending
