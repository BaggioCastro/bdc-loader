# -*- coding: utf-8 -*-
"""Collection list badge marking which collections are cloud-optimized.

A COG streams from its internal overview pyramid, so QGIS draws it from a few
hundred KB. A plain GeoTIFF has no pyramid, so the same draw pulls whole scenes
over the network. The badge puts that difference where the collection is picked
instead of leaving it to be discovered after a slow load.
"""

from qgis.PyQt.QtCore import QRectF, Qt
from qgis.PyQt.QtGui import QColor, QFont, QFontMetrics, QPainter
from qgis.PyQt.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem

# Role holding "COG" / "GEOTIFF", or None when format is unknown
BADGE_ROLE = Qt.ItemDataRole.UserRole + 100
# Role holding "CUBE" / "MOSAIC" / "SCENE" category badge
TYPE_BADGE_ROLE = Qt.ItemDataRole.UserRole + 101
# Role holding "GRID" / "NO GRID" tile system badge
GRID_BADGE_ROLE = Qt.ItemDataRole.UserRole + 102

COG_BADGE = "COG"
GEOTIFF_BADGE = "GEOTIFF"
GRID_BADGE = "GRID"
NO_GRID_BADGE = "NO GRID"

# (background, foreground)
_BADGE_STYLES = {
    COG_BADGE: ("#1e8449", "#ffffff"),
    GEOTIFF_BADGE: ("#b9770e", "#ffffff"),
    "CUBE": ("#2980b9", "#ffffff"),
    "MOSAIC": ("#6c3483", "#ffffff"),
    "SCENE": ("#5d6d7e", "#ffffff"),
    "COLL": ("#5d6d7e", "#ffffff"),
    GRID_BADGE: ("#0e6251", "#ffffff"),
    NO_GRID_BADGE: ("#707b7c", "#ffffff"),
}
_BADGE_TOOLTIPS = {
    COG_BADGE: "Cloud-optimized: reads fast over the network.",
    GEOTIFF_BADGE: "Plain GeoTIFF: rendering streams whole scenes — prefer Download.",
    GRID_BADGE: "Grid system: uses BDC/MGRS tile grid navigation.",
    NO_GRID_BADGE: "No grid system: scene extent query only.",
}

_PADDING_X = 3
_GAP = 3
_RADIUS = 2
_TEXT_MARGIN = 2


def badge_for_collection(config):
    """Return the raster format badge text ('COG'/'GEOTIFF') for a collection config."""
    flag = config.get("cloud_optimized")
    if flag is None:
        return None
    return COG_BADGE if flag else GEOTIFF_BADGE


def type_badge_for_collection(config):
    """Return category badge ('CUBE', 'MOSAIC', 'SCENE') for a collection config."""
    ctype = str(config.get("type") or config.get("bdc:type") or "collection").lower()
    if ctype == "cube":
        return "CUBE"
    if ctype == "mosaic":
        return "MOSAIC"
    return "SCENE"


def grid_badge_for_collection(config):
    """Return tile system badge ('NO GRID') for collections without a tile grid, or None."""
    if config.get("has_tiles") is False:
        return NO_GRID_BADGE
    grid = config.get("grid") or config.get("bdc:grs")
    if not grid or str(grid).strip() in ("", "-"):
        return NO_GRID_BADGE
    return None


def badge_font(base_font):
    """Return the small bold font the badge text is drawn with."""
    font = QFont(base_font)
    font.setBold(True)
    size = base_font.pointSize()
    # pointSize() is -1 when the font was defined in pixels; fall back to a
    # literal so the badge never inherits the full-size text height.
    font.setPointSize(max(5, int(size * 0.65)) if size > 0 else 6)
    return font


def badge_width(base_font, badge):
    """Return the pixel width the badge pill occupies, gaps included."""
    metrics = QFontMetrics(badge_font(base_font))
    return metrics.horizontalAdvance(badge) + 2 * _PADDING_X + 2 * _GAP


def _strip_type_prefix(text):
    """``text`` without the [CUBE], [MOSAIC] and [COLLECTION] prefixes the type badge replaces."""
    for prefix in ("[CUBE] ", "[MOSAIC] ", "[COLLECTION] "):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    return text


def _pill_width(metrics, badge):
    return metrics.horizontalAdvance(badge) + 2 * _PADDING_X


def _draw_pill(painter, font, metrics, x, rect, badge):
    """Draw ``badge`` as a rounded pill at ``x``, centered vertically in ``rect``; return its width."""
    width = _pill_width(metrics, badge)
    height = metrics.height()
    pill = QRectF(x, rect.top() + (rect.height() - height) / 2.0, width, height)
    bg, fg = _BADGE_STYLES[badge]
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(bg))
    painter.drawRoundedRect(pill, _RADIUS, _RADIUS)
    painter.setFont(font)
    painter.setPen(QColor(fg))
    painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, badge)
    return width


class CollectionBadgeDelegate(QStyledItemDelegate):
    """Draws styled pill badges before and after the collection name in combo lists.

    Badges rendered:
    - Leading: Category pill (CUBE / MOSAIC / SCENE) replacing text bracket prefixes
    - Trailing 1: Raster format pill (COG / GEOTIFF)
    - Trailing 2: Tile system pill (GRID / NO GRID)
    """

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)

        format_badge = index.data(BADGE_ROLE)
        type_badge = index.data(TYPE_BADGE_ROLE)
        grid_badge = index.data(GRID_BADGE_ROLE)

        text = opt.text
        if not format_badge and not type_badge and not grid_badge:
            super().paint(painter, option, index)
            return

        clean_text = _strip_type_prefix(text)

        opt.text = ""
        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)

        font = badge_font(opt.font)
        metrics = QFontMetrics(font)
        text_metrics = QFontMetrics(opt.font)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        text_rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, opt.widget)
        if text_rect.isValid() and text_rect.width() > 0:
            rect = text_rect.adjusted(_TEXT_MARGIN, 0, -_TEXT_MARGIN, 0)
        else:
            rect = opt.rect.adjusted(_TEXT_MARGIN, 0, -_TEXT_MARGIN, 0)
        curr_x = rect.left()

        if type_badge in _BADGE_STYLES:
            curr_x += _draw_pill(painter, font, metrics, curr_x, rect, type_badge) + _GAP
        trailing = [badge for badge in (format_badge, grid_badge) if badge in _BADGE_STYLES]
        trailing_width = sum(_pill_width(metrics, badge) + _GAP for badge in trailing)

        painter.setFont(opt.font)
        painter.setPen(
            opt.palette.highlightedText().color()
            if opt.state & QStyle.StateFlag.State_Selected
            else opt.palette.text().color()
        )
        avail_for_text = rect.right() - curr_x - trailing_width
        shown = text_metrics.elidedText(clean_text, Qt.TextElideMode.ElideRight, max(0, avail_for_text))
        text_rect = QRectF(curr_x, rect.top(), text_metrics.horizontalAdvance(shown), rect.height())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, shown)
        curr_x += text_metrics.horizontalAdvance(shown) + _GAP

        for badge in trailing:
            curr_x += _draw_pill(painter, font, metrics, curr_x, rect, badge) + _GAP

        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        format_badge = index.data(BADGE_ROLE)
        type_badge = index.data(TYPE_BADGE_ROLE)
        grid_badge = index.data(GRID_BADGE_ROLE)

        extra = 0
        font = option.font
        if type_badge in _BADGE_STYLES:
            extra += badge_width(font, type_badge)
        if format_badge in _BADGE_STYLES:
            extra += badge_width(font, format_badge)
        if grid_badge in _BADGE_STYLES:
            extra += badge_width(font, grid_badge)

        if extra > 0:
            size.setWidth(size.width() + extra)
        return size
