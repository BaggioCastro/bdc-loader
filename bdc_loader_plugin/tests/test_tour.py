"""Guided tour: where the callout goes, and what the steps point at."""

import unittest

from bdc_loader_plugin.ui.tour import _GAP, callout_position

SCREEN = (0, 0, 1600, 1000)
CALLOUT = (360, 200)


def _overlaps(a, b):
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


class TestCalloutPosition(unittest.TestCase):
    def _place(self, target):
        x, y = callout_position(target, CALLOUT, SCREEN)
        box = (x, y) + CALLOUT
        self.assertTrue(0 <= x and 0 <= y and x + CALLOUT[0] <= 1600 and y + CALLOUT[1] <= 1000, box)
        return box

    def test_goes_right_of_a_widget_with_room(self):
        box = self._place((100, 100, 300, 30))
        self.assertEqual(box[:2], (100 + 300 + _GAP, 100))

    def test_goes_left_of_a_widget_at_the_right_edge(self):
        box = self._place((1300, 100, 250, 30))
        self.assertEqual(box[:2], (1300 - _GAP - 360, 100))

    def test_slides_up_near_the_bottom_without_covering_the_widget(self):
        target = (500, 950, 270, 40)
        box = self._place(target)
        self.assertFalse(_overlaps(box, target))
        self.assertEqual(box[1], 1000 - 200)

    def test_a_wide_widget_gets_the_callout_below_or_above(self):
        target = (0, 100, 1500, 400)
        box = self._place(target)
        self.assertFalse(_overlaps(box, target))
        self.assertEqual(box[1], 100 + 400 + _GAP)

    def test_keeps_clear_of_the_other_unshaded_widgets_when_a_side_allows(self):
        target, chart = (100, 100, 40, 30), (100 + 40 + _GAP, 0, 900, 130)
        box = (*callout_position(target, CALLOUT, SCREEN, avoid=[chart]), *CALLOUT)
        self.assertFalse(_overlaps(box, chart) or _overlaps(box, target), box)
        everywhere = (0, 0, 1600, 1000)
        box = (*callout_position(target, CALLOUT, SCREEN, avoid=[everywhere]), *CALLOUT)
        self.assertEqual(box[:2], (100 + 40 + _GAP, 100), "with no clear side, the first side with room")

    def test_a_widget_filling_the_screen_gets_the_callout_in_its_lower_right_corner(self):
        box = self._place((0, 0, 1600, 1000))
        self.assertEqual(box[:2], (1600 - 360 - _GAP, 1000 - 200 - _GAP))


class TestTourSteps(unittest.TestCase):
    def setUp(self):
        from unittest.mock import MagicMock

        from bdc_loader_plugin.ui import tour_steps

        self.ts = tour_steps
        self.steps = tour_steps.main_tour_steps(MagicMock(), MagicMock())

    def test_every_text_is_short_and_the_welcome_points_at_nothing(self):
        self.assertGreaterEqual(len(self.steps), 12)
        texts = [self.ts.GRID_OFFER_TEXT, self.ts.GRID_READY_TEXT]
        for step in self.steps:
            self.assertTrue(step.title and step.text())
            self.assertLessEqual(len(step.title), 32, step.title)
            texts += [step.text(), step.map_body]
        for text in texts:
            self.assertLessEqual(len(text), 140, text)
        self.assertIsNone(self.steps[0].target, "the welcome step points at nothing")

    def test_steps_that_ask_for_an_action_wait_for_it(self):
        waiting = [step.title for step in self.steps if step.done is not None]
        for title in (
            "Select the data cube",
            "Draw the area of interest",
            "Search images clipped to the box",
            "Load all dates",
            "Navigate the timeline",
            "Choose a band composition",
            "Load the new composition",
            "Clip to a polygon",
            "Search within the polygon",
            "Load the clipped image",
            "Select a tile on the map",
            "Search the whole tile",
            "Load the tile",
        ):
            self.assertIn(title, waiting)
        self.assertGreaterEqual(len(waiting), 20)
        on_map = {step.title for step in self.steps if step.map_body}
        self.assertEqual(on_map, {"Draw the area of interest", "Select a tile on the map"})
        self.assertTrue(all(step.section for step in self.steps), "every step names its part of the tour")

    def test_the_example_circle_is_small_and_holds_the_three_points(self):
        import json
        import os

        self.assertLess(os.path.getsize(self.ts.CIRCLE_PATH), 4096)
        with open(self.ts.CIRCLE_PATH) as f:
            ring = json.load(f)["features"][0]["geometry"]["coordinates"][0]

        def inside(lon, lat):
            hits = False
            for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
                if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
                    hits = not hits
            return hits

        for label, lon, lat in self.ts.EXAMPLE_POINTS:
            self.assertTrue(inside(lon, lat), label)

    def test_example_points_lie_in_the_example_area_and_tile_period(self):
        west, south, east, north = self.ts.EXAMPLE_AREA
        for label, lon, lat in self.ts.EXAMPLE_POINTS:
            self.assertTrue(west <= lon <= east and south <= lat <= north, label)
        start, end = self.ts.EXAMPLE_SEARCH_PERIOD
        scene = self.ts.EXAMPLE_SCENE_DATE
        self.assertTrue(start <= (int(scene[:4]), int(scene[4:6]), int(scene[6:])) <= end)


class TestTourChecks(unittest.TestCase):
    """What each step accepts as the action done, and the hint it gives otherwise."""

    def setUp(self):
        from unittest.mock import MagicMock

        from bdc_loader_plugin.ui import tour_steps

        self.ts = tour_steps
        self.dialog = MagicMock()
        self.dialog.isVisible.return_value = True
        self.panel = self.dialog._ts_panel
        self.panel._history = []
        self.panel._current_points = []
        self.panel.history_entries.side_effect = lambda: list(self.panel._history)
        self.panel.picked_points.side_effect = lambda: list(self.panel._current_points)

    def _offset(self, point, metres_east):
        label, lon, lat = point
        import math

        return lon + metres_east / (111320 * math.cos(math.radians(lat))), lat

    def test_a_click_counts_within_the_circle_only(self):
        point = self.ts.EXAMPLE_POINTS[0]
        self.assertTrue(self.ts._near(*self._offset(point, 200), point))
        self.assertFalse(self.ts._near(*self._offset(point, 300), point))

    def test_the_example_tile_alone_is_accepted(self):
        tile = self.ts.EXAMPLE_TILE
        for text, expected in (
            ("", False),
            (tile, True),
            ("030020", "That is tile 030020"),
            (f"{tile}, 030020", "Leave only"),
        ):
            self.dialog.tiles_input.text.return_value = text
            result = self.ts._chose_example_tile(self.dialog)
            if isinstance(expected, str):
                self.assertTrue(isinstance(result, str) and result.startswith(expected), result)
            else:
                self.assertIs(result, expected)

    def test_a_tile_does_not_count_while_the_plugin_is_away(self):
        self.dialog.tiles_input.text.return_value = self.ts.EXAMPLE_TILE
        self.dialog.isVisible.return_value = False
        self.assertIs(self.ts._chose_example_tile(self.dialog), False)

    def test_the_ndvi_point_must_be_in_the_circle(self):
        ctx = {"history": 0}
        self.assertIs(self.ts._ndvi_ready(self.dialog, ctx), False)
        lon, lat = self.ts.EXAMPLE_POINTS[2][1:]
        self.panel._history.append({"lon": lon, "lat": lat, "data": {"NDVI": []}})
        self.assertIn("outside", self.ts._ndvi_ready(self.dialog, ctx))
        lon, lat = self._offset(self.ts.EXAMPLE_POINTS[0], 100)
        self.panel._history.append({"lon": lon, "lat": lat, "data": {"NDVI": []}})
        self.assertIs(self.ts._ndvi_ready(self.dialog, ctx), True)

    def test_multi_points_need_multi_mode_one_point_per_circle_and_nothing_else(self):
        self.panel.multi_point_btn.isChecked.return_value = True
        points = [(lon, lat, f"P{i + 1}") for i, (_label, lon, lat) in enumerate(self.ts.EXAMPLE_POINTS)]
        self.panel._current_points = points[:2]
        self.assertIs(self.ts._points_placed(self.dialog), False)
        self.panel._current_points = points
        self.assertIs(self.ts._points_placed(self.dialog), True)
        self.panel._current_points = points + [(-46.0, -13.0, "P4")]
        self.assertTrue(self.ts._points_placed(self.dialog).startswith("P4 is outside"))
        self.panel._current_points = points
        self.panel.multi_point_btn.isChecked.return_value = False
        self.assertIs(self.ts._points_placed(self.dialog), False)

    def _card(self, item_id, kind):
        from unittest.mock import MagicMock

        card = MagicMock()
        card.item.id = item_id
        card.item.properties = {
            "crop": {"bdc:is_extent_crop": True, "bdc:is_shape_mosaic": True, "bdc:feature_name": "Crop 45.27W"},
            "circle": {"bdc:is_shape_mosaic": True, "bdc:feature_name": self.ts.CIRCLE_NAME},
            "tile": {},
        }[kind]
        return card

    def test_the_loaded_image_is_found_under_both_layer_naming_styles(self):
        kind = self.ts._names_kind
        self.assertEqual(kind("S2-16D_V2_031020_20220914_B04-B03-B02"), "tile")  # STAC item ID
        self.assertEqual(kind("S2-16D-2_031020_2022-09-14_B04-B03-B02"), "tile")  # Compact
        self.assertEqual(kind("S2-16D-2_crop_20220914_B04-B03-B02 crop-45.27W-13.86S"), "crop")
        self.assertEqual(kind("S2-16D-2_Tutorial-circle_20220914_B08-B04-B03"), "circle")
        self.assertIsNone(kind("S2-16D-2_030020_2022-09-14_B04-B03-B02"))
        self.assertTrue(self.ts._is_example_day("S2-16D-2_031020_2022-09-14"))
        self.assertFalse(self.ts._is_example_day("S2-16D-2_031020_2022-09-30"))

    def test_searches_count_once_the_right_cards_are_listed(self):
        crop_card = self._card("crop-45.27W-13.86S-45.08W-13.75S_2022-09-14", "crop")
        circle_card = self._card("Tutorial-circle-Tutorial-circle_2022-09-14", "circle")
        tile_card = self._card("S2-16D_V2_031020_20220914", "tile")
        self.dialog._search_in_progress = False
        self.dialog.result_widgets = []
        self.assertIs(self.ts._searched(self.dialog, "crop"), False)
        self.dialog.result_widgets = [tile_card]
        self.assertIn("Pick Crop", self.ts._searched(self.dialog, "crop"))
        self.dialog.result_widgets = [crop_card]
        self.assertIs(self.ts._searched(self.dialog, "crop"), True)
        self.assertIs(self.ts._searched(self.dialog, "circle"), False, "crop cards wait for the circle search")
        self.dialog.result_widgets = [circle_card]
        self.assertIs(self.ts._searched(self.dialog, "circle"), True)
        self.assertIs(self.ts._searched(self.dialog, "tile"), False, "circle cards wait for the tile search")
        self.dialog.result_widgets = [tile_card]
        self.assertIs(self.ts._searched(self.dialog, "tile"), True)
        self.dialog._search_in_progress = True
        self.assertIs(self.ts._searched(self.dialog, "tile"), False)

    def test_every_date_must_be_loaded(self):
        from unittest.mock import patch

        self.dialog.result_widgets = [self._card(f"crop-a_2022-0{m}-14", "crop") for m in (7, 8, 9)]
        for layers, expected in (([], False), ([1], "1 of 3 dates"), ([1, 2, 3], True)):
            with patch.object(self.ts, "_example_layers", return_value=layers):
                result = self.ts._loaded_all_dates(self.dialog)
            if isinstance(expected, str):
                self.assertTrue(result.startswith(expected), result)
            else:
                self.assertIs(result, expected)

    def test_false_color_is_the_composition_asked_for(self):
        combo = self.dialog.preset_combo
        for index, text, expected in (
            (4, "True Color (4,3,2)", False),
            (0, "-- Select --", False),
            (3, "SWIR (12,8A,4)", "That is SWIR"),
            (2, "False Color (8,4,3)", True),
        ):
            combo.currentIndex.return_value, combo.currentText.return_value = index, text
            result = self.ts._chose_false_color(self.dialog)
            if isinstance(expected, str):
                self.assertTrue(result.startswith(expected), result)
            else:
                self.assertIs(result, expected)

    def test_a_wrong_tile_points_at_the_clear_button(self):
        for text, target in (("", "select"), (self.ts.EXAMPLE_TILE, "select"), ("030020", "clear")):
            self.dialog.tiles_input.text.return_value = text
            expected = self.dialog.clear_tiles_btn if target == "clear" else self.dialog.select_tiles_btn
            self.assertIs(self.ts._tile_target(self.dialog), expected, text)

    def test_the_grid_offer_opens_once_when_extent_opens_on_a_project_with_layers(self):
        from unittest.mock import patch

        self.dialog.extent_box.isCollapsed.return_value = False
        with patch.object(self.ts, "_grid_layer", return_value=None), patch.object(self.ts, "QTimer") as timer:
            ctx = {"empty_map": True}
            self.ts._offer_grid_on_open(self.dialog, ctx)
            timer.singleShot.assert_not_called()  # the plugin offers it on an empty map
            ctx = {"empty_map": False}
            self.ts._offer_grid_on_open(self.dialog, ctx)
            self.ts._offer_grid_on_open(self.dialog, ctx)
            timer.singleShot.assert_called_once_with(50, self.dialog._offer_reference_grid)
        with patch.object(self.ts, "_grid_layer", return_value=object()), patch.object(self.ts, "QTimer") as timer:
            self.ts._offer_grid_on_open(self.dialog, {"empty_map": False})
            timer.singleShot.assert_not_called()  # the grid is already there


class TestDateImageStep(unittest.TestCase):
    def test_a_new_double_click_that_shows_the_tile_image_counts(self):
        from unittest.mock import MagicMock, patch

        from bdc_loader_plugin.ui import tour_steps as ts

        dialog = MagicMock()
        dialog._ts_panel._chart_vrt_running = False
        old_halo = object()
        dialog._ts_panel.chart_dock._click_highlight = old_halo
        ctx = {}
        ts._prepare_date_click(dialog, ctx)
        layer = MagicMock()
        layer.name.return_value = f"S2-16D-2_{ts.EXAMPLE_TILE}_2022-08-29_B04-B03-B02"
        dialog.iface.activeLayer.return_value = layer
        with patch.object(ts, "QgsRasterLayer", MagicMock), patch.object(ts, "layer_key", return_value=""):
            self.assertFalse(ts._date_image_shown(dialog, ctx), "the halo of an earlier click does not count")
            dialog._ts_panel.chart_dock._click_highlight = object()
            dialog._ts_panel._chart_vrt_running = True
            self.assertFalse(ts._date_image_shown(dialog, ctx), "the image is still being built")
            dialog._ts_panel._chart_vrt_running = False
            self.assertTrue(ts._date_image_shown(dialog, ctx))


class TestPublicSurfaceForTheTour(unittest.TestCase):
    """The tutorial drives the timeline and the panel through these methods."""

    def test_timeline_shows_a_group_and_reports_its_position(self):
        from unittest.mock import MagicMock

        from bdc_loader_plugin.widgets.timeline_slider import VRTTimelineSlider

        timeline = VRTTimelineSlider.__new__(VRTTimelineSlider)
        timeline._groups = {("S2", "crop", "B04"): [1, 2, 3], ("S2", "031020", "B04"): [1]}
        timeline._current_key, timeline._current_idx = None, 0
        timeline.tile_combo = MagicMock()
        timeline.tile_combo.findData.return_value = 1
        timeline._navigate_to = MagicMock()

        self.assertEqual(timeline.group_sizes(), {("S2", "crop", "B04"): 3, ("S2", "031020", "B04"): 1})
        timeline.show_group(("S2", "crop", "B04"))
        timeline.tile_combo.setCurrentIndex.assert_called_once_with(1)
        timeline._navigate_to.assert_called_once_with(0)
        self.assertEqual(timeline.position(), (("S2", "crop", "B04"), 0))
        timeline.show_group(("missing",))
        timeline._navigate_to.assert_called_once_with(0)

    def test_panel_current_entry_follows_the_chart(self):
        from bdc_loader_plugin.ui.timeseries_panel import BDCTimeSeriesPanel

        panel = BDCTimeSeriesPanel.__new__(BDCTimeSeriesPanel)
        panel._history = [{"id": 1}, {"id": 2}]
        panel._current_viz_index = 1
        self.assertEqual(panel.current_entry(), {"id": 2})
        panel._current_viz_index = 5
        self.assertIsNone(panel.current_entry())


def test_the_search_again_step_waits_for_a_search_with_the_new_bands():
    from unittest.mock import MagicMock, patch

    from bdc_loader_plugin.ui import tour_steps

    dialog = MagicMock()
    dialog._changed_search_params.return_value = ["bands"]
    assert tour_steps._searched_again(dialog, tour_steps.CROP) is False
    dialog._changed_search_params.return_value = []
    with patch.object(tour_steps, "_searched", return_value=True) as searched:
        assert tour_steps._searched_again(dialog, tour_steps.CROP) is True
    searched.assert_called_once_with(dialog, tour_steps.CROP)
