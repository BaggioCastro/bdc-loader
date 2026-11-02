"""RGB dot stretch, chart units and range bar alignment of the time series chart."""

from datetime import datetime, timedelta

import pytest


def test_clouds_do_not_darken_the_clear_dates():
    from bdc_loader_plugin.chart.plot import auto_rgb_ranges

    # 20 clear dates around reflectance 0.10-0.14 and 5 clouds near 0.6
    clear = [1000.0 + 20 * i for i in range(20)]
    clouds = [6000.0, 6200.0, 5800.0, 6100.0, 5900.0]
    channels = [clear + clouds] * 3
    ranges = auto_rgb_ranges(channels, 2, 98, reflectance=True)
    for low, high in ranges:
        assert 900 <= low <= 1000 and 1380 <= high <= 1500  # the clouds are not in the stretch


def test_cloudy_majority_uses_the_reflectance_threshold():
    from bdc_loader_plugin.chart.plot import auto_rgb_ranges

    clear = [800.0, 900.0, 1000.0, 1100.0]
    clouds = [5000.0 + 100 * i for i in range(8)]  # most dates cloudy: IQR alone keeps them
    ranges = auto_rgb_ranges([clear + clouds] * 3, 2, 98, reflectance=True)
    assert all(high <= 1600 for _low, high in ranges)


def test_stable_target_gets_a_minimum_span():
    from bdc_loader_plugin.chart.plot import _MIN_REFLECTANCE_SPAN, _STRETCH_MARGIN, auto_rgb_ranges

    channels = [[500.0, 502.0, 501.0, 503.0, 500.0]] * 3
    for low, high in auto_rgb_ranges(channels, 2, 98, reflectance=True):
        assert high - low == pytest.approx(_MIN_REFLECTANCE_SPAN * (1 + 2 * _STRETCH_MARGIN))


def test_percentiles_follow_the_spinboxes():
    from bdc_loader_plugin.chart.plot import auto_rgb_ranges

    values = [float(v) for v in range(0, 2000, 20)]
    narrow = auto_rgb_ranges([values] * 3, 10, 90, reflectance=True)[0]
    wide = auto_rgb_ranges([values] * 3, 0, 100, reflectance=True)[0]
    assert wide[0] < narrow[0] and wide[1] > narrow[1]


def test_landsat_values_are_drawn_as_reflectance():
    from bdc_loader_plugin.chart.plot import _view_bounds, display_series
    from bdc_loader_plugin.extraction.band_scaling import display_scaling

    scaling = display_scaling({"scale": 2.75e-05, "offset": -0.2})
    day = datetime(2024, 1, 1)
    entry = {"data": {"red": [(day, 11719.0)]}, "scaling": {"red": scaling}, "valid_range": {"red": (7273.0, 43636.0)}}
    assert display_series(entry, "red")[0][1] == pytest.approx(1222.7, abs=0.1)  # 0.1223 reflectance
    low, high = _view_bounds(entry, ["red"])
    assert low == pytest.approx(0.0, abs=0.1) and high == pytest.approx(10000.0, abs=0.1)


@pytest.mark.parametrize(
    "entry, expected",
    [
        ({"scale": 0.0001}, (1.0, 0.0)),  # Sentinel-2 / CBERS / MODIS cubes: unchanged
        ({"scale": 0.02}, None),  # land surface temperature
        ({"scale": 0.001}, None),  # aerosol optical thickness
        ({"scale": 0.00341802, "offset": 149.0}, None),  # Landsat thermal
        ({"scale": None}, None),
        (None, None),
    ],
)
def test_display_scaling_only_for_reflectance(entry, expected):
    from bdc_loader_plugin.extraction.band_scaling import display_scaling

    result = display_scaling(entry)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


def test_entries_without_scaling_are_drawn_as_stored():
    from bdc_loader_plugin.chart.plot import display_series

    day = datetime(2024, 1, 1) + timedelta(days=1)
    entry = {"data": {"B04": [(day, 812.0)]}}
    assert display_series(entry, "B04") == [(day, 812.0)]


def test_range_bar_track_follows_the_given_span():
    from bdc_loader_plugin.widgets.range_bar import AxisRangeBar

    bar = AxisRangeBar.__new__(AxisRangeBar)
    bar._orientation = "horizontal"
    bar._handle_size = 10
    bar._track_span = None
    bar.width = lambda: 1000
    bar.update = lambda: None
    assert bar._track_ends() == (10, 990)
    bar.set_track_span(105, 900)
    assert bar._track_ends() == (105, 900)
    assert bar._frac_to_pos(0.0) == 105 and bar._frac_to_pos(1.0) == 900
    assert bar._pos_to_frac(502.5) == pytest.approx(0.5)
    bar.set_track_span(None, None)
    assert bar._track_ends() == (10, 990)


def test_auto_gamma_brightens_only_dark_series():
    from bdc_loader_plugin.chart.plot import auto_gamma

    assert auto_gamma([(0.5, 0.5, 0.5)] * 5) == 1.0
    dark = [(0.12, 0.15, 0.10)] * 5 + [(1.0, 1.0, 1.0)] * 3  # clouds left out of the median
    gamma = auto_gamma(dark)
    assert 0.5 <= gamma < 1.0
    lum = 0.299 * 0.12**gamma + 0.587 * 0.15**gamma + 0.114 * 0.10**gamma
    assert lum > 0.3
    assert auto_gamma([(0.005, 0.005, 0.005)] * 4) == 1.0  # only black dots: nothing to judge by


def test_reflectance_bands_share_one_range_so_vegetation_stays_green():
    from bdc_loader_plugin.chart.plot import auto_rgb_ranges

    # AMAZONIA-1 SR in Mato Grosso: dense crop (green above red, blue near 0)
    # most of the year, bare soil with red up to 0.30 for a few dates.
    red = [300.0] * 20 + [1500.0, 2200.0, 3000.0]
    green = [600.0] * 20 + [1600.0, 2300.0, 3000.0]
    blue = [50.0] * 20 + [800.0, 1500.0, 2000.0]
    ranges = auto_rgb_ranges([red, green, blue], 2, 98, reflectance=True)
    assert ranges[0] == ranges[1] == ranges[2]
    low, high = ranges[0]
    r = (300.0 - low) / (high - low)
    g = (600.0 - low) / (high - low)
    assert g > r  # the crop is drawn greener than it is red


def test_digital_numbers_keep_one_range_per_band():
    from bdc_loader_plugin.chart.plot import auto_rgb_ranges

    channels = [
        [float(v) for v in range(100, 200)],
        [float(v) for v in range(1000, 2000, 10)],
        [5.0 + i for i in range(100)],
    ]
    ranges = auto_rgb_ranges(channels, 2, 98, reflectance=False)
    assert len({r for r in ranges}) == 3
