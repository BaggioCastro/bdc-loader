"""Delays, in milliseconds, of the work the interface starts a moment later.

Each one lets Qt finish something first: paint a window, end the signal
handler that is running, or let QGIS place new layers in its tree.
"""

# After the main window opens: the window paints, then the STAC check, the
# disk usage check and the first-use tutorial start one after the other.
STARTUP_STAC_CHECK_MS = 500
STARTUP_STORAGE_CHECK_MS = 1000
STARTUP_TOUR_MS = 1500
# After the time series panel is built, its WTSS status check.
PANEL_WTSS_CHECK_MS = 800
# After the Settings dialog opens, its download and storage lists fill in.
SETTINGS_DOWNLOADS_LIST_MS = 200
SETTINGS_STORAGE_LIST_MS = 300

# A box drawn on the map: the map tool finishes handling the mouse release
# before the plugin switches back to Pan.
EXTENT_CAPTURE_SETTLE_MS = 120
# How long the outline of a typed bbox flashes on the map.
BBOX_FLASH_MS = 3000
# The result cards lay out before their thumbnails are asked for, so only
# the visible ones are.
THUMBNAILS_AFTER_LAYOUT_MS = 200
# A thumbnail that came back empty is asked again after this, times the attempt.
THUMBNAIL_RETRY_MS = 250

# A dialog offered from a signal handler opens after the handler returns.
AFTER_HANDLER_MS = 50
# The chart of a new entry paints before the bands it lacks are requested.
MISSING_BANDS_FETCH_MS = 200
# The STAC status repaints before the collection periods are fetched.
COLLECTION_PERIODS_MS = 100
# QGIS adds new layers to its tree before the points layer moves back on top.
POINTS_LAYER_TO_TOP_MS = 200
# The map settles on its new extent before the tutorial zooms to the example points.
TOUR_ZOOM_MS = 150

# How long a confirmation shows before the text or dialog goes back.
COPIED_LABEL_MS = 1600
STAC_RECOVERED_CLOSE_MS = 1500
