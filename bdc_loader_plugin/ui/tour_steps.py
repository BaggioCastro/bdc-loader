"""The plugin's tutorial: a real case, done by the user, from the tile grid to the time series chart.

The user cuts a box out of the images, steps through its dates on the
timeline, loads it in another band composition, cuts the image to a polygon
(an 8 km circle shipped with the plugin), loads a whole tile, and reads the
time series of points on it.

The example is native cerrado in western Bahia that PRODES Cerrado maps as
cleared in 2022 (polygon 2331370, 58 km²). In the BDC Sentinel-2 cube
(S2-16D-2, tile 031020) its NDVI rises in the rains and dips in the dry season
until October 2021, then drops to about 0.1 to 0.2 and stays low. A second
point lies in the clearing next to it, PRODES 2023 (polygon 1457611), whose
NDVI falls in April 2023, and a third in native cerrado 1.7 km from any
PRODES clearing, whose yearly wave goes on until 2023. The dry season images
of August and September 2022 have no cloud over the area.
"""

import math
import os

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeatureRequest,
    QgsFillSymbol,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsSettings,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QDate, QTimer
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QAbstractItemView, QApplication, QMenu, QPushButton

from ..core.layer_names import layer_key
from ..i18n import both
from ..timing import AFTER_HANDLER_MS, TOUR_ZOOM_MS
from .tour import GuidedTour, TourStep

TOUR_SEEN_SETTING = "bdc_loader/tour_seen"

EXAMPLE_COLLECTION = "S2-16D-2"
EXAMPLE_GRID = "BDC_SM_V2"
EXAMPLE_TILE = "031020"
# west, south, east, north around the clearings, and a wider view with the tiles around them
EXAMPLE_AREA = (-45.27, -13.86, -45.08, -13.75)
EXAMPLE_REGION = (-46.6, -14.9, -43.6, -12.6)
EXAMPLE_SEARCH_PERIOD = ((2022, 8, 1), (2022, 9, 30))
EXAMPLE_SCENE_DATE = "20220914"
EXAMPLE_SERIES_PERIOD = ((2019, 1, 1), (2023, 12, 31))
EXAMPLE_POINTS = (
    ("Cut 2022", -45.11375, -13.82825),
    ("Cut 2023", -45.19223, -13.77805),
    ("Native cerrado", -45.24, -13.785),
)
# A click this close to an example point tells the same story (checked at 8 points on this circle).
PICK_RADIUS_M = 250
RGB_BANDS = ("B04", "B03", "B02")
TRUE_COLOR = "True Color"
FALSE_COLOR = "False Color"
FALSE_COLOR_BAND = "B08"
# An 8 km circle over the three example points.
CIRCLE_PATH = os.path.join(os.path.dirname(__file__), "tour_circle.geojson")
CIRCLE_NAME = "Tutorial circle"
_SCENE_DAYS = (EXAMPLE_SCENE_DATE, f"{EXAMPLE_SCENE_DATE[:4]}-{EXAMPLE_SCENE_DATE[4:6]}-{EXAMPLE_SCENE_DATE[6:]}")
# A drawn box wider or taller than this, in degrees, is refused: the crop would be slow to load.
MAX_BOX_DEG = 1.0

GRID_OFFER_TEXT = "Open <b>Extent</b>. The plugin offers the BDC tile grids: select <b>BDC_SM_V2</b>, the small tiles."
GRID_READY_TEXT = "The BDC tile grid BDC_SM_V2 is already on the map. Click <b>Next</b>."
GRID_OFFER_TITLE = "Load BDC Grid Reference"
DRAW_TEXT = "Click <b>{}</b>, then drag a box over the amber outline on the map."
FALSE_COLOR_TEXT = (
    "Vegetation appears red: dark red for native cerrado, bright red along the streams. "
    "Bare dry season fields appear green and pale blue."
)


def _qdate(ymd):
    return QDate(*ymd)


def _to_canvas(rect, canvas):
    """``rect`` in WGS 84, transformed to the canvas CRS."""
    source = QgsCoordinateReferenceSystem("EPSG:4326")
    target = canvas.mapSettings().destinationCrs()
    if target.isValid() and target != source:
        rect = QgsCoordinateTransform(source, target, QgsProject.instance()).transformBoundingBox(rect)
    return rect


def _zoom_to(dialog, bbox):
    canvas = dialog.iface.mapCanvas()
    canvas.setExtent(_to_canvas(QgsRectangle(*bbox), canvas))
    canvas.refresh()


def _zoom_to_box(dialog, west, south, east, north, margin, room):
    """Zoom to the box with ``margin`` around it and ``room`` more to the east and south,
    where the callout sits on the map, so it does not cover what the step shows."""
    _zoom_to(dialog, (west - margin, south - margin - room, east + margin + room, north + margin))


def _zoom_to_example(dialog):
    _zoom_to_box(dialog, *EXAMPLE_AREA, margin=0.02, room=0.08)


def _zoom_to_points(dialog, points, margin=0.02, room=0.0):
    lons = [lon for _label, lon, _lat in points]
    lats = [lat for _label, _lon, lat in points]
    _zoom_to_box(dialog, min(lons), min(lats), max(lons), max(lats), margin, room)


def _distance_m(lon, lat, point):
    _label, plon, plat = point
    dx = (lon - plon) * 111320 * math.cos(math.radians(plat))
    return math.hypot(dx, (lat - plat) * 111320)


def _near(lon, lat, point):
    return _distance_m(lon, lat, point) <= PICK_RADIUS_M


def _wgs84():
    return QgsCoordinateReferenceSystem("EPSG:4326")


class MapMarks:
    """The outline the tutorial draws on the map where the user has to work, until cleared."""

    def __init__(self, canvas):
        self.canvas = canvas
        self.band = None

    def show(self, geometry, crs):
        from qgis.gui import QgsRubberBand

        self.clear()
        self.band = QgsRubberBand(self.canvas)
        self.band.setStrokeColor(QColor(245, 158, 11))
        self.band.setFillColor(QColor(245, 158, 11, 40))
        self.band.setWidth(3)
        self.band.setToGeometry(geometry, crs)
        self.band.show()

    def show_circles(self, points):
        radius = PICK_RADIUS_M / 111320
        circles = [QgsGeometry.fromPointXY(QgsPointXY(lon, lat)).buffer(radius, 24) for _label, lon, lat in points]
        self.show(QgsGeometry.collectGeometry(circles), _wgs84())

    def clear(self):
        if self.band is not None:
            self.band.reset()
            self.canvas.scene().removeItem(self.band)
            self.band = None


def _collection_chosen(dialog, ctx):
    """True for the Sentinel-2 cube; a hint once the user picks another one after Cubes."""
    text = dialog.collection_combo.currentText()
    if f"({EXAMPLE_COLLECTION})" in text:
        return True
    if not dialog.filter_cube_btn.isChecked():
        ctx.pop("first_cube", None)
        return False
    # Cubes itself selects the first cube of the list; only a later change is the user's.
    if text != ctx.setdefault("first_cube", text):
        return f"That is {text}. Choose Sentinel-2 Cube 16D (S2-16D-2)."
    return False


def _example_collection_index(combo):
    return next((i for i in range(combo.count()) if f"({EXAMPLE_COLLECTION})" in combo.itemText(i)), -1)


def _combo_target(combo, row):
    """The combo; while its list is open, the item at ``row`` in it."""
    view = combo.view()
    if view.isVisible() and row >= 0:
        index = combo.model().index(row, combo.modelColumn())
        view.scrollTo(index, QAbstractItemView.ScrollHint.EnsureVisible)
        return view.viewport(), view.visualRect(index)
    return combo


def _collection_target(dialog):
    """Cubes first; then the list, and in the open list the Sentinel-2 cube item."""
    if not dialog.filter_cube_btn.isChecked():
        return dialog.filter_cube_btn
    return _combo_target(dialog.collection_combo, _example_collection_index(dialog.collection_combo))


def _reset_area(dialog, ctx):
    """Start the area filters empty, so opening Extent offers the grid."""
    ctx["empty_map"] = not QgsProject.instance().mapLayers()
    ctx["had_grid"] = _grid_layer() is not None
    ctx["offered"] = False
    dialog.clear_tiles()
    dialog._clear_extent()
    dialog.extent_box.setCollapsed(True)
    dialog.tiles_group.setCollapsed(True)
    dialog._apply_spatial_locks()


def _grid_layer():
    layers = QgsProject.instance().mapLayersByName(EXAMPLE_GRID)
    return layers[0] if layers and layers[0].isValid() else None


def _grid_target(dialog):
    """Extent, then the small grid's button in the grid offer."""
    modal = QApplication.activeModalWidget()
    if modal is not None and modal.windowTitle() in both(GRID_OFFER_TITLE):
        for button in modal.findChildren(QPushButton):
            if button.text().strip() == EXAMPLE_GRID:
                return button
    return dialog.extent_box


def _offer_grid_on_open(dialog, ctx):
    """Open the grid offer when Extent opens on a project with layers, where the plugin skips it."""
    if ctx.get("empty_map", True) or ctx.get("offered") or _grid_layer() is not None:
        return
    if not dialog.extent_box.isCollapsed():
        ctx["offered"] = True
        QTimer.singleShot(AFTER_HANDLER_MS, dialog._offer_reference_grid)


def _prepare_draw(dialog, marks):
    """Outline the example area on the map and open Extent, where Draw on Canvas is."""
    dialog.update_grid_status()
    if dialog.extent_box.isCollapsed():
        dialog.extent_box.setCollapsed(False)
    marks.show(QgsGeometry.fromRect(QgsRectangle(*EXAMPLE_AREA)), _wgs84())
    west, south, east, north = EXAMPLE_AREA
    _zoom_to(dialog, (west - 0.3, south - 0.2, east + 0.3, north + 0.2))


def _draw_button(dialog):
    return dialog.extent_box.extent_widget.findChild(QPushButton, "mButtonDrawOnCanvas")


def _button_text(button, default):
    text = button.text() if button is not None else ""
    return text.replace("&", "") if isinstance(text, str) and text else default


def _drawn_box(dialog):
    """The extent drawn on the map, in WGS 84, or None."""
    if not dialog.extent_box.wasDrawn():
        return None
    try:
        west, south, east, north = (float(v) for v in dialog._extent_bbox_edit.text().split(","))
    except ValueError:
        return None
    return QgsRectangle(west, south, east, north)


def _drew_over_example(dialog):
    if not dialog.isVisible():
        return False
    box = _drawn_box(dialog)
    if box is None:
        return False
    if not box.intersects(QgsRectangle(*EXAMPLE_AREA)):
        return "That box misses the amber outline. Click Draw on Canvas again."
    if box.width() > MAX_BOX_DEG or box.height() > MAX_BOX_DEG:
        return "That box is much larger than the outline. Click Draw on Canvas and draw a smaller one."
    return True


def _tile_feature(layer):
    point = QgsPointXY(EXAMPLE_POINTS[0][1], EXAMPLE_POINTS[0][2])
    if layer.crs().authid() != "EPSG:4326":
        point = QgsCoordinateTransform(_wgs84(), layer.crs(), QgsProject.instance()).transform(point)
    for feature in layer.getFeatures(QgsFeatureRequest().setFilterRect(QgsRectangle(point, point))):
        if feature.geometry().contains(QgsGeometry.fromPointXY(point)):
            return feature
    return None


def _outline_tile(dialog, marks):
    """Show the tile grid and outline the example tile, over the region around it."""
    _zoom_to(dialog, EXAMPLE_REGION)
    layer = _grid_layer()
    _set_visible(layer, True)
    feature = _tile_feature(layer) if layer else None
    if feature is not None:
        marks.show(feature.geometry(), layer.crs())


def _prepare_tile(dialog, marks):
    """Free the Tiles filter (another area filter in use locks it), open it and outline the tile."""
    dialog._clear_shapefile()
    dialog._clear_extent()
    dialog.extent_box.setCollapsed(True)
    dialog.shape_group.setCollapsed(True)
    dialog.update_grid_status()
    dialog._apply_spatial_locks()
    dialog.tiles_group.setCollapsed(False)
    _outline_tile(dialog, marks)


def _chose_example_tile(dialog):
    tiles = [t.strip() for t in dialog.tiles_input.text().split(",") if t.strip()]
    if not tiles or not dialog.isVisible():
        return False
    if tiles == [EXAMPLE_TILE]:
        return True
    if EXAMPLE_TILE in tiles:
        return f"Leave only tile {EXAMPLE_TILE}: click \u2715 to clear the list, then select it again."
    return f"That is tile {tiles[-1]}. Click \u2715 to clear it, then select the amber one."


def _tile_target(dialog):
    """Select on Map; the clear button while a wrong tile is listed."""
    tiles = [t.strip() for t in dialog.tiles_input.text().split(",") if t.strip()]
    return dialog.clear_tiles_btn if tiles and tiles != [EXAMPLE_TILE] else dialog.select_tiles_btn


def _preset_index(dialog, name):
    combo = dialog.preset_combo
    return next((i for i in range(combo.count()) if combo.itemText(i).startswith(name)), -1)


def _use_true_color(dialog):
    index = _preset_index(dialog, TRUE_COLOR)
    if index >= 0:
        dialog.preset_combo.setCurrentIndex(index)


def _prepare_crop(dialog, marks):
    """Start from an empty result list, with the dry season dates and the True Color bands."""
    marks.clear()
    dialog.clear_results()
    start, end = EXAMPLE_SEARCH_PERIOD
    dialog.range_slider.set_start_date(_qdate(start))
    dialog.range_slider.set_end_date(_qdate(end))
    _use_true_color(dialog)


def _crop_target(dialog):
    return dialog.search_btn if dialog._extent_mode_crop.isChecked() else dialog._extent_mode_crop


def _is_example_day(text):
    """``text`` names the example date, written 20220914 or 2022-09-14 (the two layer naming styles)."""
    return any(day in text for day in _SCENE_DAYS)


# The three kinds of example image: the drawn box, the circle and the whole tile.
CROP, CIRCLE, TILE = "crop", "circle", "tile"


def _card_kind(item):
    props = getattr(item, "properties", None) or {}
    if props.get("bdc:is_extent_crop"):
        return CROP
    if props.get("bdc:feature_name") == CIRCLE_NAME:
        return CIRCLE
    return None if props.get("bdc:is_shape_mosaic") else TILE


def _cards(dialog, kind):
    return [w for w in dialog.result_widgets if _card_kind(w.item) == kind]


def _example_card(dialog, kind):
    return next((w for w in _cards(dialog, kind) if _is_example_day(w.item.id)), None)


def _searched(dialog, kind):
    if getattr(dialog, "_search_in_progress", False) or not dialog.result_widgets:
        return False
    if _example_card(dialog, kind) is not None:
        return True
    kinds = {_card_kind(w.item) for w in dialog.result_widgets}
    if kind == CROP and kinds == {TILE}:
        return "These are whole tiles. Pick Crop, then click Search STAC again."
    if kind in kinds:
        return "No image of 14 Sep 2022 in the list: check the area and the dates."
    return False  # the earlier cards stay listed until the new search replaces them


def _searched_again(dialog, kind):
    """The results on screen come from a search made with the panel as it is now."""
    if dialog._changed_search_params():
        return False
    return _searched(dialog, kind)


def _untick_cards(dialog):
    for widget in dialog.result_widgets:
        widget.set_selected(False)


def _card_part(card):
    """The card without its STAC and download buttons, which a tick does not need."""
    buttons = [b.geometry().left() for b in card.findChildren(QPushButton) if b.isVisible()]
    rect = card.rect()
    if buttons:
        rect.setRight(min(buttons) - 4)
    return card, rect


def _card_or_load(dialog, kind):
    card = _example_card(dialog, kind)
    if card is None or card.is_selected():
        return dialog.load_btn
    return _card_part(card)


def _example_layers(kind, bands=None):
    """Loaded example images of ``kind``, in any band composition unless ``bands`` names one band in it.

    Read from the layer's name and machine name, which carry the date in
    either naming style, "crop" or the circle's name for an area, and the bands.
    """
    found = []
    for layer in QgsProject.instance().mapLayers().values():
        if not isinstance(layer, QgsRasterLayer):
            continue
        text = f"{layer.name()} {layer_key(layer)}"
        if _names_kind(text) == kind and (bands is None or bands in text):
            found.append(layer)
    return found


def _names_kind(text):
    if "crop" in text:
        return CROP
    if CIRCLE_NAME.replace(" ", "-") in text:
        return CIRCLE
    return TILE if EXAMPLE_TILE in text else None


def _example_layer(kind, bands=None):
    return next((lyr for lyr in _example_layers(kind, bands) if _is_example_day(lyr.name() + layer_key(lyr))), None)


def _loaded_example(dialog, kind, bands=None):
    if _example_layer(kind, bands) is not None:
        return True
    card = _example_card(dialog, kind)
    if any(w.is_selected() and w is not card for w in dialog.result_widgets):
        return "Tick only the 14 Sep 2022 card."
    return False


def _all_or_load(dialog):
    cards = _cards(dialog, CROP)
    if cards and all(w.is_selected() for w in cards):
        return dialog.load_btn
    return dialog.sel_all_btn


def _loaded_all_dates(dialog):
    wanted = len(_cards(dialog, CROP))
    loaded = len(_example_layers(CROP, RGB_BANDS[0]))
    if wanted and loaded >= wanted:
        return True
    if loaded:
        return f"{loaded} of {wanted} dates loaded. Click All, then Load layers."
    return False


def _set_visible(layer, visible):
    node = QgsProject.instance().layerTreeRoot().findLayer(layer.id()) if layer is not None else None
    if node is None:
        return
    if visible:
        node.setItemVisibilityCheckedParentRecursive(True)
    else:
        node.setItemVisibilityChecked(False)


def _show_only(dialog, layers):
    """Draw ``layers`` alone among the example images, so one stretch shows."""
    for kind in (CROP, CIRCLE, TILE):
        for layer in _example_layers(kind):
            _set_visible(layer, False)
    for layer in layers:
        _set_visible(layer, True)
    dialog.iface.mapCanvas().refresh()


def _zoom_to_layer(dialog, layer, scale=1.4):
    canvas = dialog.iface.mapCanvas()
    extent = QgsCoordinateTransform(
        layer.crs(), canvas.mapSettings().destinationCrs(), QgsProject.instance()
    ).transformBoundingBox(layer.extent())
    extent.scale(scale)
    canvas.setExtent(extent)
    canvas.refresh()


def _timeline(dialog):
    return getattr(dialog, "_timeline_toolbar", None)


def _crop_group_key(timeline):
    sizes = timeline.group_sizes()
    keys = [k for k in sizes if "crop" in str(k[1]) and RGB_BANDS[0] in str(k[2])]
    return max(keys, key=sizes.get) if keys else None


def _prepare_timeline(dialog, marks, ctx):
    """Show the timeline on the first date of the box, zoomed to it."""
    marks.clear()
    timeline = _timeline(dialog)
    if not dialog.tl_btn.isChecked():
        dialog.tl_btn.setChecked(True)
        dialog._toggle_timeline_toolbar(True)
    timeline.scan_project_layers()
    key = _crop_group_key(timeline)
    if key is not None:
        timeline.show_group(key)
    layers = _example_layers(CROP, RGB_BANDS[0])
    if layers:
        _zoom_to_layer(dialog, layers[0])
    ctx["dates"] = timeline.group_sizes().get(key, 0) if key else 0


def _walked_dates(dialog, ctx):
    timeline = _timeline(dialog)
    if not timeline.isVisible():
        timeline.setVisible(True)
    key = _crop_group_key(timeline)
    shown_key, index = timeline.position()
    return key is not None and shown_key == key and index >= ctx.get("dates", 0) - 1


def _preset_target(dialog):
    return _combo_target(dialog.preset_combo, _preset_index(dialog, FALSE_COLOR))


def _chose_false_color(dialog):
    text = dialog.preset_combo.currentText()
    if text.startswith(FALSE_COLOR):
        return True
    if dialog.preset_combo.currentIndex() > 0 and not text.startswith(TRUE_COLOR):
        return f"That is {text}. Choose {FALSE_COLOR} (8,4,3)."
    return False


def _show_false_color(dialog, marks):
    marks.clear()
    layer = _example_layer(CROP, FALSE_COLOR_BAND)
    _show_only(dialog, [layer] if layer else [])
    if layer is not None:
        _zoom_to_layer(dialog, layer)


def _circle_layer():
    for layer in QgsProject.instance().mapLayers().values():
        if isinstance(layer, QgsVectorLayer) and os.path.normpath(layer.source().split("|")[0]) == CIRCLE_PATH:
            return layer
    return None


def _prepare_circle(dialog, marks):
    """Put the example circle in the project and open Vector File, freed of the drawn box."""
    marks.clear()
    if _circle_layer() is None:
        layer = QgsVectorLayer(CIRCLE_PATH, CIRCLE_NAME, "ogr")
        # An outline only, so the image cut to the circle shows through it.
        layer.renderer().setSymbol(
            QgsFillSymbol.createSimple({"color": "0,0,0,0", "outline_color": "245,158,11", "outline_width": "0.8"})
        )
        QgsProject.instance().addMapLayer(layer)
    dialog.clear_results()
    dialog._clear_extent()
    dialog.extent_box.setCollapsed(True)
    dialog._apply_spatial_locks()
    dialog.shape_group.setCollapsed(False)


def _circle_target(dialog):
    """Layer, then the circle in the menu it opens."""
    menu = QApplication.activePopupWidget()
    if isinstance(menu, QMenu):
        for action in menu.actions():
            if action.text().startswith(CIRCLE_NAME):
                return menu, menu.actionGeometry(action)
    return dialog.shape_layer_btn


def _chose_circle(dialog):
    layer = getattr(dialog, "_shape_vector_layer", None)
    return layer is not None and layer is _circle_layer()


def _show_circle(dialog, marks):
    marks.clear()
    layer = _example_layer(CIRCLE)
    circle = _circle_layer()
    _show_only(dialog, [layer] if layer else [])
    _set_visible(circle, True)
    if circle is not None:
        _zoom_to_layer(dialog, circle, scale=1.3)


def _prepare_tile_search(dialog, marks):
    """The whole tile is read in True Color, the composition the time series steps describe."""
    _use_true_color(dialog)


def _show_example_image(dialog, marks):
    """Draw the whole tile image alone."""
    marks.clear()
    layer = _example_layer(TILE)
    _show_only(dialog, [layer] if layer else [])
    _set_visible(_circle_layer(), False)
    _zoom_to_example(dialog)


def _ts(dialog, name=None):
    panel = getattr(dialog, "_ts_panel", None)
    if panel is None or name is None:
        return panel
    return getattr(panel, name, None)


def _chart(dialog, name=None):
    dock = getattr(_ts(dialog), "chart_dock", None)
    if dock is None or name is None:
        return dock
    return getattr(dock, name, None)


def _panel_open(dialog):
    panel = _ts(dialog)
    return bool(panel is not None and panel.isVisible())


def _open_ts_panel(dialog):
    if not _panel_open(dialog):
        dialog.ts_btn.setChecked(True)
        dialog._toggle_timeseries_panel(True)


def _prepare_series(dialog, marks, ctx, points, bands, multi):
    """Set the example's collection, period and bands, clear the points and circle where to click."""
    _open_ts_panel(dialog)
    panel = _ts(dialog)
    combo = panel.ts_collection_combo
    index = combo.findData(EXAMPLE_COLLECTION)
    if index >= 0 and combo.currentIndex() != index:
        combo.setCurrentIndex(index)
    start, end = EXAMPLE_SERIES_PERIOD
    panel.range_slider.set_start_date(_qdate(start))
    panel.range_slider.set_end_date(_qdate(end))
    panel.check_bands(bands)
    if not multi:
        panel.single_point_btn.setChecked(True)
        # The chart opens with the first series read; opened now, it does not shrink the map under the click.
        panel.open_chart()
    panel.clear_points()
    marks.show_circles(points)
    _series_view(dialog, ctx)


def _series_view(dialog, ctx):
    """One view of the three points for every time series step, set once the docks have their size."""
    canvas = dialog.iface.mapCanvas()
    if ctx.get("series_extent") is not None and canvas.extent() == ctx["series_extent"]:
        return

    def zoom():
        _zoom_to_points(dialog, EXAMPLE_POINTS, margin=0.02, room=0.06)
        ctx["series_extent"] = canvas.extent()

    QTimer.singleShot(TOUR_ZOOM_MS, zoom)


def _prepare_ndvi(dialog, marks, ctx):
    """One point, NDVI only; the series already read tell a wrong click from a new one."""
    _prepare_series(dialog, marks, ctx, EXAMPLE_POINTS[:1], ("NDVI",), multi=False)
    ctx["history"] = len(_ts(dialog).history_entries())
    line_btn = _chart(dialog, "line_mode_btn")
    if line_btn is not None:
        line_btn.setChecked(True)


def _pick_target(dialog):
    pick = _ts(dialog, "pick_btn")
    return dialog.iface.mapCanvas() if pick.isChecked() else pick


def _entries_near(dialog, point, bands=("NDVI",)):
    return [
        e
        for e in _ts(dialog).history_entries()
        if _near(e["lon"], e["lat"], point) and all(b in e.get("data", {}) for b in bands)
    ]


def _ndvi_ready(dialog, ctx):
    panel = _ts(dialog)
    if _entries_near(dialog, EXAMPLE_POINTS[0]) and panel.chart_dock is not None:
        return True
    if len(panel.history_entries()) > ctx.get("history", 0):
        return "That point is outside the amber circle. Click inside it."
    return False


def _rgb_done(dialog):
    panel = _ts(dialog)
    if not _chart(dialog, "rgb_mode_btn").isChecked():
        return False
    entry = panel.current_entry() or {}
    return not panel.rgb_bands_pending() and all(b in entry.get("data", {}) for b in RGB_BANDS)


def _prepare_date_click(dialog, ctx):
    """Remember the chart's click halo, so a new double-click is told from an older one."""
    ctx["halo"] = getattr(_chart(dialog), "_click_highlight", None)


def _date_image_shown(dialog, ctx):
    """A dot was double-clicked and the image of its date is the active layer on the map."""
    if getattr(_ts(dialog), "_chart_vrt_running", False):
        return False
    halo = getattr(_chart(dialog), "_click_highlight", None)
    if halo is None or halo is ctx.get("halo"):
        return False
    layer = dialog.iface.activeLayer()
    return isinstance(layer, QgsRasterLayer) and EXAMPLE_TILE in f"{layer.name()} {layer_key(layer)}"


def _points_target(dialog):
    panel = _ts(dialog)
    if not panel.multi_point_btn.isChecked():
        return panel.multi_point_btn
    if any(not _near_any(lon, lat) for lon, lat, _label in panel.picked_points()):
        return panel.clear_pts_btn
    return _pick_target(dialog)


def _near_any(lon, lat):
    return any(_near(lon, lat, p) for p in EXAMPLE_POINTS)


def _points_placed(dialog):
    panel = _ts(dialog)
    if not panel.multi_point_btn.isChecked():
        return False
    points = panel.picked_points()
    for lon, lat, label in points:
        if not _near_any(lon, lat):
            return f"{label} is outside the circles. Click Clear, then click the three circles again."
    return all(any(_near(lon, lat, p) for lon, lat, _label in points) for p in EXAMPLE_POINTS)


def _all_points_ready(dialog):
    return all(_entries_near(dialog, p, ("NDVI", *RGB_BANDS)) for p in EXAMPLE_POINTS)


def _prepare_browse(dialog, marks, ctx):
    marks.clear()
    ctx["viz"] = _ts(dialog)._current_viz_index


def _browsed(dialog, ctx):
    return _ts(dialog)._current_viz_index != ctx.get("viz")


# The parts of the tour, shown above each step's title.
INTRO, DATA, VIEW, SHAPE, TILES, SITS = (
    "Getting started",
    "Data discovery",
    "Visualization",
    "Area of interest",
    "Tiles",
    "Time series",
)


def main_tour_steps(dialog, marks):
    d = dialog
    ctx = {}
    canvas = d.iface.mapCanvas
    return [
        TourStep(
            "Welcome to BDC Loader",
            "A case study: native cerrado in western Bahia, deforested in 2022 (PRODES Cerrado). "
            "You run each step; the highlight shows where.",
            section=INTRO,
        ),
        TourStep(
            "Select the data cube",
            "Click <b>Cubes</b>, open the list and select <b>Sentinel-2 Cube 16D (S2-16D-2)</b>: "
            "10 m, one composite every 16 days.",
            section=DATA,
            target=lambda: _collection_target(d),
            prepare=lambda: ctx.pop("first_cube", None),
            done=lambda: _collection_chosen(d, ctx),
        ),
        TourStep(
            "Load the BDC tile grid",
            lambda: GRID_READY_TEXT if ctx.get("had_grid") else GRID_OFFER_TEXT,
            section=DATA,
            target=lambda: _grid_target(d),
            prepare=lambda: _reset_area(d, ctx),
            done=lambda: _grid_layer() is not None,
            watch=lambda: _offer_grid_on_open(d, ctx),
        ),
        TourStep(
            "Draw the area of interest",
            # The button belongs to QGIS, which may show it translated: name it as shown.
            lambda: DRAW_TEXT.format(_button_text(_draw_button(d), "Draw on Canvas")),
            section=DATA,
            target=lambda: _draw_button(d),
            prepare=lambda: _prepare_draw(d, marks),
            done=lambda: _drew_over_example(d),
            map_body="Drag a box over the amber outline. The plugin returns when you release the mouse.",
        ),
        TourStep(
            "Search images clipped to the box",
            "Select <b>Crop</b>, then click <b>Search STAC</b>. Period: August to September 2022, the dry season.",
            section=DATA,
            target=lambda: _crop_target(d),
            prepare=lambda: _prepare_crop(d, marks),
            done=lambda: _searched(d, CROP),
        ),
        TourStep(
            "Load all dates",
            "Click <b>All</b> to select every date, then <b>Load layers</b>.",
            section=VIEW,
            target=lambda: _all_or_load(d),
            prepare=lambda: _untick_cards(d),
            done=lambda: _loaded_all_dates(d),
        ),
        TourStep(
            "Navigate the timeline",
            "The timeline bar holds one layer per date. Click <b>Next \u25b6</b> up to the last date.",
            section=VIEW,
            target=lambda: _timeline(d).next_btn,
            prepare=lambda: _prepare_timeline(d, marks, ctx),
            done=lambda: _walked_dates(d, ctx),
            aside=True,
            also=lambda: (_timeline(d).date_bar, _timeline(d).prev_btn, canvas()),
        ),
        TourStep(
            "Choose a band composition",
            "Under <b>Bands</b>, open <b>Preset</b> and select <b>False Color (8,4,3)</b>: NIR, red and green.",
            section=VIEW,
            target=lambda: _preset_target(d),
            done=lambda: _chose_false_color(d),
        ),
        TourStep(
            "Search with the new bands",
            "The results follow the bands of the search, so <b>Search STAC</b> turned amber. "
            "Click it again: same box and period.",
            section=VIEW,
            target=lambda: d.search_btn,
            done=lambda: _searched_again(d, CROP),
        ),
        TourStep(
            "Load the new composition",
            "Select <b>14 Sep 2022</b>, then click <b>Load layers</b>.",
            section=VIEW,
            target=lambda: _card_or_load(d, CROP),
            prepare=lambda: _untick_cards(d),
            done=lambda: _loaded_example(d, CROP, FALSE_COLOR_BAND),
        ),
        TourStep(
            "False color composite",
            FALSE_COLOR_TEXT,
            section=VIEW,
            target=canvas,
            prepare=lambda: _show_false_color(d, marks),
            aside=True,
        ),
        TourStep(
            "Clip to a polygon",
            f"The plugin ships an example circle. Under <b>Vector File</b>, click <b>Layer</b> "
            f"and select <b>{CIRCLE_NAME}</b>.",
            section=SHAPE,
            target=lambda: _circle_target(d),
            prepare=lambda: _prepare_circle(d, marks),
            done=lambda: _chose_circle(d),
        ),
        TourStep(
            "Search within the polygon",
            "Click <b>Search STAC</b>: same period, images clipped to the circle.",
            section=SHAPE,
            target=lambda: d.search_btn,
            done=lambda: _searched(d, CIRCLE),
        ),
        TourStep(
            "Load the clipped image",
            "Select <b>14 Sep 2022</b>, then click <b>Load layers</b>.",
            section=SHAPE,
            target=lambda: _card_or_load(d, CIRCLE),
            prepare=lambda: _untick_cards(d),
            done=lambda: _loaded_example(d, CIRCLE),
        ),
        TourStep(
            "Polygon mask applied",
            "Only pixels inside the circle were loaded. Any polygon layer works the same way.",
            section=SHAPE,
            target=canvas,
            prepare=lambda: _show_circle(d, marks),
            aside=True,
        ),
        TourStep(
            "BDC tile grid",
            f"Each square is a BDC tile, about 110 km wide. The amber tile, {EXAMPLE_TILE}, covers the clearings.",
            section=TILES,
            target=canvas,
            prepare=lambda: _outline_tile(d, marks),
            aside=True,
        ),
        TourStep(
            "Select a tile on the map",
            "Click <b>Select on Map</b>, then the amber tile.",
            section=TILES,
            target=lambda: _tile_target(d),
            prepare=lambda: _prepare_tile(d, marks),
            done=lambda: _chose_example_tile(d),
            map_body=f"Click inside the amber tile, {EXAMPLE_TILE}. The plugin returns by itself.",
        ),
        TourStep(
            "Search the whole tile",
            "Same period, back to True Color, for the whole tile. Click <b>Search STAC</b>.",
            section=TILES,
            target=lambda: d.search_btn,
            prepare=lambda: _prepare_tile_search(d, marks),
            done=lambda: _searched(d, TILE),
        ),
        TourStep(
            "Load the tile",
            "Select <b>14 Sep 2022</b>, then click <b>Load layers</b>.",
            section=TILES,
            target=lambda: _card_or_load(d, TILE),
            prepare=lambda: _untick_cards(d),
            done=lambda: _loaded_example(d, TILE),
        ),
        TourStep(
            "True color composite",
            "Pale fields were cleared from the cerrado. The dark ground cut by streams is native cerrado.",
            section=TILES,
            target=canvas,
            prepare=lambda: _show_example_image(d, marks),
            aside=True,
        ),
        TourStep(
            "Satellite image time series",
            "Turn on <b>Time Series</b>: the panel extracts the time series of a pixel from the BDC data cubes.",
            section=SITS,
            target=lambda: d.ts_btn,
            done=lambda: _panel_open(d),
        ),
        TourStep(
            "Extract an NDVI time series",
            "NDVI, 2019 to 2023, is set. Turn on the pick button, then click inside the amber circle.",
            section=SITS,
            target=lambda: _pick_target(d),
            prepare=lambda: _prepare_ndvi(d, marks, ctx),
            done=lambda: _ndvi_ready(d, ctx),
            aside=True,
            also=lambda: (canvas(),),
        ),
        TourStep(
            "NDVI trajectory",
            "A seasonal cycle of native cerrado until late 2021, then an abrupt drop that persists: the clearing.",
            section=SITS,
            target=lambda: _chart(d, "canvas_plot") or _chart(d),
            prepare=marks.clear,
            aside=True,
        ),
        TourStep(
            "RGB time series",
            "Click <b>RGB</b>: each observation is drawn in the pixel's true color.",
            section=SITS,
            target=lambda: _chart(d, "rgb_mode_btn"),
            done=lambda: _rgb_done(d),
            aside=True,
        ),
        TourStep(
            "Land cover change",
            "Olive-brown dots are cerrado vegetation. From late 2021 they turn pink and tan: bare soil. "
            "Pale dots are clouds.",
            section=SITS,
            target=lambda: _chart(d, "canvas_plot") or _chart(d),
            aside=True,
        ),
        TourStep(
            "Image of a date",
            "Double-click a dot: the map loads the image of that date. Try a pink dot of 2022.",
            section=SITS,
            target=lambda: _chart(d, "canvas_plot") or _chart(d),
            prepare=lambda: _prepare_date_click(d, ctx),
            done=lambda: _date_image_shown(d, ctx),
            aside=True,
            also=lambda: (canvas(),),
        ),
        TourStep(
            "Several points",
            "Click <b>Multi</b>, turn on the pick button, then click the three amber circles.",
            section=SITS,
            target=lambda: _points_target(d),
            prepare=lambda: _prepare_series(d, marks, ctx, EXAMPLE_POINTS, ("NDVI", *RGB_BANDS), multi=True),
            done=lambda: _points_placed(d),
            aside=True,
            also=lambda: (canvas(),),
        ),
        TourStep(
            "Batch extraction",
            "Click <b>Extract</b> to read the three time series.",
            section=SITS,
            target=lambda: _ts(d, "extract_btn"),
            done=lambda: _all_points_ready(d),
            aside=True,
        ),
        TourStep(
            "Compare trajectories",
            "Use <b>&lt;</b> and <b>&gt;</b>: clearing of 2022, clearing of 2023 and native cerrado.",
            section=SITS,
            target=lambda: _chart(d, "prev_chart_btn"),
            prepare=lambda: _prepare_browse(d, marks, ctx),
            done=lambda: _browsed(d, ctx),
            aside=True,
            also=lambda: (_chart(d, "next_chart_btn"), _chart(d, "canvas_plot")),
        ),
        TourStep(
            "Tutorial complete",
            "Open it again from Settings, under <b>Show tutorial</b>.",
            section=INTRO,
            target=lambda: getattr(d, "config_btn", None),
        ),
    ]


class PluginTour:
    """Runs the tutorial; when it is skipped, closes the panels it opened."""

    def __init__(self, dialog):
        self.dialog = dialog
        self.marks = MapMarks(dialog.iface.mapCanvas())
        steps = main_tour_steps(dialog, self.marks)
        self.tour = GuidedTour(
            steps, dialog, windows=lambda: (dialog.iface.mainWindow(),), map_view=dialog.iface.mapCanvas
        )
        self.tour.finished.connect(self._finished)
        self._had_ts_panel = False

    def start(self):
        self._had_ts_panel = _panel_open(self.dialog)
        self.tour.start()

    def _finished(self, completed):
        QgsSettings().setValue(TOUR_SEEN_SETTING, True)
        self.marks.clear()
        if not completed and not self._had_ts_panel and _panel_open(self.dialog):
            self.dialog.ts_btn.setChecked(False)
            self.dialog._toggle_timeseries_panel(False)


def tour_seen():
    return QgsSettings().value(TOUR_SEEN_SETTING, False, type=bool)
