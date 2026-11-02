# -*- coding: utf-8 -*-
"""
Download management mixin for BDCLoaderDialog.

Provides:
- `DownloadManager` — mixin inherited by BDCLoaderDialog that handles:
  - the download options dialog: file format (one GeoTIFF per band, per band
    plus a VRT, or one multiband GeoTIFF), sits file names, projection, folder
  - downloads of one result (the card button) or of every selected result
  - STAC items: original COGs fetched in parallel byte ranges, then stacked or
    reprojected when the chosen format asks for it
  - crops and vector-feature mosaics: masked to the area with gdal.Warp
  - cancellation, progress, and the "already downloaded" (LOCAL) state

Dependencies:
  core.download_outputs — output formats and file names
  ui.result_widgets — _format_size helper and ResultItemWidget
"""

import logging
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass

from qgis.core import QgsSettings

_logger = logging.getLogger("bdc_loader")
from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtWidgets import QDialog, QMessageBox

from ..i18n import count_label
from ..logger import info as _log_info
from ..stac.parsers import extract_tile_from_item
from ..ui.result_widgets import _format_size
from ..widgets.dialogs import DownloadOptionsDialog
from . import cog_window, download_engine, output_crs
from .band_selection import resolve_band
from .catalog_data import BAND_INFO
from .cutline import WHOLE_TILE_PREFETCH_FRACTION, cutline_wgs84_bbox, estimate_tile_fetch_fraction
from .download_outputs import (
    MULTIBAND,
    PER_BAND,
    area_outputs,
    area_tag,
    safe_component,
    save_format,
    stored_format,
    tile_outputs,
)
from .raster_export import export_bbox_geotiff, export_masked_geotiff, export_stack_geotiff, split_bands, write_band_vrt
from .render_ranges import raster_has_valid_pixels
from .ui_wait import run_in_worker
from .vrt_builder import build_single_vrt, is_valid_local_raster

SKIP_CONFIRM_SETTING = "bdc_loader/skip_download_confirm"
CONNECTIONS_SETTING = "bdc_loader/download_connections"


_COUNTER = re.compile(r"\[\d+/\d+\] ")


def _counter_first(text):
    """Move the "[i/n] " counter of a multi-image download, carried in a label, to the start of the line."""
    match = _COUNTER.search(text)
    if match is None or match.start() == 0:
        return text
    return match.group(0) + text[: match.start()] + text[match.end() :]


def download_connections(settings=None):
    """Simultaneous connections chosen in Settings, within the engine's bounds."""
    settings = settings if settings is not None else QgsSettings()
    try:
        value = int(settings.value(CONNECTIONS_SETTING, download_engine.DEFAULT_MAX_WORKERS))
    except (TypeError, ValueError):
        value = download_engine.DEFAULT_MAX_WORKERS
    return max(download_engine.MIN_WORKERS, min(download_engine.MAX_WORKERS_LIMIT, value))


def _safe_path_component(name: str) -> str:
    """Sanitize a string for use as a single filesystem path component."""
    return safe_component(name)


def band_download_dir(download_dir, collection_id, item_id):
    """Return the directory a per-band download writes its GeoTIFFs into."""
    return os.path.join(download_dir, "downloads", _safe_path_component(collection_id), _safe_path_component(item_id))


def find_band_download(download_dir, collection_id, item_id, band, resolved=None):
    """Return the path of an already-downloaded band file, or None.

    The download names the file after the asset key the band resolved to,
    while the user may have picked an alias (rgb -> tci -> visual), so both
    spellings are tried. Sharing this with the writer keeps a downloaded scene
    visible to the VRT builder instead of being read over the network again.
    """
    item_dir = band_download_dir(download_dir, collection_id, item_id)
    safe_item = _safe_path_component(item_id)
    for name in dict.fromkeys(n for n in (band, resolved) if n):
        candidate = os.path.join(item_dir, f"{safe_item}_{_safe_path_component(name)}.tif")
        if is_valid_local_raster(candidate):
            return candidate
    return None


def mosaic_area(item):
    """Area tag of a crop or vector-feature mosaic (see download_outputs.area_tag)."""
    props = getattr(item, "properties", {}) or {}
    tag = props.get("bdc:area_tag")
    if tag:
        return tag
    return area_tag(props.get("bdc:feature_name") or ("crop" if props.get("bdc:is_extent_crop") else "mosaic"))


def mosaic_date(item):
    props = getattr(item, "properties", {}) or {}
    return props.get("bdc:mosaic_date") or _item_date(item)


def _item_date(item):
    dt = getattr(item, "datetime", None)
    if dt:
        return dt.strftime("%Y-%m-%d")
    value = str((getattr(item, "properties", {}) or {}).get("datetime") or "")
    return value[:10] or "unknown"


def _is_mosaic(item):
    return bool((getattr(item, "properties", {}) or {}).get("bdc:is_shape_mosaic"))


def _link_or_copy(src, dst):
    """Give ``src`` a second name at ``dst``: a hard link when the file system
    allows it (no extra space), otherwise a copy written via ``<dst>.part``."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        os.link(src, dst)
        return
    except OSError:
        pass
    tmp = dst + ".part"
    shutil.copy2(src, tmp)
    os.replace(tmp, dst)


@dataclass(frozen=True)
class DownloadChoice:
    """What the options dialog returns: file format, projection, sits names."""

    fmt: str
    crs: object
    sits: bool = False


@dataclass(frozen=True)
class PrefetchPlan:
    """Outcome of plan_prefetch_tasks.

    tasks: (href, dest_file) pairs for tiles worth downloading whole, in
        source-item then band order.
    max_fraction: the largest per-tile coverage fraction seen, so the caller
        can explain why nothing was prefetched when tasks is empty.
    """

    tasks: list
    max_fraction: float


def plan_prefetch_tasks(
    source_items,
    bands,
    download_dir,
    collection_id,
    cutline_bbox,
    *,
    prefetch_fraction=WHOLE_TILE_PREFETCH_FRACTION,
    is_reusable=is_valid_local_raster,
):
    """Decide which source tiles a crop should download whole, from bbox
    metadata alone. Deterministic and free of network and Qt: the only side
    input is is_reusable, a predicate deciding whether a candidate destination
    already holds a finished raster. It defaults to is_valid_local_raster (which
    opens the file with GDAL) and is injected by tests to supply a fake disk.

    A tile whose estimated overlap with the crop (estimate_tile_fetch_fraction)
    reaches prefetch_fraction is cheaper to fetch whole in parallel than to read
    windowed, so each of its requested, resolvable bands whose destination is not
    already a reusable raster becomes a download task. A destination that exists
    but is empty, truncated, unreadable, or still has a ``.part`` sibling is not
    reusable, so it is fetched again rather than mistaken for a finished file.
    Tiles below the threshold are left for a windowed remote read and contribute
    no tasks. Bands the tile cannot provide (resolve_band returns None) are
    skipped. Tiles and bands are visited in the given order, so the task list is
    deterministic.
    """
    tasks = []
    max_fraction = 0.0
    for src_item in source_items:
        fraction = estimate_tile_fetch_fraction(getattr(src_item, "bbox", None), cutline_bbox)
        max_fraction = max(max_fraction, fraction)
        if fraction < prefetch_fraction:
            continue
        item_dir = os.path.join(
            download_dir, "downloads", _safe_path_component(collection_id), _safe_path_component(src_item.id)
        )
        for band in bands:
            resolved = resolve_band(band, src_item.assets)
            if not resolved:
                continue
            dest_file = os.path.join(
                item_dir, f"{_safe_path_component(src_item.id)}_{_safe_path_component(resolved)}.tif"
            )
            if not is_reusable(dest_file):
                tasks.append((src_item.assets[resolved].href, dest_file))
    return PrefetchPlan(tasks=tasks, max_fraction=max_fraction)


class DownloadManager:
    """Downloads with format options, progress, cancel, and status tracking."""

    # ------------------------------------------------------------------
    #  Plans and "already downloaded"
    # ------------------------------------------------------------------

    def _selected_band_list(self):
        bands = []
        for i in range(self.selected_bands.count()):
            list_item = self.selected_bands.item(i)
            bands.append(list_item.data(Qt.ItemDataRole.UserRole) or list_item.text())
        return bands

    @staticmethod
    def _resolve_item_bands(item, bands):
        """(asset keys, bands the item does not have) for a STAC item."""
        resolved, missing = [], []
        for band in bands:
            key = resolve_band(band, item.assets)
            (resolved if key else missing).append(key or band)
        return resolved, missing

    def _plan_for(self, widget, bands, fmt, tag, sits, download_dir=None):
        """Files a download of ``widget`` writes, or None when the item lacks a band."""
        download_dir = download_dir or self._download_dir
        item = widget.item
        if _is_mosaic(item):
            return area_outputs(
                download_dir, widget.collection_id, mosaic_area(item), mosaic_date(item), bands, fmt, tag, sits
            )
        resolved, missing = self._resolve_item_bands(item, bands)
        if missing:
            return None
        return tile_outputs(
            download_dir,
            widget.collection_id,
            item.id,
            resolved,
            fmt,
            tag,
            sits,
            tile=extract_tile_from_item(item),
            date=_item_date(item),
        )

    def _local_check_context(self):
        """(bands, projection tags, sits) shared by the LOCAL checks of one refresh."""
        settings = QgsSettings()
        _fmt, sits = stored_format(settings)
        tags = tuple(dict.fromkeys(("", output_crs.stored_option(settings=settings).tag)))
        return self._selected_band_list(), tags, sits

    def _check_item_downloaded(self, widget, context=None):
        """True when the selected bands of this result are on disk in any format.

        Checks the native projection and the one last chosen, with and without
        sits names, so the LOCAL badge shows whichever way the files were saved.
        """
        bands, tags, sits = context or self._local_check_context()
        if not bands:
            return False
        for tag in tags:
            for fmt in (PER_BAND, MULTIBAND, "per_band_vrt"):
                for use_sits in {False, sits and fmt == PER_BAND}:
                    plan = self._plan_for(widget, bands, fmt, tag, use_sits)
                    if plan is None:
                        return False
                    if plan.complete():
                        return True
        return False

    def _cancel_download(self):
        """Stop the downloads after the transfers already running."""
        self._download_cancelled = True
        self._set_status("Cancelling download...", "warning")

    def _update_downloaded_status(self):
        """Update downloaded status on all result widgets based on the selected bands."""
        context = self._local_check_context()
        for widget in self.result_widgets:
            widget.set_downloaded(self._check_item_downloaded(widget, context))

    # ------------------------------------------------------------------
    #  Entry points
    # ------------------------------------------------------------------

    def _download_item(self, widget):
        """Entry point for the per-result download button."""
        self._download_widgets([widget])

    def _download_selected(self):
        """Download every selected, visible result with one choice of format."""
        widgets = [w for w in self.result_widgets if w.isVisible() and w.is_selected()]
        if not widgets:
            QMessageBox.information(self, "Download", "Select one or more results to download.")
            return
        self._download_widgets(widgets)

    def _download_widgets(self, widgets):
        """Ask for the options once, then download each result in turn.

        A single in-progress flag blocks a second download from starting while
        one runs: the work below pumps the Qt event loop, so another click
        could otherwise re-enter and share this run's progress bar and cancel
        flag. The flag is released after success, error and cancellation alike.
        """
        if self._download_in_progress:
            return
        self._download_in_progress = True
        # A search or a load during the downloads would replace the result
        # cards they work on and share their progress bar.
        held = (self.search_btn, self.load_btn, self.collection_combo)
        for widget in held:
            widget.setEnabled(False)
        try:
            self._download_widgets_unguarded(widgets)
        finally:
            self._download_in_progress = False
            for widget in held:
                widget.setEnabled(True)

    def _download_widgets_unguarded(self, widgets):
        if not self._results_match_panel():
            return
        bands = self._selected_band_list()
        if not bands:
            QMessageBox.warning(self, "Warning", "Select at least 1 band before downloading.")
            return

        settings = QgsSettings()
        crs_options = output_crs.build_options()
        crs_option = output_crs.stored_option(crs_options, settings=settings)
        fmt, sits = stored_format(settings)
        if len(bands) < 2:
            fmt = PER_BAND
        stored = DownloadChoice(fmt, crs_option, sits and fmt == PER_BAND)

        if settings.value(SKIP_CONFIRM_SETTING, False, type=bool):
            choice = stored
            if len(widgets) == 1:
                plan = self._plan_for(widgets[0], bands, stored.fmt, stored.crs.tag, stored.sits)
                if plan is not None and plan.complete():
                    widgets[0].set_downloaded(True)
                    self._set_status(f"Image already downloaded: {os.path.dirname(plan.paths()[0])}.", "success")
                    return
        else:
            # Always asked, even when the last choice is on disk: the same
            # result may be wanted in another format or projection.
            choice = self._ask_download_choice(widgets, bands, crs_options, stored, sits, settings)
            if choice is None:
                return

        self._download_cancelled = False
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")
        self._show_cancel_button(self._cancel_download)
        QCoreApplication.processEvents()

        outcomes = []
        try:
            for index, widget in enumerate(widgets, start=1):
                if self._download_cancelled:
                    break
                prefix = f"[{index}/{len(widgets)}] " if len(widgets) > 1 else ""
                # The bar shows the progress of the image being downloaded.
                self.progress_bar.setValue(0)
                widget.download_btn.setEnabled(False)
                widget.set_download_busy(True)
                try:
                    outcome = self._download_one(widget, bands, choice, prefix)
                except Exception as exc:  # noqa: BLE001
                    _logger.exception("Download failed for %s", widget.item.id)
                    outcome = ("error", f"{widget.item.id}: {exc}")
                finally:
                    widget.download_btn.setEnabled(True)
                    widget.set_download_busy(False)
                if outcome[0] in ("done", "skipped", "empty"):
                    widget.set_downloaded(True)
                outcomes.append((widget, outcome))
        finally:
            self.progress_bar.setVisible(False)
            self._hide_cancel_button()

        self._report_downloads(outcomes, len(widgets))

    def _ask_download_choice(self, widgets, bands, crs_options, stored, stored_sits, settings):
        """Show the options dialog; return a DownloadChoice, or None when cancelled."""
        first = widgets[0]
        if len(widgets) == 1:
            message = f"Download {len(bands)} band(s) of {first.item.id}?"
        else:
            message = f"Download {len(bands)} band(s) for {len(widgets)} selected results?"
        size_note = self._size_note(widgets, bands)
        if size_note:
            message += f"\n{size_note}"

        def destination_for(option, fmt, sits, folder):
            plan = self._plan_for(first, bands, fmt, option.tag, sits and fmt == PER_BAND, folder)
            if plan is None or not plan.paths():
                return ""
            names = [os.path.basename(path) for path in plan.paths()]
            shown = ", ".join(names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else "")
            text = f"Destination: {os.path.dirname(plan.paths()[0])}\nFiles: {shown}"
            return ("First result. " + text) if len(widgets) > 1 else text

        dialog = DownloadOptionsDialog(
            message,
            crs_options,
            stored.crs.key,
            destination_for=destination_for,
            parent=self,
            selected_format=stored.fmt,
            sits_names=stored_sits,
            band_count=len(bands),
            folder=self._download_dir,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        crs_option = dialog.selected_option() or stored.crs
        output_crs.save_option(crs_option, settings)
        if len(bands) > 1:
            save_format(settings, dialog.selected_format(), dialog.sits_check.isChecked())
        else:
            save_format(settings, stored_format(settings)[0], dialog.sits_check.isChecked())
        folder = dialog.folder()
        if folder and folder != self._download_dir:
            self._download_dir = folder
            settings.setValue("bdc_loader/download_dir", folder)
            self._set_status(f"Download folder saved in the settings: {folder}.", "success")
        if dialog.remember_choice():
            settings.setValue(SKIP_CONFIRM_SETTING, True)
        return DownloadChoice(dialog.selected_format(), crs_option, dialog.sits_names())

    def _size_note(self, widgets, bands):
        """Estimated size of the original band files still missing (STAC items only)."""
        hrefs = []
        for widget in widgets:
            item = widget.item
            if _is_mosaic(item):
                return ""
            resolved, missing = self._resolve_item_bands(item, bands)
            if missing:
                continue
            for band in resolved:
                if not find_band_download(self._download_dir, widget.collection_id, item.id, band):
                    hrefs.append(item.assets[band].href)
        if not hrefs:
            return ""
        self._set_status(f"Estimating the size of {count_label(len(hrefs), 'file', 'files')}...", "download")
        QCoreApplication.processEvents()
        try:
            probes = download_engine.probe_all(hrefs)
        except Exception:  # noqa: BLE001
            return "Size: could not estimate"
        total = sum(size for size, _range in probes.values() if size)
        return f"Estimated size: {_format_size(total)}" if total else "Size: could not estimate"

    def _report_downloads(self, outcomes, requested):
        done = [o for o in outcomes if o[1][0] in ("done", "empty")]
        empty = [o for o in outcomes if o[1][0] == "empty"]
        skipped = [o for o in outcomes if o[1][0] == "skipped"]
        errors = [o for o in outcomes if o[1][0] == "error"]
        cancelled = self._download_cancelled or any(o[1][0] == "cancelled" for o in outcomes)

        if requested == 1 and outcomes:
            widget, (status, detail) = outcomes[0]
            if status == "done":
                self._set_status(f"Download complete: {detail}.", "success")
            elif status == "empty":
                self._set_status(
                    f"Download complete, but {widget.item.id} has no valid pixel in this area "
                    f"(the image covers it only with its empty border, or has no data there): {detail}.",
                    "warning",
                )
            elif status == "skipped":
                self._set_status(f"Image already downloaded: {detail}.", "success")
            elif status == "cancelled":
                self._set_status(f"Download cancelled: {widget.item.id}.", "warning")
            else:
                QMessageBox.warning(self, "Download Errors", detail)
                self._set_status(f"Download failed: {widget.item.id}.", "error")
            return

        parts = [f"{count_label(len(done), 'image', 'images')} downloaded"]
        if empty:
            parts.append(f"{len(empty)} without valid pixels ({', '.join(w.item.id for w, _o in empty[:3])})")
        if skipped:
            parts.append(f"{len(skipped)} already on disk")
        if errors:
            parts.append(f"{len(errors)} failed")
        text = ", ".join(parts) + "."
        if cancelled:
            text = f"Download cancelled: {len(outcomes)} of {requested} images processed, {text}"
        level = "error" if errors else ("warning" if cancelled or empty else "success")
        self._set_status(text, level)
        if errors:
            QMessageBox.warning(self, "Download Errors", "\n\n".join(detail for _w, (_s, detail) in errors))

    # ------------------------------------------------------------------
    #  One result
    # ------------------------------------------------------------------

    def _download_one(self, widget, bands, choice, prefix=""):
        """Download one result; returns (status, detail).

        status is done, skipped, cancelled, error, or empty: written, but
        without a single valid pixel (the files stay on disk).
        """
        if _is_mosaic(widget.item):
            status, detail = self._download_masked_mosaic(widget, bands, choice, prefix)
        else:
            status, detail = self._download_regular_item(widget, bands, choice, prefix)
        if status == "done" and self._written_files_are_empty(widget, bands, choice):
            return "empty", detail
        return status, detail

    def _written_files_are_empty(self, widget, bands, choice):
        """True when every raster just written has no valid pixel in its sample."""
        plan = self._plan_for(widget, bands, choice.fmt, choice.crs.tag, choice.sits)
        rasters = [path for path in (plan.paths() if plan else []) if path.endswith(".tif")]
        verdicts = [raster_has_valid_pixels(path) for path in rasters]
        return bool(verdicts) and all(verdict is False for verdict in verdicts)

    def _download_regular_item(self, widget, bands, choice, prefix=""):
        """Download a STAC item: fetch the original COGs, then derive the chosen format."""
        item = widget.item
        collection_id = widget.collection_id
        resolved, missing = self._resolve_item_bands(item, bands)
        if missing:
            available = ", ".join(k for k in item.assets if k != "thumbnail")
            return "error", f"{item.id}: band(s) {', '.join(missing)} not found. Available: {available}"

        plan = self._plan_for(widget, bands, choice.fmt, choice.crs.tag, choice.sits)
        if plan.complete():
            return "skipped", os.path.dirname(plan.paths()[0])

        natives = tile_outputs(self._download_dir, collection_id, item.id, resolved, PER_BAND)
        sources = [path for _band, path in natives.band_files]
        tasks = [(item.assets[band].href, path) for band, path in natives.band_files if not is_valid_local_raster(path)]
        fetched = [path for _href, path in tasks]
        if tasks:
            os.makedirs(os.path.dirname(sources[0]), exist_ok=True)
            bands_label = f"{count_label(len(tasks), 'band', 'bands')} of {item.id}"
            self._set_status(
                f"{prefix}Preparing to download {count_label(len(tasks), 'band', 'bands')} of {item.id}...", "download"
            )
            QCoreApplication.processEvents()
            probes = download_engine.probe_all([href for href, _path in tasks])
            size_hint = sum(size for size, _range in probes.values() if size)
            errors = self._run_accelerated_downloads(
                tasks, total_size_hint=size_hint, label=f"{prefix}{bands_label}", probes=probes
            )
            if self._download_cancelled:
                return "cancelled", item.id
            if errors:
                details = "\n".join(f"{os.path.basename(dest)}: {msg}" for _url, dest, msg in errors)
                _logger.warning("Download failed for %s: %s", item.id, details)
                return "error", f"Errors downloading {item.id}:\n{details}"

        ok, detail = self._write_outputs(plan, resolved, sources, choice, f"{prefix}{item.id}")
        if ok and plan.multiband:
            # The original bands were only the source of the multiband file.
            for path in fetched:
                for leftover in (path, path + ".aux.xml"):
                    try:
                        os.remove(leftover)
                    except OSError:
                        pass
        if self._download_cancelled:
            return "cancelled", item.id
        return ("done", os.path.dirname(plan.paths()[0])) if ok else ("error", f"{item.id}: {detail}")

    def _write_outputs(self, plan, bands, sources, choice, label):
        """Write ``plan`` from per-band ``sources`` in the native projection."""
        warp_srs = choice.crs.warp_srs
        if plan.multiband:
            os.makedirs(os.path.dirname(plan.multiband), exist_ok=True)
            return self._run_export(label, export_stack_geotiff, sources, plan.multiband, bands, dst_srs=warp_srs)
        for (band, out), src in zip(plan.band_files, sources):
            if os.path.abspath(out) == os.path.abspath(src) or is_valid_local_raster(out):
                continue
            os.makedirs(os.path.dirname(out), exist_ok=True)
            if warp_srs:
                ok, detail = self._run_export(label, export_stack_geotiff, [src], out, [band], dst_srs=warp_srs)
                if not ok:
                    return False, detail
            else:
                _link_or_copy(src, out)
        if plan.vrt:
            return write_band_vrt(plan.vrt, [path for _band, path in plan.band_files], bands)
        return True, os.path.dirname(plan.paths()[0])

    def _download_masked_mosaic(self, widget, bands, choice, prefix=""):
        """Download a crop or vector-feature mosaic masked to its area.

        Source tiles the area mostly covers are pre-fetched whole, in
        parallel, into the regular downloads folder (so a later per-item
        download sees them as local too); tiles it barely touches are read
        windowed instead, which costs less than fetching the whole tile for a
        sliver of it. A VRT over those tiles is then cut to the area with
        gdal.Warp, and split per band when the chosen format asks for it.
        Returns (status, detail): done, skipped, cancelled or error.
        """
        item = widget.item
        collection_id = widget.collection_id
        props = getattr(item, "properties", {}) or {}
        is_extent_crop = bool(props.get("bdc:is_extent_crop"))
        source_items = self._mosaic_source_items(item, is_extent_crop)
        if not source_items:
            return "error", f"{item.id}: no source tiles for this date (check the Tile Filter)."

        area = mosaic_area(item)
        date_str = mosaic_date(item)
        plan = area_outputs(
            self._download_dir, collection_id, area, date_str, bands, choice.fmt, choice.crs.tag, choice.sits
        )
        if plan.complete():
            return "skipped", os.path.dirname(plan.paths()[0])
        cutline_path = self._cutline_for_item(item)
        if not cutline_path:
            return "error", f"{item.id}: could not determine the shape/extent boundary."

        output_dir = self._download_dir
        os.makedirs(output_dir, exist_ok=True)
        self._set_status(f"{prefix}Downloading {item.id}...", "download")
        QCoreApplication.processEvents()
        label = f"{prefix}{item.id}"
        tmp_dir = tempfile.mkdtemp(prefix="bdc_masked_dl_")
        try:
            self._prefetch_mosaic_tiles(source_items, bands, collection_id, cutline_path, item.id, prefix)
            if self._download_cancelled:
                return "cancelled", item.id
            task_errors = []
            task = self._mosaic_vrt_task(
                bands,
                source_items,
                item,
                collection_id,
                f"{area}_{date_str}",
                date_str,
                tmp_dir,
                cutline_path,
                task_errors,
            )
            if not task:
                return "error", "\n".join(task_errors) or f"{item.id}: could not build the mosaic VRT."
            # Sources still remote are copied block by block: only the blocks
            # under the area, in parallel (see cog_window).
            crop_bbox = props.get("bdc:crop_bbox")
            task = self._fetch_area_blocks(
                task,
                lambda: (
                    cog_window.bbox_wkt(crop_bbox)
                    if is_extent_crop and crop_bbox
                    else cog_window.area_wkt_from_cutline(cutline_path)
                ),
                os.path.join(tmp_dir, "blocks"),
                label,
            )
            if self._download_cancelled:
                return "cancelled", item.id
            vrt_result = build_single_vrt(task)
            if vrt_result[0] != "ok":
                return "error", f"{item.id}: VRT build failed: {vrt_result[2]}"
            # The boundary is a temp file written before the (possibly slow)
            # VRT build; write it again if it is gone by now.
            if not os.path.exists(cutline_path):
                cutline_path = self._cutline_for_item(item)
                if not cutline_path:
                    return "error", f"{item.id}: could not determine the shape/extent boundary."
            clip = crop_bbox if is_extent_crop and crop_bbox else None
            status, detail = self._export_mosaic(plan, vrt_result[1], bands, choice, cutline_path, clip, tmp_dir, label)
            if status != "done":
                return status, item.id if status == "cancelled" else f"{item.id}: {detail}"
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        return "done", os.path.dirname(plan.paths()[0])

    def _mosaic_source_items(self, item, is_extent_crop):
        """The mosaic's source items, without tiles unchecked in the Tile Filter dialog."""
        source_items = list(getattr(item, "_source_items", []))
        if is_extent_crop and self._current_result_mode == "extent_crop":
            tile_filter_dict = self._tile_filter_dict
            if tile_filter_dict:
                checked = {tid for tid, td in tile_filter_dict.items() if td["checked"]}
                source_items = [si for si in source_items if extract_tile_from_item(si).upper() in checked]
        return source_items

    def _prefetch_mosaic_tiles(self, source_items, bands, collection_id, cutline_path, item_id, prefix):
        """Download whole the source tiles the area mostly covers.

        A tile the area mostly covers is cheaper to fetch whole, in parallel
        across many connections, than to read piecemeal over a single
        windowed connection (~2 MB/s windowed vs ~13 MB/s at 12-way parallel
        against the BDC server). The overlap comes from bbox metadata alone,
        with no raster I/O.
        """
        plan = plan_prefetch_tasks(
            source_items, bands, self._download_dir, collection_id, cutline_wgs84_bbox(cutline_path)
        )
        if not plan.tasks:
            self._set_status(
                f"{prefix}Reading {item_id} directly from the BDC "
                f"(the area covers ~{plan.max_fraction * 100:.0f}% of the largest tile)...",
                "info",
            )
            return
        for _href, dest in plan.tasks:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
        self._set_status(
            f"{prefix}Preparing to download {count_label(len(plan.tasks), 'tile file', 'tile files')} of {item_id}...",
            "download",
        )
        QCoreApplication.processEvents()
        probes = download_engine.probe_all([href for href, _dest in plan.tasks])
        size_hint = sum(size for size, _supports_range in probes.values())
        self._run_accelerated_downloads(
            plan.tasks, total_size_hint=size_hint, label=f"{prefix}the tiles of {item_id}", probes=probes
        )

    def _mosaic_vrt_task(self, bands, source_items, item, collection_id, tile, date_str, tmp_dir, cutline_path, errors):
        """VRT build task of the mosaic, written to ``tmp_dir``: one band, or an RGB composite."""
        return self._composition_task(
            bands,
            "-".join(bands),
            source_items,
            item,
            True,
            collection_id,
            (tile, tile, date_str),
            (self._download_dir, tmp_dir),
            self._has_mixed_resolution(collection_id, bands),
            cutline_path,
            f"{collection_id} / {mosaic_area(item)}",
            "compact",
            errors,
        )

    def _export_mosaic(self, plan, vrt_path, bands, choice, cutline_path, clip_bbox, tmp_dir, label):
        """Cut the mosaic VRT to its area into the planned files; (status, detail).

        An extent crop (``clip_bbox``) is cut as a straight rectangle in the
        output projection (see export_bbox_geotiff) instead of a mask along a
        box that is rotated in that projection; a shape is masked along it.
        """
        if plan.multiband:
            target = plan.multiband
        elif len(plan.band_files) == 1:
            target = plan.band_files[0][1]
        else:
            target = os.path.join(tmp_dir, "stack.tif")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if clip_bbox:
            ok, detail = self._run_export(
                label, export_bbox_geotiff, vrt_path, clip_bbox, target, dst_srs=choice.crs.warp_srs, band_names=bands
            )
        else:
            ok, detail = self._run_masked_export(
                vrt_path, cutline_path, target, label, dst_srs=choice.crs.warp_srs, band_names=bands
            )
        if self._download_cancelled:
            return "cancelled", ""
        if not ok:
            return "error", detail
        band_paths = [path for _band, path in plan.band_files]
        if target not in plan.paths():
            for path in band_paths:
                os.makedirs(os.path.dirname(path), exist_ok=True)
            ok, detail = split_bands(target, band_paths, bands)
            if not ok:
                return "error", detail
        if plan.vrt:
            ok, detail = write_band_vrt(plan.vrt, band_paths, bands)
            if not ok:
                return "error", detail
        return "done", ""

    @staticmethod
    def _has_mixed_resolution(collection_id, bands):
        info = BAND_INFO.get(collection_id, {})
        resolutions = {info[band].get("resolution", "") for band in bands if band in info}
        return len(resolutions) > 1

    # ------------------------------------------------------------------
    #  Background work with progress
    # ------------------------------------------------------------------

    def _run_masked_export(self, vrt_path, cutline_path, dst_path, label, dst_srs=None, band_names=None):
        """Run export_masked_geotiff in the background with progress (see _run_export).

        dst_srs is the user's output-projection choice; it rides along to the
        same single Warp the crop already runs, so it adds no pass over the data.

        Returns export_masked_geotiff's (ok, dst_path_or_error) tuple.
        """
        return self._run_export(
            label, export_masked_geotiff, vrt_path, cutline_path, dst_path, dst_srs=dst_srs, band_names=band_names
        )

    def _run_export(self, label, func, *args, **kwargs):
        """Run a GDAL export ``func(*args, progress_cb, cancel_check, **kwargs)`` in
        the background, polling GDAL's own progress (0.0-1.0) onto the progress
        bar and status line from the main thread, and honoring the cancel button
        through GDAL's progress callback.

        GDAL only reports progress once it starts copying output pixels; a
        small or windowed remote read can spend most of its time in setup before
        that, so elapsed time is shown until there is a fraction to report.
        """
        progress = download_engine.ProgressCounter()
        start = time.time()

        def _show_progress():
            fraction = progress.value()
            if fraction > 0:
                pct = min(100, int(fraction * 100))
                self.progress_bar.setValue(pct)
                self._set_status(_counter_first(f"Writing {label}: {pct}%"), "download")
            else:
                self._set_status(_counter_first(f"Writing {label}: {time.time() - start:.0f} s"), "download")

        return run_in_worker(
            func,
            *args,
            progress_cb=progress.set,
            cancel_check=lambda: self._download_cancelled,
            on_wait=_show_progress,
            **kwargs,
        )

    def _fetch_area_blocks(self, task, area_wkt_of, folder, label):
        """Point ``task`` at local copies of the source blocks under the area.

        ``area_wkt_of()`` gives the area as a lon/lat WKT polygon; it is only
        called when some source is remote.

        Downloads run in a worker while this polls the progress; the task is
        returned unchanged (remote sources) when the blocks cannot be planned,
        fetched or verified, which keeps the slower windowed read as fallback.
        """
        hrefs = cog_window.task_hrefs(task)
        if not any(cog_window.is_remote(h) for h in hrefs):
            return task
        area_wkt = area_wkt_of()
        if not area_wkt:
            return task
        connections = download_engine.effective_workers(download_connections())
        limiter = download_engine.ConnectionLimiter(connections)
        session = download_engine.make_session(connections, on_throttle=limiter.throttle)
        counter = download_engine.ProgressCounter()
        last = {"bytes": 0, "time": time.time()}

        def _show_progress():
            done = counter.value()
            now = time.time()
            speed = (done - last["bytes"]) / (now - last["time"]) if now > last["time"] else 0
            last.update(bytes=done, time=now)
            speed_info = f" ({_format_size(speed)}/s)" if speed > 0 else ""
            self._set_status(
                _counter_first(f"Downloading the area blocks of {label}: {_format_size(done)}{speed_info}"),
                "download",
            )

        try:
            mapping, fetched = run_in_worker(
                cog_window.localize,
                hrefs,
                area_wkt,
                folder,
                session,
                limiter,
                counter.add,
                lambda: self._download_cancelled,
                on_wait=_show_progress,
            )
        finally:
            session.close()
        if not mapping:
            _log_info(f"{label}: block copy not used; reading the sources remotely")
            return task
        _log_info(f"{label}: block copy of {len(mapping)} file(s), {_format_size(fetched)}")
        return cog_window.localize_task(task, mapping)

    def _run_accelerated_downloads(self, tasks, total_size_hint=0, label="files", probes=None):
        """Run download_engine.download_files in the background, polling its
        progress onto self.progress_bar/self._set_status from the main thread.

        Qt widgets aren't thread-safe, so the worker threads inside
        download_engine only ever touch plain counters; this method is the
        only place that reads them and updates the UI, including an
        instantaneous transfer speed (bytes since the last poll / elapsed)
        and how many files are downloading concurrently right now.

        probes, if given, is a {url: (size, supports_range)} mapping already
        obtained for these tasks (via probe_all) so each transfer reuses it
        instead of issuing a second HEAD.

        Returns download_engine.download_files' (url, dest_path, error) list;
        empty means every file in tasks succeeded.
        """
        if not tasks:
            return []

        counter = download_engine.ProgressCounter()
        active_counter = download_engine.ProgressCounter()
        last = {"bytes": 0, "time": time.time()}

        def _show_progress():
            downloaded = counter.value()
            now = time.time()
            elapsed = now - last["time"]
            speed = (downloaded - last["bytes"]) / elapsed if elapsed > 0 else 0
            last.update(bytes=downloaded, time=now)
            active = max(0, active_counter.value())
            files = count_label(active, "file", "files")
            speed_info = f" ({_format_size(speed)}/s, {files} at a time)" if speed > 0 else ""
            if total_size_hint > 0:
                pct = min(100, int(downloaded / total_size_hint * 100))
                self.progress_bar.setValue(pct)
                size = f"{_format_size(downloaded)} of {_format_size(total_size_hint)}"
                self._set_status(_counter_first(f"Downloading {label}: {size}{speed_info}"), "download")
            else:
                self._set_status(
                    _counter_first(f"Downloading {label}: {_format_size(downloaded)}{speed_info}"), "download"
                )

        return run_in_worker(
            download_engine.download_files,
            tasks,
            download_connections(),
            counter.add,
            lambda: self._download_cancelled,
            active_counter.add,
            probes,
            on_wait=_show_progress,
        )
