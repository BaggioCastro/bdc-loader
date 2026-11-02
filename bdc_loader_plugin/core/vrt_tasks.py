"""Turns the selected results into VRT build tasks: one per scene, crop or area mosaic, reusing downloaded files."""

import os

from qgis.core import (
    QgsProject,
)

from ..i18n import count_label
from ..logger import info as _log_info
from ..logger import warning as _log_warning
from ..stac.parsers import extract_tile_from_item
from . import output_crs
from .band_selection import resolve_band
from .download import find_band_download, mosaic_area
from .download_outputs import find_area_band_files, find_area_layer
from .layer_names import (
    area_group_display,
    area_layer_display,
    build_vrt_layer_name,
    layer_key,
)
from .raster_export import write_band_vrt
from .vrt_builder import (
    attach_area_mask,
    build_single_vrt,
    vrt_sources_match,
)


def _band_href(band, item, download_dir, collection_id):
    """The downloaded file of ``band`` for ``item``, else its /vsicurl/ URL; None when the item lacks the band."""
    resolved = resolve_band(band, item.assets)
    if not resolved:
        return None
    local_file = find_band_download(download_dir, collection_id, item.id, band, resolved)
    if local_file:
        return local_file
    href = item.assets[resolved].href
    # Items rebuilt from the download folder (local_catalog) point at the files themselves.
    return href if os.path.isfile(href) else f"/vsicurl/{href}"


def _available_assets(items):
    """Asset keys of the first item, without the thumbnail, for the missing-band message."""
    return [key for key in items[0].assets.keys() if key != "thumbnail"] if items else []


def _split_unchanged_tasks(vrt_tasks):
    """Split *vrt_tasks* into (to_build, unchanged).

    A task is unchanged when its VRT already exists referencing exactly the
    same sources *and* its layer is loaded in the project. Rebuilding those
    costs a remote open per band and discards a layer QGIS has already
    rendered, for an identical result. A source that moved from /vsicurl/ to a
    finished download changes the reference, so a downloaded scene does get its
    VRT re-pointed at the local file.
    """
    try:
        loaded_names = {layer_key(layer) for layer in QgsProject.instance().mapLayers().values()}
    except Exception as exc:
        # Never let a project-state query stop a build from being prepared.
        _log_warning(f"Could not read loaded layer names, rebuilding all VRTs: {exc}")
        return list(vrt_tasks), []

    to_build, unchanged = [], []
    for task in vrt_tasks:
        # A task missing either key cannot be shown to be unchanged, so it
        # builds — the safe direction.
        name = task.get("layer_name")
        hrefs = task.get("hrefs")
        if name in loaded_names and hrefs and vrt_sources_match(task.get("vrt_path", ""), hrefs):
            unchanged.append(task)
        else:
            to_build.append(task)
    return to_build, unchanged


def _stack_downloaded_bands(band_files, bands, vrt_path):
    """Stack per-band downloads into one local VRT layer; returns its path or None."""
    if not band_files:
        return None
    ok, result = write_band_vrt(vrt_path, band_files, bands)
    if not ok:
        _log_warning(f"Could not stack the downloaded bands, loading from the server instead: {result}")
        return None
    return result


def _build_task(task, mask_dir):
    """Build one layer's VRT; a feature crop is then cut to its shape (``task["area_mask"]``)."""
    result = build_single_vrt(task)
    if result[0] == "ok" and task.get("area_mask"):
        attach_area_mask(result[1], task["area_mask"], mask_dir)
    return result


def _local_layer(item, props, collection_id, date_str, naming_format):
    """(file, layer name, group) of a downloaded multiband file, loaded as it is on disk."""
    tile = extract_tile_from_item(item).replace("/", "-")
    bands = list(props.get("bdc:local_layer_bands") or [])
    layer_name = build_vrt_layer_name(item.id, collection_id, tile, date_str, bands, False, naming_format)
    return props["bdc:local_layer"], layer_name, f"{collection_id} / {tile}"


class VrtTasks:
    """Turns the selected results into VRT build tasks: one per scene, crop or area mosaic, reusing downloaded files."""

    # ------------------------------------------------------------------
    # Phase 1: prepare VRT tasks
    # ------------------------------------------------------------------
    def _prepare_vrt_tasks(
        self,
        selected_items,
        bands,
        num_bands,
        band_composition,
        collection_id,
        has_mixed_resolution,
        naming_format,
        errors,
    ):
        """Build list of VRT task dicts from selected items.

        Returns (vrt_tasks, prebuilt_layers): prebuilt_layers are mosaic/crop
        items whose exact band composition was already downloaded as a real,
        pixel-masked GeoTIFF (see download.DownloadManager); those load
        straight from disk with no VRT build, since the file is already
        cropped to the shape/extent. They still get the shape overlay in
        _load_vrt_layers, which is what keeps the edge smooth on the canvas.
        """
        cutline_path = self._get_shape_cutline_geometry() or self._get_extent_cutline()
        # Cached for the mask built in _load_vrt_layers.
        self._cached_cutline_path = cutline_path
        # One cutline per area, also looked up by group for the shape overlay.
        self._area_cutlines = {}
        self._group_cutlines = {}
        # Short names shown in the Layers panel for crop and vector-feature areas
        self._layer_displays = {}
        self._group_displays = {}
        checked_tiles = self._crop_checked_tiles()

        vrt_tasks, prebuilt_layers = [], []
        for item in selected_items:
            date_str = item.datetime.strftime("%Y-%m-%d") if hasattr(item, "datetime") and item.datetime else "unknown"
            props = getattr(item, "properties", {}) or {}
            if props.get("bdc:local_layer"):
                prebuilt_layers.append(_local_layer(item, props, collection_id, date_str, naming_format))
                continue
            is_shape_mosaic = bool(props.get("bdc:is_shape_mosaic"))
            is_extent_crop = bool(props.get("bdc:is_extent_crop"))
            is_any_mosaic = is_shape_mosaic or is_extent_crop
            source_items = list(getattr(item, "_source_items", [])) if is_any_mosaic else [item]
            if is_extent_crop and checked_tiles is not None:
                source_items = [si for si in source_items if extract_tile_from_item(si).upper() in checked_tiles]
                if not source_items:
                    continue
            if is_any_mosaic:
                target = self._register_area(item, date_str, collection_id, bands, naming_format, cutline_path)
                if target["prebuilt"]:
                    prebuilt_layers.append(target["prebuilt"])
                    continue
                tile = tile_safe = target["tile"]
                group_name, item_cutline = target["group"], target["cutline"]
            else:
                tile = extract_tile_from_item(item)
                tile_safe = tile.replace("/", "-")
                group_name = f"{collection_id} / {tile_safe}"
                item_cutline = cutline_path
            task = self._composition_task(
                bands,
                band_composition,
                source_items,
                item,
                is_any_mosaic,
                collection_id,
                (tile, tile_safe, date_str),
                (self._download_dir, self.output_dir.text()),
                has_mixed_resolution,
                item_cutline,
                group_name,
                naming_format,
                errors,
            )
            if task:
                if is_shape_mosaic and not is_extent_crop and item_cutline:
                    # Cut to the feature by a mask band rasterized once (see attach_area_mask).
                    task["area_mask"] = item_cutline
                vrt_tasks.append(task)

        vrt_tasks, unchanged = _split_unchanged_tasks(vrt_tasks)
        # Read by the report, so a second Load of the same layers is not taken for a failure.
        self._unchanged_layers = len(unchanged)
        if unchanged:
            _log_info(f"{len(unchanged)} layers already loaded from the same sources; not rebuilt")
            self._set_status(f"{count_label(len(unchanged), 'layer', 'layers')} already up to date; skipped.", "info")
        return vrt_tasks, prebuilt_layers

    def _crop_checked_tiles(self):
        """Tiles left checked in the Tile Filter in extent-crop mode, or None when every tile counts."""
        if self._current_result_mode != "extent_crop":
            return None
        tile_filter = self._tile_filter_dict
        if not tile_filter:
            return None
        return {tid for tid, td in tile_filter.items() if td["checked"]}

    def _register_area(self, item, date_str, collection_id, bands, naming_format, cutline_path):
        """Names, group and cutline of a crop or vector-feature mosaic, and a prebuilt file if downloaded.

        A prior Download already wrote this area and band composition,
        already cropped to the shape/extent: that file is loaded instead of
        re-deriving a VRT from the (possibly remote) tiles. Any output
        projection will do; QGIS reprojects a mismatched one on the fly.
        """
        props = getattr(item, "properties", {}) or {}
        is_extent_crop = bool(props.get("bdc:is_extent_crop"))
        area = mosaic_area(item)
        area_date = props.get("bdc:mosaic_date") or date_str
        tile = f"{area}_{date_str}"
        group_name = f"{collection_id} / {area}"
        layer_name = build_vrt_layer_name(item.id, collection_id, tile, date_str, bands, True, naming_format)
        feature_name = props.get("bdc:feature_name")
        self._layer_displays[layer_name] = area_layer_display(
            collection_id, "crop" if is_extent_crop else (feature_name or area), area_date, bands
        )
        self._group_displays[group_name] = area_group_display(
            collection_id,
            area,
            props.get("bdc:crop_bbox") if is_extent_crop else None,
            None if is_extent_crop else feature_name,
        )
        if area not in self._area_cutlines:
            self._area_cutlines[area] = self._cutline_for_item(item) or cutline_path
        item_cutline = self._area_cutlines[area]
        # An extent crop is shown as the straight rectangle of the grid
        # that covers the box, so its overview gets no mask either.
        self._group_cutlines[group_name] = None if is_extent_crop else item_cutline

        download_dir = self._download_dir
        local_tags = [""] + [option.tag for option in output_crs.build_options() if option.tag]
        local_file = find_area_layer(download_dir, collection_id, area, area_date, bands, local_tags)
        if not local_file:
            local_file = _stack_downloaded_bands(
                find_area_band_files(download_dir, collection_id, area, area_date, bands, local_tags),
                bands,
                # Its own file name: the layer it replaces may still hold the
                # remote <name>.vrt open and write it back when it closes.
                os.path.join(self.output_dir.text(), f"{layer_name}_downloaded.vrt"),
            )
        prebuilt = (local_file, layer_name, group_name) if local_file else None
        return {"tile": tile, "group": group_name, "cutline": item_cutline, "prebuilt": prebuilt}

    def _composition_task(
        self,
        bands,
        band_composition,
        source_items,
        item,
        is_mosaic,
        collection_id,
        tile_names,
        dirs,
        has_mixed_resolution,
        cutline,
        group_name,
        naming_format,
        errors,
    ):
        """VRT build task for ``bands``: a single band, or an RGB composite of three.

        ``tile_names`` is (tile, file-safe tile, date); ``dirs`` is (folder
        searched for downloaded sources, folder the VRT is written to).
        """
        tile, tile_safe, date_str = tile_names
        source_dir, output_dir = dirs
        if len(bands) == 1:
            return self._build_single_band_task(
                bands[0],
                source_items,
                item,
                is_mosaic,
                collection_id,
                tile,
                tile_safe,
                date_str,
                source_dir,
                output_dir,
                cutline,
                group_name,
                naming_format,
                errors,
            )
        return self._build_rgb_task(
            bands,
            band_composition,
            source_items,
            item,
            is_mosaic,
            collection_id,
            tile,
            tile_safe,
            date_str,
            source_dir,
            output_dir,
            has_mixed_resolution,
            cutline,
            group_name,
            naming_format,
            errors,
        )

    def _build_single_band_task(
        self,
        band,
        source_items,
        item,
        is_mosaic,
        collection_id,
        tile,
        tile_safe,
        date_str,
        download_dir,
        output_path,
        cutline_path,
        group_name,
        naming_format,
        errors,
    ):
        """VRT task mosaicking ``band`` from every source item that has it; None when none has."""
        hrefs = [href for href in (_band_href(band, src, download_dir, collection_id) for src in source_items) if href]
        if not hrefs:
            errors.append(f"{tile}: band '{band}' not available (available: {_available_assets(source_items)})")
            return None

        layer_name = build_vrt_layer_name(item.id, collection_id, tile_safe, date_str, [band], is_mosaic, naming_format)
        return {
            "vrt_path": os.path.join(output_path, f"{layer_name}.vrt"),
            "hrefs": hrefs,
            "separate": False,
            "mixed_res": False,
            "tile": tile,
            "tile_safe": tile_safe,
            "layer_name": layer_name,
            "band_desc": f"Mosaic {band}" if is_mosaic else band,
            "cutline_path": cutline_path,
            "group_name": group_name,
        }

    def _build_rgb_task(
        self,
        bands,
        band_composition,
        source_items,
        item,
        is_mosaic,
        collection_id,
        tile,
        tile_safe,
        date_str,
        download_dir,
        output_path,
        has_mixed_resolution,
        cutline_path,
        group_name,
        naming_format,
        errors,
    ):
        """VRT task stacking ``bands`` as RGB; None when a band is missing.

        A mosaic stacks one group of sources per band (``href_groups``); a
        single scene stacks one source per band (``hrefs``).
        """
        if is_mosaic:
            href_groups = [
                [href for href in (_band_href(band, src, download_dir, collection_id) for src in source_items) if href]
                for band in bands
            ]
            missing = [band for band, group in zip(bands, href_groups) if not group]
            available = _available_assets(source_items)
        else:
            hrefs = [_band_href(band, item, download_dir, collection_id) for band in bands]
            missing = [band for band, href in zip(bands, hrefs) if href is None]
            available = _available_assets([item])
        if missing:
            errors.append(f"{tile}: bands {missing} not available (available: {available})")
            return None

        layer_name = build_vrt_layer_name(item.id, collection_id, tile_safe, date_str, bands, is_mosaic, naming_format)
        task = {"vrt_path": os.path.join(output_path, f"{layer_name}.vrt"), "hrefs": [] if is_mosaic else hrefs}
        if is_mosaic:
            task["href_groups"] = href_groups
        task.update(
            {
                "separate": True,
                "mixed_res": has_mixed_resolution,
                "tile": tile,
                "tile_safe": tile_safe,
                "layer_name": layer_name,
                "band_desc": f"Mosaic RGB {band_composition}" if is_mosaic else f"RGB {band_composition}",
                "cutline_path": cutline_path,
                "group_name": group_name,
            }
        )
        return task

    def _cutline_for_group(self, group_name):
        """Return the cutline geometry path matching a VRT's group.

        Each crop or feature mosaic has its own group (named after its area
        tag) and cutline, recorded while the tasks are built; other groups get
        the single cached cutline (merged shape, or the extent-crop bbox).
        """
        group_cutlines = getattr(self, "_group_cutlines", {}) or {}
        if group_name in group_cutlines:
            return group_cutlines[group_name]
        return getattr(self, "_cached_cutline_path", None)
