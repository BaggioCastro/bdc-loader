"""
Plotting Capabilities

Provides the pure matplotlib plotting functions for standard time series line
charts and multidimensional RGB scatter plots.

Developed by Baggio Luiz de Castro e Silva
INPE - Sao Jose dos Campos, 2026
"""

import logging

import numpy as np

from ..i18n import tr

_logger = logging.getLogger("bdc_loader")

# A visually distinctive color palette for multi-band charting
BAND_COLORS = [
    "#2c3e50",
    "#e74c3c",
    "#27ae60",
    "#2980b9",
    "#8e44ad",
    "#d35400",
    "#16a085",
    "#c0392b",
    "#f39c12",
    "#7f8c8d",
]


def apply_axis_ranges(ax, chart_dock):
    """
    Applies the custom user-adjusted axis limits (zooms) to the matplotlib axes.
    """
    if not chart_dock:
        return

    y_range = chart_dock.get_effective_y_range()
    x_range = chart_dock.get_effective_x_range()

    if y_range:
        ax.set_ylim(y_range[0], y_range[1])
    if x_range:
        from matplotlib.dates import num2date

        try:
            ax.set_xlim(num2date(x_range[0]), num2date(x_range[1]))
        except Exception as _e:
            _logger.debug("Failed to set x-axis range (apply_axis_ranges): %s", _e)


# Default Y view when the bands do not declare a valid range.
_DEFAULT_VIEW_BOUNDS = (-10000.0, 10000.0)

# RGB dots: a date whose mean of the three bands exceeds this reflectance
# x 10^4 is treated as cloud when the bands are reflectance.
_CLOUD_BRIGHTNESS = 3000.0
# Smallest stretch span per band (reflectance x 10^4), so a stable target
# such as forest is not stretched into noise.
_MIN_REFLECTANCE_SPAN = 400.0
# Fraction of the stretch span added below and above it.
_STRETCH_MARGIN = 0.1


def _display_transform(hist_entry, band):
    """(a, b) mapping a stored value of ``band`` to ``a * value + b`` on the chart, or None."""
    scaling = (hist_entry.get("scaling") or {}).get(band)
    if not scaling:
        return None
    return float(scaling[0]), float(scaling[1])


def display_series(hist_entry, band):
    """[(date, value)] of ``band`` in chart units.

    Reflectance bands are drawn as reflectance x 10^4 (``hist_entry["scaling"]``),
    so Landsat Collection 2 integers and Sentinel-2 cube values share one scale
    with the indices, which are stored x 10^4. Other bands are drawn as stored.
    """
    series = hist_entry.get("data", {}).get(band, [])
    transform = _display_transform(hist_entry, band)
    if not transform:
        return list(series)
    a, b = transform
    return [(date, value * a + b) for date, value in series]


def _view_bounds(hist_entry, bands):
    """Return the (low, high) Y limits allowed for the default view of ``bands``.

    Uses the union of the valid ranges declared for those bands, in chart
    units, so values outside them (saturated or flagged pixels) do not stretch
    the axis. Falls back to +/-10000 when no band declares a range.
    """
    declared = hist_entry.get("valid_range") or {}
    ranges = []
    for band in bands:
        if band not in declared:
            continue
        low, high = declared[band]
        transform = _display_transform(hist_entry, band)
        if transform:
            a, b = transform
            low, high = sorted((low * a + b, high * a + b))
        ranges.append((low, high))
    if not ranges:
        return _DEFAULT_VIEW_BOUNDS
    return min(r[0] for r in ranges), max(r[1] for r in ranges)


def _y_label(hist_entry, bands):
    """Axis label: the unit shared by ``bands`` when all are reflectance or indices x 10^4."""
    indices = {"NDVI", "EVI"}
    if bands and all(b in indices or _display_transform(hist_entry, b) for b in bands):
        return tr("Reflectance / index (x10\u2074)")
    return tr("Value")


def auto_gamma(colors, target=0.4, dark=0.3):
    """Gamma that brightens dark dots: 1 unless the median luminance is below ``dark``.

    ``colors`` are stretched (r, g, b) in 0-1. White (cloud) and black dots
    are left out of the median. The gamma moves the median luminance toward
    ``target`` and stays between 0.5 and 1.
    """
    rgb = np.asarray(colors, dtype=float).reshape(-1, 3)
    lum = rgb @ np.array([0.299, 0.587, 0.114])
    lum = lum[(lum > 0.01) & (lum < 0.95)]
    if lum.size == 0:
        return 1.0
    median = float(np.median(lum))
    if median >= dark:
        return 1.0
    return float(np.clip(np.log(target) / np.log(median), 0.5, 1.0))


def auto_rgb_ranges(channels, pct_low=2, pct_high=98, reflectance=False, valid_bounds=None):
    """Stretch (low, high) per channel for RGB dots, from the series itself.

    ``channels`` holds three equal-length value lists (R, G, B) for the same
    dates. Cloudy dates are left out of the statistics: a date is cloudy when
    the mean of its three values is an upper outlier (above Q3 + 1.5 IQR) or,
    for reflectance, above 0.3. Each channel then takes its ``pct_low`` and
    ``pct_high`` percentiles over the clear dates, widened to a minimum span.
    Reflectance channels share one range (the widest of the three) so the
    dot keeps the surface's color; other channels keep their own. A 10 %
    margin is added on each side.
    Clouds stay in the chart and saturate to white. Values outside
    ``valid_bounds`` (per channel, chart units) are left out of the statistics.
    """
    arr = np.asarray(channels, dtype=float)
    n = arr.shape[1]
    usable = np.ones(n, dtype=bool)
    if valid_bounds:
        for i, bounds in enumerate(valid_bounds):
            if bounds:
                usable &= (arr[i] >= bounds[0]) & (arr[i] <= bounds[1])
    if usable.sum() < 2:
        usable[:] = True
    bright = arr.mean(axis=0)
    clear = usable.copy()
    if usable.sum() >= 4:
        q1, q3 = np.percentile(bright[usable], [25, 75])
        clear &= bright <= q3 + 1.5 * (q3 - q1)
    if reflectance:
        physical = clear & (bright <= _CLOUD_BRIGHTNESS)
        if physical.sum() >= max(3, 0.2 * usable.sum()):
            clear = physical
    if clear.sum() < 3:
        clear = usable
    ranges = []
    for i in range(arr.shape[0]):
        values = arr[i][clear]
        low, high = (float(v) for v in np.percentile(values, [pct_low, pct_high]))
        if reflectance:
            min_span = _MIN_REFLECTANCE_SPAN
        else:
            min_span = max(1.0, 0.05 * float(arr[i][usable].max() - arr[i][usable].min()))
        if high - low < min_span:
            middle = (high + low) / 2.0
            low, high = middle - min_span / 2.0, middle + min_span / 2.0
        ranges.append((low, high))
    if reflectance:
        # One range for the three bands keeps their ratios, so the dot shows the
        # surface's color: stretched apart, a band with a wide yearly range (red
        # over bare soil) outweighs the others and vegetation turns brown.
        shared = (min(low for low, _ in ranges), max(high for _, high in ranges))
        ranges = [shared] * len(ranges)
    # A margin on each side: with few dates the percentiles are the extremes,
    # which would turn the darkest and brightest clear dates pure black and white.
    return [(low - _STRETCH_MARGIN * (high - low), high + _STRETCH_MARGIN * (high - low)) for low, high in ranges]


def _clamp_values(values, bounds):
    low, high = bounds
    clamped = [v for v in values if low <= v <= high]
    return clamped or list(values)


# ---------------------------------------------------------------------------
# Figure helpers shared by the line and RGB charts
# ---------------------------------------------------------------------------


def _new_axes(chart_dock):
    fig = chart_dock.figure
    fig.clear()
    return fig.add_subplot(111)


def _show_message(chart_dock, ax, text, color):
    """Draw ``text`` in the middle of an empty chart."""
    ax.text(0.5, 0.5, text, transform=ax.transAxes, ha="center", va="center", fontsize=12, color=color)
    chart_dock.canvas_plot.draw_idle()


def _style_axes(ax, title, y_label, bold_labels):
    weight = "bold" if bold_labels else "normal"
    ax.set_xlabel(tr("Date"), fontsize=9, fontweight=weight)
    ax.set_ylabel(y_label, fontsize=9, fontweight=weight)
    ax.set_title(title, fontsize=10, fontweight="bold")
    ax.tick_params(axis="both", labelsize=8)
    ax.grid(True, alpha=0.15, color="#000000", linestyle="-")
    ax.set_facecolor("#f0f0f0")


def _fit_view(chart_dock, ax, dates, values, bounds):
    """Feed the range bars and set the default view, unless the user set the axes.

    The default Y view covers the values inside ``bounds`` (the bands' valid
    range) with a 10 % margin; an X range the user picked is kept.
    """
    view_values = _clamp_values(values, bounds)
    chart_dock.update_axis_ranges_from_data(dates, view_values)
    if getattr(chart_dock, "_y_user_adjusted", False):
        apply_axis_ranges(ax, chart_dock)
        return
    view_ymin, view_ymax = min(view_values), max(view_values)
    margin_y = (view_ymax - view_ymin) * 0.10 if view_ymax > view_ymin else 1
    ax.set_ylim(view_ymin - margin_y, view_ymax + margin_y)
    if getattr(chart_dock, "_x_user_adjusted", False):
        x_range = chart_dock.get_effective_x_range()
        if x_range:
            from matplotlib.dates import num2date

            try:
                ax.set_xlim(num2date(x_range[0]), num2date(x_range[1]))
            except Exception as _e:
                _logger.debug("Failed to set x-axis range: %s", _e)


def _finish(chart_dock):
    fig = chart_dock.figure
    fig.autofmt_xdate(rotation=45, ha="right")
    fig.tight_layout()
    chart_dock.canvas_plot.draw_idle()


def _point_title(hist_entry):
    return f"{hist_entry.get('label', '')} ({hist_entry.get('lon', 0.0):.4f}, {hist_entry.get('lat', 0.0):.4f})"


# ---------------------------------------------------------------------------
# Line chart
# ---------------------------------------------------------------------------


def plot_line_chart(chart_dock, hist_entry):
    """Draw every band of ``hist_entry`` the user has not hidden as a line, in chart units."""
    ax = _new_axes(chart_dock)
    bands = hist_entry.get("bands", [])
    hidden = getattr(chart_dock, "_hidden_bands", set())

    all_dates, all_values, plotted_bands = [], [], []
    for idx, band in enumerate(bands):
        series = display_series(hist_entry, band) if band not in hidden else []
        if not series:
            continue
        dates = [d for d, _v in series]
        values = [v for _d, v in series]
        all_dates.extend(dates)
        all_values.extend(values)
        color = BAND_COLORS[idx % len(BAND_COLORS)]
        ax.plot(dates, values, "o-", color=color, linewidth=1.5, markersize=4, label=band, alpha=0.85)
        plotted_bands.append(band)

    if not plotted_bands:
        ax.text(
            0.5, 0.5, "No valid data", transform=ax.transAxes, ha="center", va="center", fontsize=12, color="#95a5a6"
        )
    title = f"{hist_entry.get('collection', '')} | {_point_title(hist_entry)}"
    _style_axes(ax, title, _y_label(hist_entry, plotted_bands), bold_labels=False)
    if plotted_bands:
        if len(bands) <= 12:
            ax.legend(fontsize=7, loc="upper right", ncol=2, framealpha=0.8)
        _fit_view(chart_dock, ax, all_dates, all_values, _view_bounds(hist_entry, plotted_bands))
    _finish(chart_dock)


# ---------------------------------------------------------------------------
# RGB dots
# ---------------------------------------------------------------------------


def _rgb_selection(chart_dock):
    """(R, G, B, Y) band names picked in the chart's combos (None when empty)."""
    return tuple(
        combo.currentData()
        for combo in (chart_dock.rgb_r_combo, chart_dock.rgb_g_combo, chart_dock.rgb_b_combo, chart_dock.rgb_y_combo)
    )


def _rgb_channel_ranges(chart_dock, hist_entry, rgb_bands, channels, pct_low, pct_high, vis_min, vis_max):
    """Stretch (low, high) per channel and the Min/Max spinboxes kept in step.

    Automatic: from the series' clear dates (auto_rgb_ranges), shown in the
    spinboxes. Manual (the user edited Min/Max): one range for all three.
    """
    if getattr(chart_dock, "_rgb_user_adjusted", False):
        return [(float(vis_min), float(vis_max))] * 3
    declared = hist_entry.get("valid_range") or {}
    ranges = auto_rgb_ranges(
        channels,
        pct_low,
        pct_high,
        reflectance=all(_display_transform(hist_entry, b) for b in rgb_bands),
        valid_bounds=[_view_bounds(hist_entry, [b]) if b in declared else None for b in rgb_bands],
    )
    data_min = int(np.floor(min(lo for lo, _ in ranges)))
    data_max = int(np.ceil(max(hi for _, hi in ranges)))
    for spin, value in ((chart_dock._rgb_min_spin, data_min), (chart_dock._rgb_max_spin, max(data_max, data_min + 1))):
        spin.blockSignals(True)
        spin.setValue(value)
        spin.blockSignals(False)
    return ranges


def _scale_unit(value, vmin, vmax):
    """``value`` mapped into 0-1 by the range (vmin, vmax), clamped."""
    if vmax <= vmin:
        vmax = vmin + 1
    clamped = max(float(vmin), min(float(value), float(vmax)))
    return (clamped - vmin) / (vmax - vmin)


def _apply_gamma(chart_dock, colors):
    """``colors`` with the user's gamma, or the automatic one shown in the γ spinbox."""
    gamma_spin = getattr(chart_dock, "_rgb_gamma_spin", None)
    if getattr(chart_dock, "_rgb_gamma_user", False) is True and gamma_spin is not None:
        gamma = float(gamma_spin.value())
    else:
        gamma = auto_gamma(colors) if colors else 1.0
        if gamma_spin is not None:
            gamma_spin.blockSignals(True)
            gamma_spin.setValue(round(gamma, 2))
            gamma_spin.blockSignals(False)
    if gamma == 1.0:
        return colors
    return [(r**gamma, g**gamma, b**gamma) for r, g, b in colors]


def _draw_dots(ax, dates, y_values, colors, point_size):
    # A faint ring first, so white (cloud) dots stay visible on the grid.
    ax.scatter(
        dates,
        y_values,
        facecolors="none",
        s=point_size + 20,
        zorder=4,
        edgecolors="#00000030",
        linewidths=1.2,
        marker="o",
        clip_on=True,
    )
    ax.scatter(
        dates,
        y_values,
        facecolors=colors,
        s=point_size,
        zorder=5,
        edgecolors="none",
        linewidths=0,
        marker="o",
        clip_on=True,
    )


def plot_rgb_dots(chart_dock, hist_entry):
    """Scatter of ``hist_entry`` over time, each dot colored by its R, G, B bands.

    The Y axis is the band picked in the Y combo, or the luminance of the
    three bands when none is picked; similar to Earth Engine's rgb-timeseries.
    """
    ax = _new_axes(chart_dock)
    r_band, g_band, b_band, y_band = _rgb_selection(chart_dock)
    if not all([r_band, g_band, b_band]):
        _show_message(chart_dock, ax, "Select 3 bands for R, G, B", "#e74c3c")
        return
    rgb_bands = (r_band, g_band, b_band)
    rgb_series = [dict(display_series(hist_entry, band)) for band in rgb_bands]
    y_series = dict(display_series(hist_entry, y_band)) if y_band else {}
    use_y_band = bool(y_band and y_series)

    common = set(rgb_series[0]) & set(rgb_series[1]) & set(rgb_series[2])
    if use_y_band:
        common &= set(y_series)
    dates = sorted(common)
    if not dates:
        _show_message(chart_dock, ax, "No common dates for RGB", "#95a5a6")
        return

    vis_min, vis_max, point_size, pct_low, pct_high = chart_dock.get_rgb_params()
    channels = [[float(series[d]) for d in dates] for series in rgb_series]
    ranges = _rgb_channel_ranges(chart_dock, hist_entry, rgb_bands, channels, pct_low, pct_high, vis_min, vis_max)
    colors = [tuple(_scale_unit(channels[i][k], *ranges[i]) for i in range(3)) for k in range(len(dates))]
    colors = _apply_gamma(chart_dock, colors)
    if use_y_band:
        y_values = [y_series[d] for d in dates]
    else:
        y_values = [0.299 * channels[0][k] + 0.587 * channels[1][k] + 0.114 * channels[2][k] for k in range(len(dates))]

    _draw_dots(ax, dates, y_values, colors, point_size)
    y_label = (y_band + " (x10\u2074)" if y_band in ("NDVI", "EVI") else y_band) if use_y_band else tr("Luminance")
    title = f"{hist_entry.get('collection', '')} \u2014 RGB({r_band}/{g_band}/{b_band}) | {_point_title(hist_entry)}"
    _style_axes(ax, title, y_label, bold_labels=True)
    _fit_view(chart_dock, ax, dates, y_values, _view_bounds(hist_entry, [y_band] if use_y_band else list(rgb_bands)))
    _finish(chart_dock)
