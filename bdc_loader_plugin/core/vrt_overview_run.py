"""Builds the local overviews of a load in parallel, within a time budget, after the VRTs are written."""

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from qgis.core import (
    QgsSettings,
)
from qgis.PyQt.QtCore import QCoreApplication

from ..i18n import count_label, tr
from ..logger import info as _log_info
from ..logger import warning as _log_warning
from .overviews import OVERVIEW_NOT_NEEDED, build_overview, remote_vrt_streams_full_raster
from .render_ranges import estimate_vrt_render_ranges
from .ui_wait import wait_slice
from .vrt_builder import (
    vrt_has_direct_remote_source,
)

# Phase 2.5 runs on the UI thread while worker threads read remote rasters, so
# it needs a hard ceiling: layers still load without an overview, but a stalled
# remote read must never hold the dialog.
_OVERVIEW_PHASE_BUDGET_S = 90.0


def _abandon_pending(pending, ovr_futures, render_ranges_cache):
    """Drop still-running preparation futures and mark their VRTs as sampled.

    Seeding the render-range cache with an empty result is what stops
    _precompute_render_ranges from queueing the same slow remote reads again,
    which would put back the UI stall this bail-out just escaped. A worker that
    finishes later still publishes its .ovr atomically, so a later load picks
    it up.
    """
    for future in pending:
        future.cancel()
        render_ranges_cache.setdefault(ovr_futures[future], {})


# Seconds without a finished layer after which the status says the wait is
# on the BDC server: the first read of each image there takes 1 to 6 s.
_SERVER_WAIT_S = 10.0

# Rows and columns sampled for the stretch of a source without overviews.
_FULL_STREAM_SAMPLE = 64


@dataclass
class _OverviewOutcome:
    """What the overview phase did with the remote VRTs."""

    built: int = 0
    not_needed: int = 0
    abandoned: int = 0
    failed: list = field(default_factory=list)
    streams_full: list = field(default_factory=list)


def _prepare_remote_layer(vrt_path, cutline, want_overview):
    """(overview path, render ranges, streams the full raster) of one remote VRT; worker thread.

    A source without overviews is sampled with fewer rows: every sampled row
    costs one remote strip. Without a range, QGIS samples the scene itself
    when the layer is built, on the UI thread; here it is done off the UI thread.
    """
    ovr = build_overview(vrt_path, cutline) if want_overview else None
    streams_full = ovr is None and remote_vrt_streams_full_raster(vrt_path)
    sample = _FULL_STREAM_SAMPLE if streams_full else 256
    return ovr, estimate_vrt_render_ranges(vrt_path, sample_size=sample), streams_full


class VrtOverviewRun:
    """Builds the local overviews of a load in parallel, within a time budget, after the VRTs are written."""

    # ------------------------------------------------------------------
    # Phase 2.5: overviews
    # ------------------------------------------------------------------
    def _build_overviews(self, vrt_paths):
        """Prepare remote-sourced VRTs off the UI thread: build local overviews
        and precompute per-band display ranges.

        Both steps run in worker threads, so no /vsicurl/ sampling reaches the
        UI thread when the layers are created. The render range is cached by
        vrt_path (always, even when empty) so _open_raster_layers applies it
        without re-sampling. Overview generation honors the user setting; range
        precomputation always runs and reads the local overview when one was
        built, otherwise the remote VRT, but never on the UI thread.
        """

        want_overview = QgsSettings().value("bdc_loader/generate_ovr", True, type=bool)
        if not want_overview:
            _log_info("Overview generation disabled by user setting")
        remote_vrts = [(vp, gn) for vp, ln, gn in vrt_paths if vrt_has_direct_remote_source(vp)]
        if not remote_vrts:
            return
        self._display_status = None
        self.progress_bar.setFormat(tr("Preparing for display %v/%m"))
        self.progress_bar.setRange(0, len(remote_vrts))
        self.progress_bar.setValue(0)
        self._show_display_progress(0, len(remote_vrts), 0.0, False, want_overview)
        QCoreApplication.processEvents()
        outcome = self._run_overview_jobs(remote_vrts, want_overview)
        self._report_overview_outcome(outcome, len(remote_vrts), want_overview)

    def _run_overview_jobs(self, remote_vrts, want_overview):
        """Prepare every remote VRT in up to 4 workers, within the phase's time budget.

        Four, not the profile's thread count: more workers make some loads
        much slower, as the BDC holds back an address with many requests open.
        """
        outcome = _OverviewOutcome()
        executor = ThreadPoolExecutor(max_workers=min(4, len(remote_vrts)))
        try:
            futures = {
                executor.submit(_prepare_remote_layer, vp, self._cutline_for_group(gn), want_overview): vp
                for vp, gn in remote_vrts
            }
            pending = set(futures)
            done_count = 0
            start = last_done = time.monotonic()
            deadline = start + _OVERVIEW_PHASE_BUDGET_S
            # Waiting in short slices keeps processEvents() running while the
            # workers are busy, so the dialog stays responsive and the cancel
            # button keeps working. Blocking on the futures themselves would
            # freeze the UI thread for as long as the slowest remote read.
            while pending:
                if self._vrt_cancelled:
                    _abandon_pending(pending, futures, self._render_ranges_cache)
                    break
                if time.monotonic() > deadline:
                    outcome.abandoned = len(pending)
                    _abandon_pending(pending, futures, self._render_ranges_cache)
                    break
                done, pending = wait_slice(pending)
                now = time.monotonic()
                for future in done:
                    done_count += 1
                    last_done = now
                    self.progress_bar.setValue(done_count)
                    self._record_overview(futures[future], future, outcome, want_overview)
                stalled = now - last_done > _SERVER_WAIT_S
                self._show_display_progress(done_count, len(remote_vrts), now - start, stalled, want_overview)
        finally:
            executor.shutdown(wait=False)
        return outcome

    def _show_display_progress(self, done, total, elapsed, stalled, want_overview):
        """Say which step runs, how far it is and, when no layer finished for a while, that the BDC is slow."""
        # Which layers take an overview is only known once the workers open
        # them, so the text names both steps rather than promising overviews
        # that a non-cloud-optimized source does not get.
        step = "overview and contrast" if want_overview else "contrast"
        text = f"Preparing layers for display ({step}): {done}/{total} ({elapsed:.0f} s)"
        if stalled:
            text += ", waiting for the BDC server"
        # The loop polls many times a second; the line changes once a second at most.
        if text != getattr(self, "_display_status", None):
            self._display_status = text
            self._set_status(text, "info")

    def _record_overview(self, vrt_path, future, outcome, want_overview):
        try:
            ovr_path, render_ranges, streams_full = future.result()
        except Exception as exc:
            outcome.failed.append(vrt_path)
            _log_warning(f"Failed to prepare remote layer: {exc}")
            return
        self._render_ranges_cache[vrt_path] = render_ranges
        if streams_full:
            # Nothing was generated for this layer by design, so it is not an
            # overview failure.
            outcome.streams_full.append(vrt_path)
        elif ovr_path is OVERVIEW_NOT_NEEDED:
            # Small enough to draw without one (a crop, say).
            outcome.not_needed += 1
        elif want_overview:
            if ovr_path:
                outcome.built += 1
            else:
                outcome.failed.append(vrt_path)

    def _report_overview_outcome(self, outcome, remote_count, want_overview):
        eligible = remote_count - len(outcome.streams_full) - outcome.not_needed
        if want_overview:
            if outcome.failed and not self._vrt_cancelled:
                message = (
                    f"{len(outcome.failed)} of {count_label(eligible, 'overview', 'overviews')} could not be created; "
                    "those layers draw directly from the BDC."
                )
                _log_warning(message)
                self._set_status(message, "warning")
            elif eligible:
                _log_info(f"Overviews: {outcome.built}/{eligible} generated")
        # These layers stream every full-resolution block they display, so
        # zoomed-out rendering is slow and can fail outright against a
        # rate-limited server. Downloading is the workable path, and saying so
        # beats letting the canvas look broken. Reported whether or not
        # overviews are enabled: the display-range sampling is skipped for the
        # same reason, so nothing was generated for these layers either way.
        if outcome.streams_full and not self._vrt_cancelled:
            message = (
                f"{len(outcome.streams_full)} of {count_label(remote_count, 'layer', 'layers')} not "
                "cloud-optimized: no overview or contrast was prepared, and drawing reads each full image from "
                "the BDC. Download these images for fast local layers."
            )
            _log_warning(message)
            self._set_status(message, "warning")
        # Reported last so the timeout stays the visible status: it explains a
        # slow load better than the overview tally it would otherwise sit under.
        if outcome.abandoned:
            message = (
                f"Preparing {outcome.abandoned} of {count_label(remote_count, 'layer', 'layers')} for display took "
                f"over {_OVERVIEW_PHASE_BUDGET_S:.0f} s; they load without overview or contrast."
            )
            _log_warning(message)
            self._set_status(message, "warning")
