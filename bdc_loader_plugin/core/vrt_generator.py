# -*- coding: utf-8 -*-
"""
VRT generation pipeline mixin for BDCLoaderDialog.

Provides:
- `VrtGenerator` — mixin inherited by BDCLoaderDialog that orchestrates:
  - Phase 1: Prepare VRT tasks from selected items (single-band or RGB)
  - Phase 2: Build VRTs in parallel via ThreadPoolExecutor
  - Phase 2.5: Generate local overviews for remote-sourced VRTs
  - Phase 3: Load generated VRT layers into QGIS with grouped layer tree
  - Shape-mosaic and extent-crop modes with per-feature cutlines
  - Cancel support, elapsed-time timer, and final report

Dependencies:
  core.vrt_builder — build_single_vrt, build_overview, resolve_band, GDAL opts
  stac.parsers     — extract_tile_from_item
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor

from qgis.core import (
    QgsSettings,
)
from qgis.PyQt.QtCore import QCoreApplication, Qt, QTimer
from qgis.PyQt.QtWidgets import QCheckBox, QMessageBox

from ..i18n import count_label, tr
from ..logger import info as _log_info
from ..logger import warning as _log_warning
from .band_selection import band_availability_issues
from .catalog_data import BAND_INFO, COLLECTIONS
from .overview_cache import _file_digest
from .ui_wait import wait_slice
from .vrt_builder import (
    vrt_has_direct_remote_source,
)
from .vrt_layers import VrtLayers
from .vrt_overview_run import VrtOverviewRun
from .vrt_tasks import VrtTasks, _build_task

# Phase 2 waits the same way, but abandoning a task there costs a whole layer
# rather than just its overview, so the ceiling is a backstop against a hung
# read and not a routine cutoff: build_single_vrt only reads source metadata.
_VRT_BUILD_BUDGET_S = 300.0


# Setting key for the "not cloud-optimized" pre-build warning. Stored rather
# than kept in memory so dismissing it survives a QGIS restart; the Settings
# dialog is where it gets switched back on.
_NON_COG_WARNING_KEY = "bdc_loader/warn_non_cog"


def _non_cog_warning_muted():

    return not QgsSettings().value(_NON_COG_WARNING_KEY, True, type=bool)


def _mute_non_cog_warning():

    QgsSettings().setValue(_NON_COG_WARNING_KEY, False)
    _log_info("Non-cloud-optimized warning muted; re-enable it in Settings.")


def _reads_local_files(path):
    """True when a loaded layer reads files on disk rather than the BDC server."""
    return not str(path).lower().endswith(".vrt") or not vrt_has_direct_remote_source(path)


def _source_notes(vrt_paths):
    """``["2 from your downloads", "1 streamed from the BDC"]`` for the final status."""
    on_disk = sum(1 for path, _name, _group in vrt_paths if _reads_local_files(path))
    streamed = len(vrt_paths) - on_disk
    parts = []
    if on_disk:
        parts.append(f"{on_disk} from your downloads")
    if streamed:
        parts.append(f"{streamed} streamed from the BDC")
    return parts


class VrtGenerator(VrtLayers, VrtTasks, VrtOverviewRun):
    """Provides VRT generation pipeline for BDCLoaderDialog."""

    def generate_and_load(self):
        """Build a VRT per selected result and add the layers to the project."""
        if not self._results_match_panel():
            return
        selected_items = self.get_selected_items()
        if not selected_items:
            QMessageBox.warning(self, "Warning", "Select at least one item.")
            return
        bands = self._load_bands()
        if bands is None or not self._bands_available(bands, selected_items) or not self._confirm_large_crop():
            return
        output_path = self.output_dir.text()
        os.makedirs(output_path, exist_ok=True)
        collection_id, config, band_info = self._load_collection()
        if not self._confirm_non_cog_load(config, collection_id):
            return
        resolutions = {band_info[band].get("resolution", "") for band in bands if band in band_info}

        # "stac" names layers by the STAC item id, "compact" by collection + tile
        # + date; mosaics and crops always use the compact prefix.
        naming_format = QgsSettings().value("bdc_loader/layer_naming_format", "stac", type=str)

        vrt_start_time = self._begin_vrt_run(len(selected_items))
        try:
            errors = []

            # -- Phase 1: prepare VRT tasks (main thread) --
            vrt_tasks, prebuilt_layers = self._prepare_vrt_tasks(
                selected_items,
                bands,
                len(bands),
                "-".join(bands),
                collection_id,
                len(resolutions) > 1,
                naming_format,
                errors,
            )
            # -- Phase 2: build VRTs in parallel (ThreadPoolExecutor) --
            shape_mosaic_mode = self._current_result_mode in ("shape_mosaic", "extent_crop")
            vrt_paths, errors, cancelled, vrt_total_time = self._execute_vrt_build(
                vrt_tasks, errors, vrt_start_time, shape_mosaic_mode
            )
            vrt_paths.extend(prebuilt_layers)
            if cancelled and not vrt_paths:
                self._set_status("Loading cancelled.", "warning")
                return

            # -- Phase 2.5: build local overviews & precompute render ranges off UI thread --
            self._build_overviews(vrt_paths)
            self._precompute_render_ranges(vrt_paths)

            # -- Phase 3: load layers into QGIS --
            loaded, replaced, skipped_dup = self._load_vrt_layers(vrt_paths)
        finally:
            # An error in any phase must not leave Load and Search disabled.
            self._end_vrt_run()
        # The time reported is the whole load, overviews and layer setup included.
        load_time = time.time() - vrt_start_time
        self._report_vrt_results(vrt_paths, errors, loaded, replaced, skipped_dup, load_time, cancelled)
        self._warn_empty_layers(vrt_paths)

    def _load_bands(self):
        """Real band names picked for loading (1 or 3), or None after a warning."""
        count = self.selected_bands.count()
        if count == 0:
            QMessageBox.warning(self, "Error", "Select at least 1 band.")
            return None
        if count == 2 or count > 3:
            QMessageBox.warning(self, "Error", "Select 1 band (single image) or 3 bands (RGB composite).")
            return None
        bands = []
        for i in range(count):
            item = self.selected_bands.item(i)
            bands.append(item.data(Qt.ItemDataRole.UserRole) or item.text())
        return bands

    def _bands_available(self, bands, selected_items):
        """True when every selected item has every band; otherwise warns with the first gaps."""
        issues = band_availability_issues(bands, selected_items)
        if not issues:
            return True
        details = [
            f"{item_id}: {', '.join(missing)} (available: {', '.join(available) or 'none'})"
            for item_id, missing, available in issues[:5]
        ]
        if len(issues) > len(details):
            details.append(f"... and {len(issues) - len(details)} more item(s)")
        QMessageBox.warning(
            self,
            "Band not available",
            "The selected band combination is not available in every selected item.\n\n"
            + "\n".join(details)
            + "\n\nUpdate the item or band selection and try again.",
        )
        return False

    def _confirm_large_crop(self):
        """False when the user declines cropping an extent larger than about 4 square degrees."""
        if not self.is_extent_crop_mode():
            return True
        bbox = self.get_bbox_from_extent()
        if not bbox:
            return True
        width, height = abs(bbox[2] - bbox[0]), abs(bbox[3] - bbox[1])
        # ~4 degrees² ≈ roughly 400×400 km at the equator
        if width * height <= 4.0:
            return True
        reply = QMessageBox.warning(
            self,
            "Large extent for Crop",
            f"The selected extent is large (~{width:.1f}° × {height:.1f}°).\n\n"
            "Crop mode builds cropped layers over this region, "
            "which may take longer to process and load, "
            "especially with many selected items.\n\n"
            "Do you want to continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _load_collection(self):
        """(STAC collection id, its config, its band info) for the collection picked in the combo."""
        collection_name = self._current_collection_name()
        config = COLLECTIONS.get(collection_name, {})
        collection_id = config.get("id", collection_name.replace(" ", "_"))
        return collection_id, config, BAND_INFO.get(collection_id, {})

    def _confirm_non_cog_load(self, config, collection_id):
        """Warn before loading a collection that is not cloud-optimized; False when the user cancels.

        Rendering has to stream whole scenes, and neither an overview nor a
        contrast stretch can be prepared, so the warning comes before the build.
        """
        if config.get("cloud_optimized") is not False or _non_cog_warning_muted():
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Collection is not cloud-optimized")
        box.setText(
            f"{collection_id} is served as plain GeoTIFF, without the internal overviews "
            "that make remote reading fast.\n\n"
            "The layer will load, but QGIS has to stream each full scene to draw it, so "
            "panning and zooming will be slow and may fail against a busy server. No "
            "overview or contrast stretch is generated for these layers.\n\n"
            "Download is the recommended way to work with this collection.\n\n"
            "Load the layers anyway?"
        )
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        never_again = QCheckBox("Don't show this warning again")
        box.setCheckBox(never_again)
        reply = box.exec()
        # Honored whichever button was used: someone who cancels and ticks
        # the box has decided they know the trade-off either way.
        if never_again.isChecked():
            _mute_non_cog_warning()
        if reply != QMessageBox.StandardButton.Yes:
            self._set_status("Loading cancelled. For this collection, download the images instead.", "info")
            return False
        return True

    def _begin_vrt_run(self, item_count):
        """Put the dialog in its loading state and start the elapsed-time status; returns the start time."""
        self._generating_vrt = True  # pauses thumbnails
        self._vrt_cancelled = False
        self._vrt_executor = None
        # Per-band display ranges precomputed off the UI thread in Phase 2.5,
        # keyed by vrt_path, so _open_raster_layers never samples a remote COG
        # on the UI thread. Reset each run.
        self._render_ranges_cache = {}
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, item_count)
        self.progress_bar.setFormat(tr("Preparing layer %v/%m"))
        self.load_btn.setEnabled(False)
        self.search_btn.setEnabled(False)
        self._show_cancel_button(self._cancel_vrt_generation)

        start_time = time.time()
        self._vrt_elapsed_timer = QTimer()
        self._vrt_item_idx = 0
        self._vrt_total_items = item_count

        def _update_vrt_elapsed():
            elapsed = time.time() - start_time
            done = self._vrt_item_idx
            if done > 0:
                avg = elapsed / done
                remaining = avg * (self._vrt_total_items - done)
                self._set_status(
                    f"Preparing layers: {done}/{self._vrt_total_items} "
                    f"({elapsed:.0f} s, ~{avg:.1f} s per layer, ~{remaining:.0f} s left)",
                    "info",
                )
            else:
                # The connection is open; the workers are opening each image,
                # which reads its header from the BDC.
                self._set_status(f"Reading image headers from the BDC: {elapsed:.0f} s", "info")

        self._vrt_elapsed_timer.timeout.connect(_update_vrt_elapsed)
        self._vrt_elapsed_timer.start(1000)
        return start_time

    def _end_vrt_run(self):
        self._generating_vrt = False
        timer = getattr(self, "_vrt_elapsed_timer", None)
        if timer is not None:
            timer.stop()
        self._hide_cancel_button()
        self.progress_bar.setVisible(False)
        self.load_btn.setEnabled(True)
        self.search_btn.setEnabled(True)

    def _warn_empty_layers(self, vrt_paths):
        """Say which loaded layers have no valid pixel, instead of leaving them blank.

        Uses the display-range sample already taken for each layer. A typical
        case is a scene whose footprint reaches the area only with the empty
        border around its imagery.
        """
        cache = getattr(self, "_render_ranges_cache", {}) or {}
        shown_names = getattr(self, "_layer_displays", {}) or {}
        empty = [
            shown_names.get(name, name) for path, name, _group in vrt_paths if getattr(cache.get(path), "empty", False)
        ]
        if not empty:
            return
        shown = ", ".join(empty[:3]) + (f" and {len(empty) - 3} more" if len(empty) > 3 else "")
        message = (
            f"{len(empty)} of {count_label(len(vrt_paths), 'layer', 'layers')} {'has' if len(empty) == 1 else 'have'} "
            f"no valid pixel in this area (the image covers it only with its empty border, or the area has no "
            f"data): {shown}."
        )
        _log_warning(message)
        self._set_status(message, "warning")
        try:
            self.iface.messageBar().pushWarning("BDC Loader", tr(message))
        except (AttributeError, RuntimeError):
            pass

    # ------------------------------------------------------------------
    # Phase 2: parallel VRT build
    # ------------------------------------------------------------------
    def _execute_vrt_build(self, vrt_tasks, errors, vrt_start_time, shape_mosaic_mode):
        """Execute VRT builds in parallel. Returns (vrt_paths, errors, cancelled, total_time)."""
        n_workers = min(8, len(vrt_tasks)) if vrt_tasks else 1
        if shape_mosaic_mode:
            self._set_status(
                f"Preparing {count_label(len(vrt_tasks), 'crop', 'crops')} ({n_workers} in parallel)...", "info"
            )
        else:
            self._set_status(
                f"Preparing {count_label(len(vrt_tasks), 'layer', 'layers')} ({n_workers} in parallel)...", "info"
            )
        QCoreApplication.processEvents()

        vrt_paths = []
        done_count = 0
        cancelled = False
        mask_dir = os.path.join(self.output_dir.text(), "masks")
        executor = ThreadPoolExecutor(max_workers=n_workers)
        self._vrt_executor = executor
        try:
            futures = {executor.submit(_build_task, t, mask_dir): t for t in vrt_tasks}
            # What each VRT should hold once built, to restore it if a replaced
            # layer writes its old copy back over it when it closes.
            self._built_vrts = {}
            pending = set(futures)
            deadline = time.monotonic() + _VRT_BUILD_BUDGET_S
            # Waiting in short slices keeps processEvents() running while the
            # workers open remote sources, so the dialog stays responsive and
            # the cancel button keeps working. Blocking on the futures instead
            # would freeze the UI thread for as long as the slowest read.
            while pending:
                if self._vrt_cancelled:
                    cancelled = True
                    for f in pending:
                        f.cancel()
                    break
                if time.monotonic() > deadline:
                    for f in pending:
                        f.cancel()
                    message = (
                        f"{len(pending)} of {len(vrt_tasks)} VRT builds exceeded "
                        f"{_VRT_BUILD_BUDGET_S:.0f}s and were abandoned; those layers were not loaded."
                    )
                    _log_warning(message)
                    errors.append(message)
                    break

                done, pending = wait_slice(pending)
                for future in done:
                    done_count += 1
                    self._vrt_item_idx = done_count
                    self.progress_bar.setValue(done_count)

                    try:
                        result = future.result()
                    except Exception as exc:
                        _log_warning(f"VRT task failed: {exc}")
                        continue
                    if result[0] == "ok":
                        vrt_paths.append((result[1], result[2], result[3]))
                        self._built_vrts[result[1]] = (futures[future], mask_dir, _file_digest(result[1]))
                    else:
                        errors.append(f"{result[1]}: {result[2]}")
        finally:
            executor.shutdown(wait=False)
            self._vrt_executor = None

        # Stop the progress timer
        self._vrt_elapsed_timer.stop()
        vrt_total_time = time.time() - vrt_start_time

        if cancelled:
            total_done = len(vrt_paths)
            if total_done > 0:
                self._set_status(
                    f"Loading cancelled: {total_done} of {len(vrt_tasks)} layers ready ({vrt_total_time:.1f} s). "
                    "Adding them to the map...",
                    "warning",
                )

        return vrt_paths, errors, cancelled, vrt_total_time

    # ------------------------------------------------------------------
    # Phase 3: load layers into QGIS
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------
    def _report_vrt_results(self, vrt_paths, errors, loaded, replaced, skipped_dup, vrt_total_time, cancelled):
        """Show final status message after VRT generation."""
        auto_render = self.auto_select_check.isChecked()
        total_vrts = len(vrt_paths)

        if total_vrts > 0:
            avg_time = vrt_total_time / total_vrts if total_vrts > 0 else 0
            timing = f"{vrt_total_time:.1f} s, ~{avg_time:.1f} s per layer"
            if avg_time > 10:
                timing += ", slow server"
            elif avg_time > 5:
                timing += ", moderate speed"

            msg = f"{count_label(loaded, 'layer', 'layers')} added to the map"
            if not auto_render:
                msg += ", turned off"
            msg += f" ({timing})."
            if cancelled:
                msg = "Loading cancelled: " + msg
            notes = _source_notes(vrt_paths)
            if skipped_dup > 0:
                notes.append(count_label(skipped_dup, "non-raster duplicate skipped", "non-raster duplicates skipped"))
            if replaced > 0:
                notes.append(f"{replaced} switched from the BDC to your downloads")
            if errors:
                notes.append(count_label(len(errors), "error", "errors"))
            if notes:
                msg += f" {', '.join(notes)}."
            if errors:
                self._set_status(msg, "warning")
                _log_warning(f"VRT Errors: {errors[:10]}")
            else:
                self._set_status(msg, "success")
        elif getattr(self, "_unchanged_layers", 0) and not errors:
            self._set_status(
                f"{count_label(self._unchanged_layers, 'layer', 'layers')} already loaded and up to date.", "info"
            )
        else:
            self._set_status("Loading layers failed: no layer was added to the map.", "error")
            if errors:
                QMessageBox.warning(self, "Error", "Errors:\n" + "\n".join(errors[:10]))
            else:
                QMessageBox.warning(
                    self,
                    "Error",
                    "No layer loaded.\n\n"
                    "Check that:\n"
                    "- Results are selected (checkboxes)\n"
                    "- 1 or 3 bands are selected\n"
                    "- The server is reachable",
                )
