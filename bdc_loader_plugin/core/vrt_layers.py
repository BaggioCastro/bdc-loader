"""Opens the built VRTs as raster layers on the UI thread and adds them, with their area masks, to the layer tree."""

import os
import time
from concurrent.futures import ThreadPoolExecutor

from qgis.core import (
    QgsFillSymbol,
    QgsInvertedPolygonRenderer,
    QgsProject,
    QgsRasterLayer,
    QgsSingleSymbolRenderer,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QCoreApplication

from ..i18n import count_label, tr
from ..logger import error as _log_error
from ..logger import info as _log_info
from ..logger import warning as _log_warning
from ..widgets.timeline_slider import _timeline_info_for_layer
from .layer_names import (
    _ts_points_layer_pos,
    find_group,
    layer_key,
    set_display_name,
)
from .layer_style import _new_raster_layer, _render_ranges, _style_raster_layer
from .overview_cache import _file_digest
from .render_ranges import estimate_vrt_render_ranges
from .ui_wait import wait_slice
from .vrt_builder import (
    vrt_has_direct_remote_source,
    vrt_has_mask_band,
)
from .vrt_tasks import _build_task

# Layers opened at once in worker threads: each open can read the remote
# raster, and the BDC server throttles a client that opens many connections.
_LAYER_OPEN_WORKERS = 4


def _resolve_mask_target_group(group_cache, group_name, root):
    """Choose the layer-tree node a group's shape mask should be inserted into.

    Returns (node, missing). When group_name is in group_cache, returns (that
    group, False). When it is absent, returns (root, True) so the caller warns
    and falls back to the project root — never silently attaching the mask to an
    unrelated group (e.g. the first cached one), which would hide the wrong
    layers.
    """
    grp = group_cache.get(group_name)
    if grp is not None:
        return grp, False
    return root, True


def _show_one_date_per_series(layers):
    """Turn on one date per series (collection, tile, bands) touched by ``layers``.

    Every visible layer is drawn on each pan and zoom, and the dates of a
    series cover the same ground, so all but one would only add reads. The
    earliest date among ``layers`` stays on; every other date of its series,
    loaded now or before, is turned off and stays in the Layers panel for the
    timeline. Layers whose name gives no date are left as they are. Returns
    [(series key, id of the layer left on)], sorted by series key.
    """
    root = QgsProject.instance().layerTreeRoot()
    first = {}
    for layer in layers:
        info = _timeline_info_for_layer(layer, root)
        if info is None:
            continue
        collection, tile, date_str, bands = info
        key = (collection, tile, bands)
        if key not in first or date_str < first[key][0]:
            first[key] = (date_str, layer.id())
    keep = {layer_id for _date, layer_id in first.values()}
    for layer in QgsProject.instance().mapLayers().values():
        info = _timeline_info_for_layer(layer, root)
        if info is None or (info[0], info[1], info[3]) not in first:
            continue
        node = root.findLayer(layer.id())
        if node is not None:
            node.setItemVisibilityChecked(layer.id() in keep)
    return sorted((key, layer_id) for key, (_date, layer_id) in first.items())


class VrtLayers:
    """Opens the built VRTs as raster layers on the UI thread and adds them, with their area masks, to the layer tree."""

    def _precompute_render_ranges(self, vrt_paths):
        """Precompute per-band display ranges in background worker threads for any uncomputed VRTs."""
        if not vrt_paths:
            return

        cache = getattr(self, "_render_ranges_cache", None)
        if cache is None:
            self._render_ranges_cache = {}
            cache = self._render_ranges_cache

        paths_to_sample = [vp for vp, ln, gn in vrt_paths if vp not in cache]
        if not paths_to_sample:
            return

        n_workers = min(8, len(paths_to_sample))
        executor = ThreadPoolExecutor(max_workers=n_workers)
        try:
            future_map = {executor.submit(estimate_vrt_render_ranges, vp): vp for vp in paths_to_sample}
            pending = set(future_map)
            # Short waits with processEvents() in between keep the dialog responsive.
            while pending:
                done, pending = wait_slice(pending)
                for future in done:
                    vp = future_map[future]
                    try:
                        ranges = future.result()
                        # An empty sample is kept too: it is what marks a blank layer.
                        if ranges or getattr(ranges, "empty", False):
                            cache[vp] = ranges
                    except Exception as exc:
                        _log_warning(f"Background render range sampling failed for {vp}: {exc}")
        finally:
            executor.shutdown(wait=False)

    def _open_raster_layers(self, jobs):
        """Open ``jobs`` [(vrt_path, layer_name)] keeping the UI responsive.

        The slow part, sampling each source for its display range (over
        /vsicurl/ up to a couple of seconds per layer), runs in worker
        threads; each layer is then built and styled on the UI thread (see
        _new_raster_layer). Returns {vrt_path: layer or None} in input order.
        """
        cache = getattr(self, "_render_ranges_cache", {})
        results = {}
        if not jobs:
            return results
        self.progress_bar.setFormat(tr("Adding layer %v/%m"))
        self.progress_bar.setRange(0, len(jobs))
        self.progress_bar.setValue(0)
        executor = ThreadPoolExecutor(max_workers=min(_LAYER_OPEN_WORKERS, len(jobs)))
        try:
            futures = {
                executor.submit(_render_ranges, vrt_path, cache): (vrt_path, layer_name)
                for vrt_path, layer_name in jobs
            }
            pending = set(futures)
            done_count = 0
            while pending:
                done, pending = wait_slice(pending)
                for future in done:
                    vrt_path, layer_name = futures[future]
                    done_count += 1
                    self.progress_bar.setValue(done_count)
                    try:
                        render_ranges = future.result()
                    except Exception as exc:
                        _log_warning(f"Could not sample {layer_name}: {exc}")
                        render_ranges = None
                    try:
                        layer = _new_raster_layer(vrt_path, layer_name, own_stretch=bool(render_ranges))
                    except Exception as exc:
                        _log_warning(f"Could not open {layer_name}: {exc}")
                        results[vrt_path] = None
                        continue
                    results[vrt_path] = _style_raster_layer(layer, vrt_path, layer_name, render_ranges)
        finally:
            executor.shutdown(wait=False)
        return {vrt_path: results.get(vrt_path) for vrt_path, _name in jobs}

    def _restore_overwritten_vrts(self):
        """Rebuild any VRT a just-removed layer wrote back over on closing.

        GDAL saves a VRT whose in-memory copy changed (QGIS stores band
        statistics in it) when the last handle closes, which for a replaced
        layer is after the new VRT was written to the same path.
        """
        for vrt_path, (task, mask_dir, digest) in (getattr(self, "_built_vrts", None) or {}).items():
            if _file_digest(vrt_path) != digest:
                _log_info(f"{os.path.basename(vrt_path)} was overwritten by the layer it replaces; rebuilding it")
                _build_task(task, mask_dir)

    def _load_vrt_layers(self, vrt_paths):
        """Load generated VRTs as layers in QGIS project. Returns (loaded, replaced, skipped_dup)."""
        self._set_status(f"Adding {count_label(len(vrt_paths), 'layer', 'layers')} to the map...", "info")
        QCoreApplication.processEvents()
        existing = {layer_key(lyr): (lid, lyr) for lid, lyr in QgsProject.instance().mapLayers().items()}
        group_displays = getattr(self, "_group_displays", {})
        auto_render = self.auto_select_check.isChecked()
        load_t0 = time.time()
        canvas = self.iface.mapCanvas()
        canvas.setRenderFlag(False)
        root = QgsProject.instance().layerTreeRoot()
        loaded = replaced = 0
        try:
            group_names = {gn for _, _, gn in vrt_paths}
            group_cache = self._ensure_layer_groups(root, group_names, group_displays)
            replacing, skipped_dup = self._retire_replaced_layers(vrt_paths, existing)
            layers_to_add, replaced = self._open_new_layers(vrt_paths, existing, replacing)
            shown_series = []
            if layers_to_add:
                loaded = self._add_layers_to_groups(layers_to_add, group_cache, auto_render)
                if auto_render:
                    shown_series = _show_one_date_per_series([layer for layer, _group in layers_to_add])
                self._add_shape_masks(vrt_paths, group_names, group_cache, group_displays, root)
        finally:
            canvas.setRenderFlag(True)

        load_time = time.time() - load_t0
        _log_info(
            f"Layer loading: {loaded} layers in {load_time:.2f}s ({load_time / max(loaded, 1) * 1000:.0f}ms/layer)"
        )
        if loaded > 0 and auto_render:
            canvas.refresh()
        if loaded > 0 and self._timeline_toolbar:
            self._timeline_toolbar.scan_project_layers()
        if shown_series:
            # The timeline follows the active layer to the date left on.
            shown = QgsProject.instance().mapLayer(shown_series[0][1])
            if shown is not None:
                self.iface.setActiveLayer(shown)
        return loaded, replaced, skipped_dup

    def _ensure_layer_groups(self, root, group_names, group_displays):
        """{group name: layer tree group}, creating missing groups above the time series points layer."""
        group_cache = {}
        for name in group_names:
            group = find_group(root, name)
            if group is None:
                group = root.insertGroup(_ts_points_layer_pos(root), name)
            if name in group_displays:
                set_display_name(group, name, group_displays[name])
            group_cache[name] = group
        return group_cache

    def _retire_replaced_layers(self, vrt_paths, existing):
        """Remove the raster layers about to be rebuilt; ({name: was remote}, non-raster duplicates).

        Done before any replacement is built: GDAL hands out shared dataset
        handles, so a VRT opened while the outgoing layer still holds it comes
        back from cache with the old sources, which is why a scene rebuilt
        against a fresh download kept reading over the network even though the
        .vrt on disk already pointed at the local file.
        """
        replacing, to_remove, skipped_dup = {}, [], 0
        for _vrt_path, layer_name, _group in vrt_paths:
            if layer_name not in existing:
                continue
            old_lid, old_lyr = existing[layer_name]
            if old_lyr and isinstance(old_lyr, QgsRasterLayer):
                # "Upgraded" counts only a layer that actually stopped reading
                # over the network, not every replacement.
                replacing[layer_name] = vrt_has_direct_remote_source(old_lyr.source())
                to_remove.append(old_lid)
            else:
                skipped_dup += 1
        if to_remove:
            QgsProject.instance().removeMapLayers(to_remove)
            self._restore_overwritten_vrts()
        return replacing, skipped_dup

    def _open_new_layers(self, vrt_paths, existing, replacing):
        """[(layer, group name)] of the valid new layers, and how many moved from remote to local sources."""
        layer_displays = getattr(self, "_layer_displays", {})
        # A non-raster duplicate is already counted and left alone.
        to_open = [(vp, ln, gn) for vp, ln, gn in vrt_paths if not (ln in existing and ln not in replacing)]
        opened = self._open_raster_layers([(vp, ln) for vp, ln, _g in to_open])
        layers, replaced = [], 0
        for vrt_path, layer_name, group_name in to_open:
            layer = opened.get(vrt_path)
            if not (layer and layer.isValid()):
                continue
            if layer_name in layer_displays:
                set_display_name(layer, layer_name, layer_displays[layer_name])
            layers.append((layer, group_name))
            if replacing.get(layer_name) and not vrt_has_direct_remote_source(vrt_path):
                replaced += 1
        return layers, replaced

    def _add_layers_to_groups(self, layers_to_add, group_cache, auto_render):
        """Add the layers to the project in batches of 50, collapsed and, unless auto render, turned off."""
        loaded = 0
        batch_size = 50
        for i in range(0, len(layers_to_add), batch_size):
            batch = layers_to_add[i : i + batch_size]
            QgsProject.instance().addMapLayers([lyr for lyr, _ in batch], False)
            for layer, group_name in batch:
                group = group_cache[group_name]
                group.addLayer(layer)
                node = group.findLayer(layer.id())
                if node:
                    node.setExpanded(False)
                    if not auto_render:
                        node.setItemVisibilityChecked(False)
                loaded += 1
            QCoreApplication.processEvents()
        return loaded

    def _add_shape_masks(self, vrt_paths, group_names, group_cache, group_displays, root):
        """Paint the outside of each shape opaque over groups whose layers are not cut to it.

        The overlay is an inverted-polygon vector layer, so its boundary is
        drawn antialiased at screen resolution; a raster mask can only step
        along its pixel grid. A layer already cut to the shape (a VRT with a
        mask band, or a downloaded crop) needs none; the overlay is the
        fallback when cutting the VRT failed. An extent crop's cutline is the
        rectangle the raster was cropped to, so it never needs one.
        """
        if self._current_result_mode == "extent_crop":
            return
        uncut_groups = {
            gn for vp, _ln, gn in vrt_paths if str(vp).lower().endswith(".vrt") and not vrt_has_mask_band(vp)
        }
        added = set()
        for group_name in group_names:
            if group_name not in uncut_groups:
                continue
            cutline = self._cutline_for_group(group_name)
            if not cutline or cutline in added:
                continue
            added.add(cutline)
            try:
                self._add_shape_mask(group_name, cutline, group_cache, group_displays, root)
            except Exception as e:
                _log_error(f"Mask error: {e}")
        if added:
            _log_info(f"Shape masks added: {len(added)}")

    def _add_shape_mask(self, group_name, cutline, group_cache, group_displays, root):
        # Named after the group, so a reload replaces it.
        mask_name = f"{group_name} (mask)"
        for lid, lyr in list(QgsProject.instance().mapLayers().items()):
            if layer_key(lyr) == mask_name:
                QgsProject.instance().removeMapLayer(lid)
        mask_layer = QgsVectorLayer(cutline, mask_name, "ogr")
        if not mask_layer.isValid():
            return
        if group_name in group_displays:
            set_display_name(mask_layer, mask_name, "Outside the area (mask)")
        symbol = QgsFillSymbol.createSimple(
            {"color": "255,255,255,255", "outline_color": "80,80,80,255", "outline_width": "0.4"}
        )
        mask_layer.setRenderer(QgsInvertedPolygonRenderer(QgsSingleSymbolRenderer(symbol)))
        QgsProject.instance().addMapLayer(mask_layer, False)
        group, missing = _resolve_mask_target_group(group_cache, group_name, root)
        if missing:
            _log_warning(
                f"Mask target group '{group_name}' not found in the layer tree; "
                "adding the shape mask to the project root instead"
            )
        group.insertLayer(0, mask_layer)
        node = group.findLayer(mask_layer.id())
        if node:
            node.setExpanded(False)
