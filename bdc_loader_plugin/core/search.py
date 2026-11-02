# -*- coding: utf-8 -*-
"""
Search engine mixin for BDCLoaderDialog.

Provides:
- `SearchEngine` — mixin inherited by BDCLoaderDialog that handles:
  - STAC item search with tile, extent, and shapefile spatial filters
  - Shape-mosaic mode: groups scenes by date per shapefile feature
  - Extent-crop mode: groups scenes by date within a bbox
  - Search parameter validation (tiles, extent, bands, dates)
  - Lazy thumbnail loading with viewport-aware preloading
  - Result widget population and status feedback

Dependencies:
  ui.result_widgets — per-item result widgets and shape-mosaic wrappers
  stac.parsers      — tile pattern validation
  stac.client       — STAC URL and pystac_client
"""

import logging
import re
import time
from datetime import datetime

from qgis.PyQt.QtCore import QCoreApplication, QPoint, QTimer
from qgis.PyQt.QtWidgets import QMessageBox

_logger = logging.getLogger("bdc_loader")

from ..i18n import count_label, failure_text, tr
from ..stac.client import STAC_URL, open_stac_client, search_items
from ..stac.parsers import group_items_by_date
from ..timing import THUMBNAILS_AFTER_LAYOUT_MS
from ..ui.main_styles import _SEARCH_BTN_STALE_STYLE, _SEARCH_BTN_STYLE
from ..ui.result_widgets import ResultItemWidget
from ..vendored import ensure_pystac_client
from ..widgets.cursors import apply_click_cursors
from . import local_catalog
from .catalog_data import COLLECTIONS
from .ui_wait import run_in_worker

# How long the first search waits for the STAC root catalog before searching
# the downloaded images instead.
_CLIENT_OPEN_BUDGET_S = 15


_HTML_TITLE_RE = re.compile(r"<title>\s*(.*?)\s*</title>", re.IGNORECASE | re.DOTALL)


def _readable_error(exc):
    """The message of ``exc``, with an HTML error page reduced to its title.

    pystac_client puts the server's error body in the exception; behind the
    BDC's nginx a 502 or 504 is an HTML page.
    """
    text = str(exc)
    if "<html" not in text.lower():
        return text
    match = _HTML_TITLE_RE.search(text)
    title = match.group(1) if match else "error page"
    return f"the BDC STAC server answered {title}. It is usually temporary; try again in a few minutes."


# Words in an error that mean the server could not be reached.
_CONNECTION_ERROR_WORDS = (
    "connection",
    "timeout",
    "unreachable",
    "refused",
    "reset by peer",
    "name or service not known",
)


def _tile_query(valid_tiles):
    """STAC query for the tile filter: path/row for WRS2-style ids, bdc:tiles otherwise."""
    from ..stac.parsers import ROW_PATH_PATTERN

    if not any(ROW_PATH_PATTERN.match(t) for t in valid_tiles):
        return {"bdc:tiles": {"in": valid_tiles}}
    paths, rows = [], []
    for tile in valid_tiles:
        parts = re.split(r"[/_ -]", tile)
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            paths.append(f"{int(parts[0]):03d}")
            rows.append(f"{int(parts[1]):03d}")
    if not paths:
        return None
    if len(paths) == 1:
        return {"path": {"eq": paths[0]}, "row": {"eq": rows[0]}}
    return {"path": {"in": list(dict.fromkeys(paths))}, "row": {"in": list(dict.fromkeys(rows))}}


def _no_results_message(config, start, end, tiles, bbox, shape_missed, scene_count):
    """Why a search found nothing, short enough for the two lines of the status line."""
    collection_id = config.get("id", "")
    first, last = (config.get("temporal") or (None, None))[:2]
    if first and last and (end < first[:10] or start > last[:10]):
        return (
            f"No images found. {collection_id} has images from {first[:10]} to {last[:10]}; choose a period inside it."
        )
    if shape_missed:
        return (
            f"No images found. {count_label(scene_count, 'scene covers', 'scenes cover')} the box around the "
            "vector features, but none crosses the checked features."
        )
    if tiles and config.get("has_tiles", True):
        return (
            f"No images found in tiles {', '.join(tiles)} from {start} to {end}. "
            f"Check that they belong to the {config.get('grid', 'BDC')} grid of {collection_id}."
        )
    if bbox:
        return (
            f"No images found over this area from {start} to {end}. It may be outside the coverage of "
            f"{collection_id}; try a longer period or another area."
        )
    return f"No images found from {start} to {end}."


class SearchEngine:
    """Provides STAC search, validation, and thumbnail loading."""

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def _validate_search_params(self):
        """Validate parameters before search. Returns (ok, msg) tuple."""
        from ..stac.parsers import MGRS_PATTERN, ROW_PATH_PATTERN, STG_PATTERN, TILE_PATTERN, WRS2_PATTERN

        problems = []

        collection_name = self._current_collection_name()
        config = COLLECTIONS.get(collection_name, {})
        has_tiles = config.get("has_tiles", True)

        # Spatial
        valid_tiles = self.get_tiles_list()
        bbox = self.get_bbox_from_extent()
        shape_bbox = self._get_shape_bbox()

        shape_without_features = (
            self._shape_vector_layer is not None
            and not shape_bbox
            and not self.shape_merge_check.isChecked()
            and not self._get_selected_shape_fids()
        )
        if not bbox and not valid_tiles and not shape_bbox:
            if shape_without_features:
                problems.append("No feature of the vector file is checked. Check at least one, or Merge all.")
            elif has_tiles:
                problems.append("Define a spatial extent, provide tiles, or load a shapefile to search.")
            else:
                problems.append("This collection has no tile system. Define a spatial extent or load a shapefile.")
        if bbox:
            xmin, ymin, xmax, ymax = (float(v) for v in bbox)
            if xmin >= xmax or ymin >= ymax:
                problems.append("The extent has no area. Drag a box on the map, or type four different coordinates.")
            elif xmin < -180 or xmax > 180 or ymin < -90 or ymax > 90:
                problems.append("The extent is outside longitude -180 to 180 and latitude -90 to 90.")

        # Tiles format check
        raw_tiles = self.tiles_input.text().strip()
        if raw_tiles and has_tiles:
            raw_list = [t.strip() for t in raw_tiles.replace(";", ",").split(",") if t.strip()]
            invalid = [
                t
                for t in raw_list
                if not (
                    TILE_PATTERN.match(t)
                    or MGRS_PATTERN.match(t)
                    or WRS2_PATTERN.match(t)
                    or STG_PATTERN.match(t)
                    or ROW_PATH_PATTERN.match(t)
                )
            ]
            if invalid:
                problems.append(
                    f"Tiles with invalid format: {', '.join(invalid)}. "
                    f"Use BDC (031023), MGRS (23LMF), WRS2 (233067), STG (h13v10) or Row/Path (039/018)."
                )

        # Bands: any number can be searched and downloaded; Load layers
        # checks its own 1-or-3 rule.
        if self.selected_bands.count() == 0:
            problems.append("No band selected. Select at least 1 band.")

        # Dates
        start = self.range_slider.get_start_date()
        end = self.range_slider.get_end_date()
        if start > end:
            problems.append("Start date must not be after end date.")

        if problems:
            msg = f"<b>{tr('Issues found:')}</b><br><br>"
            msg += "<br>".join(f"- {tr(p)}" for p in problems)
            return False, msg

        return True, ""

    # ------------------------------------------------------------------
    # Main STAC search
    # ------------------------------------------------------------------
    def search_stac(self):
        """Run a search; a second click while one runs is ignored.

        The STAC request runs in a worker while this method pumps the event
        loop, so the Search button and the collection stay disabled until it
        returns.
        """
        if self._search_in_progress:
            return
        self._search_in_progress = True
        # The collection is read when the search starts; changing it while
        # the request runs would label the results with the wrong one.
        held = [
            w for w in (getattr(self, "search_btn", None), getattr(self, "collection_combo", None)) if w is not None
        ]
        for widget in held:
            widget.setEnabled(False)
        try:
            self._search_stac_unguarded()
        finally:
            self._search_in_progress = False
            for widget in held:
                widget.setEnabled(True)
        # Results of this search take the parameters it ended with; results kept
        # from an earlier search (the new one stopped at validation) keep theirs.
        if self.result_widgets and self._searched_params is None:
            self._searched_params = self._search_params()
        self._results_fresh = True
        self._check_search_params()

    # ------------------------------------------------------------------
    # Results against the parameters they were searched with
    # ------------------------------------------------------------------
    # Names of the search parameters, as the status line lists them.
    _PARAM_LABELS = {"collection": "collection", "bands": "bands", "period": "period", "area": "area", "limit": "limit"}

    def _search_params(self):
        """What the results depend on: collection, bands, period, area and result limit."""
        bbox = self.get_bbox_from_extent()
        return {
            "collection": COLLECTIONS.get(self._current_collection_name(), {}).get("id", ""),
            "bands": tuple(self._selected_band_names()),
            "period": (
                self.range_slider.get_start_date().toString("yyyy-MM-dd"),
                self.range_slider.get_end_date().toString("yyyy-MM-dd"),
            ),
            "area": (
                tuple(round(float(v), 6) for v in bbox) if bbox else None,
                self.is_extent_crop_mode(),
                tuple(self.get_tiles_list()),
                self._shape_search_signature(),
            ),
            "limit": self.limit_spin.value(),
        }

    def _changed_search_params(self):
        """Names of the parameters that differ from those of the results on screen."""
        searched = self._searched_params
        if not searched or not self.result_widgets:
            return []
        current = self._search_params()
        return [name for name in self._PARAM_LABELS if current[name] != searched[name]]

    def _watch_search_params(self):
        """Check the results against the panel whenever a search parameter changes."""
        self._params_timer = QTimer(self)
        self._params_timer.setSingleShot(True)
        self._params_timer.setInterval(0)
        self._params_timer.timeout.connect(self._check_search_params)
        schedule = self._params_timer.start
        for signal in (
            self.range_slider.start_date_edit.dateChanged,
            self.range_slider.end_date_edit.dateChanged,
            self.selected_bands.model().rowsInserted,
            self.selected_bands.model().rowsRemoved,
            self.extent_box.extentChanged,
            self.extent_box.activeChanged,
            self._extent_mode_crop.toggled,
            self.tiles_input.textChanged,
            self.shape_feature_list.itemChanged,
            self.shape_merge_check.toggled,
            self.shape_attr_combo.currentIndexChanged,
            self.shape_file_input.textChanged,
            self.limit_spin.valueChanged,
        ):
            signal.connect(lambda *_args: schedule())

    def _check_search_params(self):
        """Lock Load and Download while the panel no longer matches the results."""
        if self._search_in_progress:
            return
        changed = self._changed_search_params()
        was_fresh = self._results_fresh
        self._show_results_fresh(not changed)
        if changed:
            names = ", ".join(self._PARAM_LABELS[name] for name in changed)
            self._set_status(f"Search parameters changed ({names}). Click Search STAC again.", "warning")
        elif not was_fresh and self.result_widgets:
            self._set_status("The parameters are back to those of the search.", "info")

    def _show_results_fresh(self, fresh):
        """Enable the result actions, or lock them and light Search, for results that no longer match."""
        self._results_fresh = fresh
        usable = fresh and bool(self.result_widgets)
        self.load_btn.setEnabled(usable)
        self.download_selected_btn.setEnabled(usable)
        for widget in self.result_widgets:
            widget.download_btn.setEnabled(fresh)
        self.search_btn.setStyleSheet(_SEARCH_BTN_STYLE if fresh else _SEARCH_BTN_STALE_STYLE)

    def _results_match_panel(self):
        """True when Load and Download may use the results; otherwise says why on the status line."""
        changed = self._changed_search_params()
        if changed:
            self._show_results_fresh(False)
            names = ", ".join(self._PARAM_LABELS[name] for name in changed)
            self._set_status(f"Search parameters changed ({names}). Click Search STAC again.", "warning")
        return not changed

    def _search_stac_unguarded(self):
        """Search the selected collection and fill the results, as items or mosaics by date."""
        pystac_client = ensure_pystac_client()
        ok, msg = self._validate_search_params()
        if not ok:
            QMessageBox.warning(self, "Validation", msg)
            return
        self.clear_results()
        # STAC known offline: search the downloaded images instead of waiting on the network.
        if self._stac_online is False:
            self._search_local_downloads()
            return

        valid_tiles = self.get_tiles_list()
        bbox = self.get_bbox_from_extent()
        shape_search = False
        if not bbox and not valid_tiles:
            # Shapefile mode: the shape's bbox, with results grouped into mosaics by date.
            bbox = self._get_shape_bbox()
            shape_search = bool(bbox and self._is_shape_search_active())

        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self._set_status("Searching images (STAC)...", "info")
        QCoreApplication.processEvents()
        started = time.monotonic()
        try:
            if not self._ensure_stac_client(pystac_client, STAC_URL):
                self._search_local_downloads()
                return
            collection_name = self._current_collection_name()
            config = COLLECTIONS.get(collection_name, {})
            collection_id = config.get("id")
            if not collection_id:
                QMessageBox.warning(self, "Error", f"Collection ID not found for: {collection_name}")
                return
            start = self.range_slider.get_start_date().toString("yyyy-MM-dd")
            end = self.range_slider.get_end_date().toString("yyyy-MM-dd")
            ui_limit = self.limit_spin.value()
            # In mosaic modes (shape or crop) the limit counts dates, not scenes,
            # so more scenes are fetched for enough dates to survive the grouping.
            is_mosaic_mode = shape_search or self.is_extent_crop_mode()
            fetch_limit = min(max(ui_limit * 20, 200), 5000) if is_mosaic_mode else ui_limit
            if shape_search:
                self._set_status("Searching scenes that cross the vector features (STAC)...", "info")
            elif is_mosaic_mode:
                self._set_status("Searching scenes for the crops (STAC)...", "info")
            else:
                self._set_status("Searching images (STAC)...", "info")
            QCoreApplication.processEvents()

            search_params = {"collections": [collection_id], "datetime": f"{start}/{end}", "limit": fetch_limit}
            if bbox:
                search_params["bbox"] = bbox
            if valid_tiles and config.get("has_tiles", True):
                tile_query = _tile_query(valid_tiles)
                if tile_query:
                    search_params["query"] = tile_query
                if bbox and self.is_extent_crop_mode():
                    self._warn_crop_with_tiles(valid_tiles)
            elif valid_tiles:
                self._set_status(
                    "This collection has no tiles: the tile filter is ignored, the extent is used.", "warning"
                )

            items = self._fetch_items(search_params, fetch_limit)
            _logger.debug("STAC search completed in %.2fs, %d items", time.monotonic() - started, len(items))
            raw_items = items[:]
            if shape_search:
                self._search_stac_shape_mode(items, raw_items, ui_limit)
            elif self.is_extent_crop_mode():
                self._search_stac_extent_crop(items, raw_items, ui_limit)
            else:
                self._current_result_mode = "stac_items"
                self._search_stac_finalize(
                    items, raw_items, collection_name, config, shape_search, valid_tiles, bbox, start, end
                )
        except Exception as e:
            self._handle_search_error(e)
        finally:
            self.progress_bar.setVisible(False)

    def _ensure_stac_client(self, pystac_client, stac_url):
        """Open the STAC client once; on failure switch to offline mode and return False."""
        if self.client:
            return True
        try:
            self.client = run_in_worker(open_stac_client, pystac_client, stac_url, budget_s=_CLIENT_OPEN_BUDGET_S)
            return True
        except Exception:
            _logger.warning("STAC connection failed", exc_info=True)
        self._stac_online = False
        self._set_stac_status(False)
        try:
            from qgis.core import Qgis

            self.iface.messageBar().pushMessage(
                "BDC Loader",
                tr("The BDC cannot be reached. Searching the images downloaded on this computer."),
                level=Qgis.MessageLevel.Warning,
                duration=8,
            )
        except Exception:
            pass
        self.progress_bar.setVisible(False)
        return False

    def _search_local_downloads(self):
        """Search the images downloaded on this computer with the collection, period and area filters."""
        collection_name = self._current_collection_name()
        config = COLLECTIONS.get(collection_name, {})
        collection_id = config.get("id", "")
        start = self.range_slider.get_start_date().toString("yyyy-MM-dd")
        end = self.range_slider.get_end_date().toString("yyyy-MM-dd")
        valid_tiles = self.get_tiles_list() if config.get("has_tiles", True) else []
        bbox = self.get_bbox_from_extent() or self._get_shape_bbox()

        # The status line adds the offline mark itself.
        self._set_status("Searching images downloaded on this computer...", "info")
        QCoreApplication.processEvents()
        images = local_catalog.scan_downloads(self._download_dir)
        found = local_catalog.search_local(images, collection_id, start, end, bbox=bbox, tiles=valid_tiles)
        found = found[: self.limit_spin.value()]
        if not found:
            in_collection = sum(1 for image in images if image.collection == collection_id)
            self._set_status(
                f"<b>Offline:</b> no downloaded image of {collection_id} matches this period and area. "
                f"This computer holds {count_label(in_collection, 'downloaded image', 'downloaded images')} "
                f"of this collection and {len(images)} in total.",
                "warning",
            )
            return
        items = [local_catalog.to_stac_item(image) for image in found]
        self._current_result_mode = "stac_items"
        self._search_stac_finalize(items, items, collection_name, config, False, valid_tiles, bbox, start, end)
        self._set_status(
            f"<b>Offline:</b> {count_label(len(items), 'downloaded image', 'downloaded images')} found on this "
            "computer. Layers load from disk; searching the BDC resumes when it can be reached.",
            "warning",
        )

    def _warn_crop_with_tiles(self, valid_tiles):
        tiles_str = ", ".join(valid_tiles[:5])
        if len(valid_tiles) > 5:
            tiles_str += f" (+{len(valid_tiles) - 5})"
        self._set_status(
            f"Crop with tile filter: the search returns only scenes of tiles {tiles_str} inside the extent.",
            "warning",
        )
        QCoreApplication.processEvents()

    def _fetch_items(self, search_params, fetch_limit):
        """Run the search and its pages in a worker, showing the count while the window stays responsive."""
        items = []
        fetched = {"count": 0}
        client = self.client

        def _fetch():
            search = client.search(**search_params)
            for i, item in enumerate(search_items(search)):
                if i >= fetch_limit:
                    break
                items.append(item)
                fetched["count"] = i + 1

        shown = {"count": 0}

        def _show_count():
            if fetched["count"] != shown["count"]:
                shown["count"] = fetched["count"]
                self._set_status(f"Searching images (STAC): {shown['count']} found", "info")

        run_in_worker(_fetch, on_wait=_show_count)
        return items

    def _handle_search_error(self, error):
        """A connection error switches to offline mode and searches the downloads; any other error is shown."""
        _logger.warning("STAC search error: %s", error, exc_info=True)
        text = str(error).lower()
        if any(word in text for word in _CONNECTION_ERROR_WORDS):
            self.client = None  # the client is stale
            self._set_stac_status(False)
            self._search_local_downloads()
            return
        QMessageBox.critical(self, "Error", f"Search error: {_readable_error(error)}")
        self._set_status(failure_text("Search", _readable_error(error)), "error")

    def _search_stac_shape_mode(self, items, raw_items, ui_limit):
        """Handle shape mosaic result mode within search_stac."""
        from qgis.core import (
            QgsCoordinateReferenceSystem,
            QgsCoordinateTransform,
            QgsGeometry,
            QgsProject,
            QgsRectangle,
        )

        collection_name = self._current_collection_name()
        config = COLLECTIONS.get(collection_name, {})
        start = self.range_slider.get_start_date().toString("yyyy-MM-dd")
        end = self.range_slider.get_end_date().toString("yyyy-MM-dd")
        valid_tiles = self.get_tiles_list()
        bbox = self._get_shape_bbox()

        # Per-feature: generate separate mosaics for each selected feature
        if not self.shape_merge_check.isChecked():
            selected_fids = self._get_selected_shape_fids()
            feature_names = {}
            for fid, name, geom in self._shape_features:
                if fid in selected_fids:
                    feature_names[fid] = name
            # Pre-compute CRS transform once (avoid per-item recalculation)
            vlayer_crs = self._shape_vector_layer.crs()
            need_transform = vlayer_crs.authid() != "EPSG:4326"
            xform = None
            if need_transform:
                xform = QgsCoordinateTransform(
                    vlayer_crs, QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance()
                )
            # Assign each STAC item to intersecting features
            all_mosaics = []
            for fid in selected_fids:
                fname = feature_names.get(fid, f"Feature_{fid}")
                fgeom = None
                for f_fid, f_name, f_geom in self._shape_features:
                    if f_fid == fid:
                        fgeom = QgsGeometry(f_geom)
                        break
                if not fgeom:
                    continue
                # Transform feature geometry to EPSG:4326 for comparison with STAC bboxes
                if need_transform:
                    fgeom.transform(xform)
                feat_rect = fgeom.boundingBox()
                # Filter items whose bbox intersects the feature geometry
                feat_items = []
                for it in raw_items:
                    it_bbox = getattr(it, "bbox", None)
                    if it_bbox and len(it_bbox) >= 4:
                        it_rect = QgsRectangle(it_bbox[0], it_bbox[1], it_bbox[2], it_bbox[3])
                        # Quick bbox pre-filter then precise geometry check
                        if it_rect.intersects(feat_rect) and fgeom.intersects(QgsGeometry.fromRect(it_rect)):
                            feat_items.append(it)
                    else:
                        feat_items.append(it)
                if feat_items:
                    _name, area, area_wkt = self._feature_area(fid) or (fname, None, None)
                    mosaics = self._build_shape_mosaic_items(
                        feat_items, feature_name=fname, area=area, area_wkt=area_wkt, feature_fid=fid
                    )
                    all_mosaics.extend(mosaics)
            items = sorted(all_mosaics, key=lambda m: m.datetime or datetime.min, reverse=True)[:ui_limit]
        else:
            area, area_wkt = self._merged_area() or (None, None)
            items = self._build_shape_mosaic_items(raw_items, area=area, area_wkt=area_wkt)[:ui_limit]
        self._current_result_mode = "shape_mosaic"

        self._search_stac_finalize(items, raw_items, collection_name, config, True, valid_tiles, bbox, start, end)
        self.progress_bar.setVisible(False)

    def _search_stac_extent_crop(self, items, raw_items, ui_limit):
        """Group items by date for extent-crop mode (merge + clip to bbox)."""
        from ..ui.result_widgets import _ShapeMosaicItem

        collection_name = self._current_collection_name()
        config = COLLECTIONS.get(collection_name, {})
        start = self.range_slider.get_start_date().toString("yyyy-MM-dd")
        end = self.range_slider.get_end_date().toString("yyyy-MM-dd")
        valid_tiles = self.get_tiles_list()
        bbox = self.get_bbox_from_extent()

        # The crop is named by its corner coordinates, so two different boxes
        # never share result ids or file names.
        if bbox:
            crop_name, crop_area = self._crop_area(bbox)
            xmin, ymin, xmax, ymax = (float(v) for v in bbox)
            crop_wkt = f"POLYGON(({xmin} {ymin},{xmax} {ymin},{xmax} {ymax},{xmin} {ymax},{xmin} {ymin}))"
        else:
            crop_name, crop_area, crop_wkt = "Crop", None, None

        mosaics = []
        for key, group_dt, group_items in group_items_by_date(raw_items):
            mosaic = _ShapeMosaicItem(
                key,
                group_dt,
                group_items,
                feature_name=crop_name,
                is_extent_crop=True,
                area=crop_area,
                area_wkt=crop_wkt,
                crop_bbox=bbox,
            )
            mosaics.append(mosaic)

        items = mosaics[:ui_limit]
        self._current_result_mode = "extent_crop"
        self._search_stac_finalize(items, raw_items, collection_name, config, False, valid_tiles, bbox, start, end)
        self.progress_bar.setVisible(False)

    def _search_stac_finalize(
        self, items, raw_items, collection_name, config, shape_search, valid_tiles, bbox, start, end
    ):
        """Finalize search: populate result widgets, filters, status."""
        collection_id = config.get("id")

        if not items:
            self._set_status(
                _no_results_message(
                    config, start, end, valid_tiles, bbox, shape_search and bool(raw_items), len(raw_items)
                ),
                "warning",
            )
            self.progress_bar.setVisible(False)
            return

        self.found_items = items
        self._current_collection_id = collection_id
        self._current_grid_type = config.get("grid", "")
        if shape_search:
            self._set_status(
                f"Listing {count_label(len(items), 'date', 'dates')} of "
                f"{count_label(len(raw_items), 'scene', 'scenes')}...",
                "info",
            )
        else:
            self._set_status(f"Listing {count_label(len(items), 'image', 'images')}...", "info")
        QCoreApplication.processEvents()

        auto_select = self.auto_select_check.isChecked()
        self.results_container.setUpdatesEnabled(False)
        for item in items:
            widget = ResultItemWidget(
                item,
                collection_id=collection_id,
                grid_type=self._current_grid_type,
                selected=auto_select,
                compact=self.compact_view,
            )
            widget._download_callback = self._download_item
            # A crop card previews the area with the bands chosen for the search.
            widget.preview_bands = self._selected_band_names() if hasattr(self, "_selected_band_names") else []
            widget.selectionChanged.connect(self._schedule_band_availability_update)
            self.result_widgets.append(widget)
            self.results_layout.insertWidget(self.results_layout.count() - 1, widget)
            apply_click_cursors(widget)
        self.results_container.setUpdatesEnabled(True)

        QTimer.singleShot(THUMBNAILS_AFTER_LAYOUT_MS, lambda: self._load_visible_thumbnails(preload_buffer=500))
        self._update_downloaded_status()

        # The filters take the new results: tiles and dates span them, and the
        # cloud and downloaded filters the user set still apply.
        self._populate_tile_checkboxes()
        self._populate_filter_range_bar()
        visible = self._apply_result_filters(refresh=True)
        # Filling the date filter queued an update of its own; this one covers it.
        timer = getattr(self, "_filter_debounce_timer", None)
        if timer is not None:
            timer.stop()

        self.load_btn.setEnabled(True)
        self.download_selected_btn.setEnabled(True)
        if visible < len(self.result_widgets):
            self._show_result_count(visible, "success")
        elif shape_search:
            self._set_status(
                f"{count_label(len(raw_items), 'scene', 'scenes')} grouped into "
                f"{count_label(len(items), 'date', 'dates')}.",
                "success",
            )
        else:
            self._set_status(f"{count_label(len(items), 'image', 'images')} found.", "success")

    # ------------------------------------------------------------------
    # Thumbnail loading
    # ------------------------------------------------------------------
    def _load_visible_thumbnails(self, preload_buffer: int = 150):
        """Load thumbnails visible in the viewport plus a preload buffer above/below."""
        try:
            viewport = self.results_scroll.viewport()
            vp_height = viewport.height()
            for widget in self.result_widgets:
                if not widget.isVisible():
                    if hasattr(widget, "cancel_thumbnail"):
                        widget.cancel_thumbnail()
                    continue
                # Widget position relative to the viewport
                wpos = widget.mapTo(viewport, QPoint(0, 0))
                w_top = wpos.y()
                w_bottom = w_top + widget.height()
                # Visible or within the preload buffer; the rest give way.
                if w_bottom >= -preload_buffer and w_top <= vp_height + preload_buffer:
                    widget.load_thumbnail_if_needed()
                elif hasattr(widget, "cancel_thumbnail"):
                    widget.cancel_thumbnail()
        except Exception:
            # Safe fallback: load the first 15
            for widget in self.result_widgets[:15]:
                widget.load_thumbnail_if_needed()

    def get_selected_items(self):
        return [w.item for w in self.result_widgets if w.isVisible() and w.is_selected()]
