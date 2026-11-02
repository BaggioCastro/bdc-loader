# -*- coding: utf-8 -*-
"""
TSBandManager — Band management, vegetation indices, and RGB combo logic.

Handles band resolution, computed indices (NDVI/EVI), RGB preset logic,
and additional band fetching for the time series panel.
"""

import threading

from ..extraction.band_scaling import band_entry, collection_band_info, display_scaling, to_reflectance
from ..extraction.point_series import extract_points_timeseries
from ..extraction.wtss_extractor import collection_has_wtss, extract_wtss_multi_points
from ..i18n import count_label, failure_text
from ..logger import error as _log_error
from ..ui.thumbnails import _invoke_on_ui_thread
from .ts_constants import _INDEX_DEFS, _KNOWN_COMMON_NAMES


class TSBandManager:
    """Band resolution, vegetation indices, and RGB combo management."""

    def _resolve_common_band(self, cid, common_name):
        """Resolve a common band name (e.g. 'nir') to the real band name."""
        band_info = self._band_info.get(cid, {})
        for band_name, info in band_info.items():
            if info.get("common_name", "").lower() == common_name.lower():
                return band_name
        config = None
        for _n, _c in self._collections.items():
            if _c.get("id") == cid:
                config = _c
                break
        if config:
            for band in config.get("bands", []):
                known = _KNOWN_COMMON_NAMES.get(band, "").lower()
                if known == common_name.lower():
                    return band
        return None

    def _get_available_indices(self, cid, bands):
        """Return computable index keys for a collection (skip if already a real band)."""
        indices = []
        bands_lower = {b.lower() for b in bands}
        for idx_key, idx_def in _INDEX_DEFS.items():
            if idx_def["output"].lower() in bands_lower:
                continue
            if all(self._resolve_common_band(cid, cn) for cn in idx_def["requires"]):
                indices.append(idx_key)
        return indices

    def _compute_vegetation_indices(self, cid, point_data, requested_indices, band_info=None):
        """Compute NDVI/EVI from extracted band data and add to point_data.

        Bands are converted to reflectance with the scale and offset in
        ``band_info`` (see band_scaling) first: Landsat Collection 2 stores
        ``(reflectance + 0.2) / 2.75e-05``, and an index of those integers is
        not the index of the surface.
        """

        def _reflectance(band):
            return to_reflectance(point_data[band], band_entry(band_info, band))

        for idx_key in requested_indices:
            idx_def = _INDEX_DEFS.get(idx_key)
            if not idx_def:
                continue
            real_bands = {}
            for cn in idx_def["requires"]:
                rb = self._resolve_common_band(cid, cn)
                if not rb or rb not in point_data:
                    break
                real_bands[cn] = rb
            else:
                output = idx_def["output"]
                if idx_key == "_NDVI":
                    point_data[output] = self._calc_ndvi(
                        _reflectance(real_bands["nir"]),
                        _reflectance(real_bands["red"]),
                    )
                elif idx_key == "_EVI":
                    point_data[output] = self._calc_evi(
                        _reflectance(real_bands["nir"]),
                        _reflectance(real_bands["red"]),
                        _reflectance(real_bands["blue"]),
                    )

    @staticmethod
    def _calc_ndvi(nir_series, red_series):
        """NDVI = (NIR - RED) / (NIR + RED), scaled to 10000.

        A date whose NIR + RED is not positive has no NDVI (Landsat reflectance
        can be slightly negative over water and shadow); a value pushed past
        +/-1 by one negative band is clipped to the valid range.
        """
        red_by_date = {d: v for d, v in red_series}
        result = []
        for dt, nir_v in nir_series:
            red_v = red_by_date.get(dt)
            if red_v is not None:
                denom = nir_v + red_v
                if denom > 0:
                    ndvi = max(-1.0, min(1.0, (nir_v - red_v) / denom))
                    result.append((dt, ndvi * 10000.0))
        return result

    @staticmethod
    def _calc_evi(nir_series, red_series, blue_series):
        """EVI = 2.5*(NIR-RED)/(NIR + 6*RED - 7.5*BLUE + L). Auto-detects scale."""
        red_by_date = {d: v for d, v in red_series}
        blue_by_date = {d: v for d, v in blue_series}
        nir_vals = [v for _, v in nir_series]
        if nir_vals:
            median_nir = sorted(nir_vals)[len(nir_vals) // 2]
            L = 10000.0 if median_nir > 1.0 else 1.0
        else:
            L = 1.0
        result = []
        for dt, nir_v in nir_series:
            red_v = red_by_date.get(dt)
            blue_v = blue_by_date.get(dt)
            if red_v is not None and blue_v is not None:
                denom = nir_v + 6.0 * red_v - 7.5 * blue_v + L
                if denom != 0:
                    evi = 2.5 * (nir_v - red_v) / denom
                    evi = max(-1.0, min(1.0, evi))
                    result.append((dt, evi * 10000.0))
        return result

    def _get_selected_bands(self):
        return [cb.property("band_name") for cb in self._band_checkboxes if cb.isChecked()]

    def _set_all_bands(self, checked):
        for cb in self._band_checkboxes:
            if cb.isVisible():
                cb.setChecked(checked)

    def _filter_bands(self, text):
        """Filter band checkboxes by name."""
        text = text.lower()
        for cb in self._band_checkboxes:
            cb.setVisible(text in cb.text().lower() if text else True)

    def _update_rgb_combos(self, bands, cid=None):
        """Populate RGB/Y combos with ALL collection bands."""
        if not self.chart_dock:
            return

        if not cid:
            cid = self.ts_collection_combo.currentData()
        all_bands = []
        if cid:
            for _name, _cfg in self._collections.items():
                if _cfg.get("id") == cid:
                    all_bands = list(_cfg.get("bands", []))
                    break
        if not all_bands:
            all_bands = list(bands)

        for idx_name in ("NDVI", "EVI"):
            if idx_name not in all_bands and idx_name in set(bands):
                all_bands.append(idx_name)
        all_bands.sort(key=lambda value: str(value).casefold())

        extracted_set = set(bands)

        prev_r = self.chart_dock.rgb_r_combo.currentData()
        prev_g = self.chart_dock.rgb_g_combo.currentData()
        prev_b = self.chart_dock.rgb_b_combo.currentData()
        prev_y = self.chart_dock.rgb_y_combo.currentData()
        self.chart_dock.rgb_r_combo.blockSignals(True)
        self.chart_dock.rgb_g_combo.blockSignals(True)
        self.chart_dock.rgb_b_combo.blockSignals(True)
        self.chart_dock.rgb_y_combo.blockSignals(True)
        self.chart_dock.rgb_r_combo.clear()
        self.chart_dock.rgb_g_combo.clear()
        self.chart_dock.rgb_b_combo.clear()
        self.chart_dock.rgb_y_combo.clear()
        for band in all_bands:
            label = band if band in extracted_set else f"{band} \u2193"
            self.chart_dock.rgb_r_combo.addItem(label, band)
            self.chart_dock.rgb_g_combo.addItem(label, band)
            self.chart_dock.rgb_b_combo.addItem(label, band)
            self.chart_dock.rgb_y_combo.addItem(label, band)
        restored = False
        if prev_r and prev_g and prev_b:
            ri = self.chart_dock.rgb_r_combo.findData(prev_r)
            gi = self.chart_dock.rgb_g_combo.findData(prev_g)
            bi = self.chart_dock.rgb_b_combo.findData(prev_b)
            if ri >= 0 and gi >= 0 and bi >= 0:
                self.chart_dock.rgb_r_combo.setCurrentIndex(ri)
                self.chart_dock.rgb_g_combo.setCurrentIndex(gi)
                self.chart_dock.rgb_b_combo.setCurrentIndex(bi)
                restored = True
        if not restored:
            self._try_preset_rgb(cid, all_bands)
        if prev_y:
            yi = self.chart_dock.rgb_y_combo.findData(prev_y)
            if yi >= 0:
                self.chart_dock.rgb_y_combo.setCurrentIndex(yi)
        else:
            ndvi_idx = self.chart_dock.rgb_y_combo.findData("NDVI")
            if ndvi_idx >= 0:
                self.chart_dock.rgb_y_combo.setCurrentIndex(ndvi_idx)
        self.chart_dock.rgb_r_combo.blockSignals(False)
        self.chart_dock.rgb_g_combo.blockSignals(False)
        self.chart_dock.rgb_b_combo.blockSignals(False)
        self.chart_dock.rgb_y_combo.blockSignals(False)

        if hasattr(self.chart_dock, "refresh_line_bands"):
            self.chart_dock.refresh_line_bands(list(bands))

    @staticmethod
    def _get_rgb_for_collection(cid, bands=None):
        """Return (R, G, B) band tuple for a collection, or None."""
        rgb_map = {
            "S2-16D-2": ("B04", "B03", "B02"),
            "S2_L2A-1": ("B04", "B03", "B02"),
            "LANDSAT-16D-1": ("red", "green", "blue"),
            "landsat-2": ("red", "green", "blue"),
            "CBERS4-WFI-16D-2": ("BAND15", "BAND14", "BAND13"),
            "CBERS-WFI-8D-1": ("BAND15", "BAND14", "BAND13"),
            "CBERS4-MUX-2M-1": ("BAND7", "BAND6", "BAND5"),
            "AMZ1-WFI-L4-SR-1": ("BAND3", "BAND2", "BAND1"),
            "mod13q1-6.1": ("NIR_reflectance", "red_reflectance", "blue_reflectance"),
        }
        preset = rgb_map.get(cid)
        if preset:
            return preset
        try:
            from ..stac.fallback import FALLBACK_BAND_INFO as BAND_INFO

            info = BAND_INFO.get(cid, {})
            if info:
                by_common = {}
                for band_name, meta in info.items():
                    cn = meta.get("common_name", "").lower()
                    if cn:
                        by_common.setdefault(cn, band_name)
                r = by_common.get("red")
                g = by_common.get("green")
                b = by_common.get("blue")
                if r and g and b:
                    return (r, g, b)
        except Exception as exc:
            _log_error(f"RGB detection failed for {cid}: {exc}")
        if bands:
            bands_lower = {b.lower(): b for b in bands}
            r = bands_lower.get("red")
            g = bands_lower.get("green")
            b = bands_lower.get("blue")
            if r and g and b:
                return (r, g, b)
        return None

    def _try_preset_rgb(self, cid, bands):
        if not self.chart_dock:
            return
        preset = self._get_rgb_for_collection(cid, bands)
        if preset:
            r, g, b = preset
            ri = self.chart_dock.rgb_r_combo.findData(r)
            gi = self.chart_dock.rgb_g_combo.findData(g)
            bi = self.chart_dock.rgb_b_combo.findData(b)
            if ri >= 0:
                self.chart_dock.rgb_r_combo.setCurrentIndex(ri)
            if gi >= 0:
                self.chart_dock.rgb_g_combo.setCurrentIndex(gi)
            if bi >= 0:
                self.chart_dock.rgb_b_combo.setCurrentIndex(bi)

    def _on_rgb_combo_changed(self):
        """Called when any RGB/Y combo changes — fetches missing bands if needed."""
        if self._current_viz_index < 0 or self._current_viz_index >= len(self._history):
            self._replot_current()
            return
        if not self.chart_dock:
            return
        entry = self._history[self._current_viz_index]
        requested = set()
        for combo in (
            self.chart_dock.rgb_r_combo,
            self.chart_dock.rgb_g_combo,
            self.chart_dock.rgb_b_combo,
            self.chart_dock.rgb_y_combo,
        ):
            b = combo.currentData()
            if b:
                requested.add(b)
        missing = [b for b in requested if b not in entry.get("data", {})]
        if missing:
            self._fetch_additional_bands(entry, missing)
        else:
            self._replot_current()

    def _fetch_additional_bands(self, entry, bands):
        """Fetch extra bands in the background, keeping only the latest pending request."""
        bands = list(dict.fromkeys(bands))
        if not bands:
            self._replot_current()
            return

        if self._rgb_bands_downloading:
            active = getattr(self, "_rgb_fetch_active", None)
            if active and active[0] is entry:
                bands = [band for band in bands if band not in active[1]]
                if not bands:
                    return
            pending = getattr(self, "_rgb_fetch_pending", None)
            if pending and pending[0] is entry:
                bands = list(dict.fromkeys([*pending[1], *bands]))
            self._rgb_fetch_pending = (entry, bands)
            return

        self._rgb_bands_downloading = True
        self._rgb_fetch_active = (entry, set(bands))
        self._rgb_fetch_pending = None
        if self.chart_dock:
            self.chart_dock.show_loading_overlay("Extracting RGB bands...")

        cid = entry["collection"]
        lon, lat = entry["lon"], entry["lat"]
        start, end = entry["start"], entry["end"]
        use_wtss = collection_has_wtss(cid)
        backend = "WTSS" if use_wtss else "STAC"
        self._set_status(
            f"Extracting {count_label(len(bands), 'band', 'bands')} of the time series ({backend}): {', '.join(bands)}",
            "loading",
            0,
        )

        def _cog_series(wanted):
            """Series of ``wanted`` read from the COGs of the point's items, grouped by file."""
            point = (lon, lat)
            items = self._point_items(cid, point, start, end)
            if not items:
                return {}, True
            series, _failed = extract_points_timeseries(
                [items], [point], wanted, cancel_flag=self._cancel_extraction.is_set
            )
            return series.get(0, {}), False

        def _run():
            no_items = False
            error = None
            scaling = {}
            try:
                if use_wtss:
                    wtss_pts = [(lon, lat, entry.get("label", "P1"), bands)]
                    result = extract_wtss_multi_points(
                        cid,
                        wtss_pts,
                        start,
                        end,
                        cancel_flag=self._cancel_extraction.is_set,
                    )
                    point_data = result.get(0, {})
                    wtss_missing = [band for band in bands if band not in point_data]
                    if wtss_missing and not self._cancel_extraction.is_set():
                        point_data.update(_cog_series(wtss_missing)[0])
                else:
                    point_data, no_items = _cog_series(bands)
                band_info = collection_band_info(cid)
                for band in point_data:
                    band_scaling = display_scaling(band_entry(band_info, band))
                    if band_scaling:
                        scaling[band] = band_scaling
            except Exception as exc:
                point_data = {}
                error = exc

            _invoke_on_ui_thread(
                lambda: self._finish_additional_band_fetch(entry, bands, point_data, no_items, error, scaling)
            )

        threading.Thread(target=_run, daemon=True, name="bdc-rgb-bands").start()

    def _finish_additional_band_fetch(self, entry, bands, point_data, no_items, error, scaling=None):
        """Apply fetched data on the UI thread, then execute the latest queued request."""
        if getattr(self, "_ts_closing", False):
            self._rgb_bands_downloading = False
            self._rgb_fetch_active = None
            self._rgb_fetch_pending = None
            return
        if error is not None:
            self._set_status(failure_text("Time series extraction", str(error)[:80]), "error", 0)
            _log_error(f"Error downloading bands: {error}")
        elif no_items:
            self._set_status(f"No images found for {', '.join(bands)} at this point.", "warning")
        else:
            fetched = [band for band in bands if band in point_data]
            not_found = [band for band in bands if band not in point_data]
            for band, values in point_data.items():
                entry["data"][band] = values
                if band not in entry["bands"]:
                    entry["bands"].append(band)
            if scaling:
                entry.setdefault("scaling", {}).update(scaling)

            parts = []
            if fetched:
                parts.append(f"{count_label(len(fetched), 'band', 'bands')} extracted")
            if not_found:
                parts.append(f"{count_label(len(not_found), 'band', 'bands')} without data: {', '.join(not_found)}")
            self._set_status(", ".join(parts) + "." if parts else "Time series extraction complete.", "success")
            self._update_rgb_combos(entry["bands"], entry.get("collection", ""))

        pending = getattr(self, "_rgb_fetch_pending", None)
        self._rgb_fetch_active = None
        self._rgb_fetch_pending = None
        if pending:
            self._rgb_bands_downloading = False
            pending_entry, pending_bands = pending
            self._fetch_additional_bands(pending_entry, pending_bands)
            return

        # Keep the guard active during this replot so an unavailable band does
        # not immediately start the same request again.
        try:
            self._replot_current()
        finally:
            self._rgb_bands_downloading = False
            if self.chart_dock:
                self.chart_dock.hide_loading_overlay()
