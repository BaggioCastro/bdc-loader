# -*- coding: utf-8 -*-
"""Result display widgets and helpers extracted from loader_dialog.py."""

import html
import os
import re
import tempfile
import webbrowser
from datetime import datetime

from qgis.PyQt.QtCore import QSize, Qt, QTimer, pyqtSignal
from qgis.PyQt.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ..core.gdal_env import uses_gdal
from ..i18n import language, set_text, translate_tree
from ..stac.parsers import cloud_cover, extract_tile_from_item, format_tile_display
from ..timing import THUMBNAIL_RETRY_MS
from ..widgets.icons import check_icon, download_icon
from .thumbnails import _fetch_thumbnail_bytes, _get_thumb_cache_path, _invoke_on_ui_thread, _thumb_executor, _ThumbJob

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_size(size_bytes):
    """Format bytes into human-readable size (B, KB, MB, GB)."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


# ---------------------------------------------------------------------------
# _ShapeMosaicItem
# ---------------------------------------------------------------------------


class _ShapeMosaicItem:
    """Lightweight result object representing one shape-based mosaic date."""

    def __init__(
        self,
        date_key,
        dt,
        source_items,
        feature_name=None,
        is_extent_crop=False,
        area=None,
        area_wkt=None,
        feature_fid=None,
        crop_bbox=None,
    ):
        """
        Args:
            area: area tag (core.download_outputs.area_tag), unique per geometry;
                it names the result and its downloaded files.
            area_wkt: the area in EPSG:4326, used as the cutline.
            feature_fid: id of the vector feature the mosaic covers, if any.
            crop_bbox: (xmin, ymin, xmax, ymax) in degrees of an extent crop.
        """
        self.feature_name = feature_name
        if area:
            self.id = f"{area}_{date_key}"
        else:
            safe_feat = re.sub(r"[^\w-]", "_", feature_name)[:40] if feature_name else None
            id_prefix = "crop" if is_extent_crop else "shape_mosaic"
            self.id = f"{id_prefix}_{safe_feat}_{date_key}" if safe_feat else f"{id_prefix}_{date_key}"
        self.datetime = dt
        self.assets = {}
        self._source_items = list(source_items)

        tiles = []
        for src_item in source_items:
            tile = extract_tile_from_item(src_item)
            if tile and tile != "NA" and tile not in tiles:
                tiles.append(tile)

        clouds = [c for c in (cloud_cover(src_item) for src_item in source_items) if c is not None]

        mean_cloud = (sum(clouds) / len(clouds)) if clouds else None

        start_values = []
        end_values = []
        for src_item in source_items:
            props = getattr(src_item, "properties", {}) or {}
            start_val = props.get("start_datetime") or props.get("datetime")
            end_val = props.get("end_datetime") or props.get("datetime")
            if start_val:
                start_values.append(start_val)
            if end_val:
                end_values.append(end_val)

        self.properties = {
            "datetime": dt.isoformat() if dt else date_key,
            "start_datetime": min(start_values) if start_values else None,
            "end_datetime": max(end_values) if end_values else None,
            "eo:cloud_cover": mean_cloud,
            "bdc:is_shape_mosaic": True,
            "bdc:is_extent_crop": is_extent_crop,
            "bdc:item_count": len(source_items),
            "bdc:tile_count": len(tiles),
            "bdc:tiles": tiles,
            "bdc:mosaic_date": date_key,
            "bdc:mosaic_label": "Extent Crop" if is_extent_crop else (feature_name or "Shape Mosaic"),
            "bdc:feature_name": feature_name,
            "bdc:area_tag": area,
            "bdc:area_wkt": area_wkt,
            "bdc:feature_fid": feature_fid,
            "bdc:crop_bbox": list(crop_bbox) if crop_bbox else None,
        }


# ---------------------------------------------------------------------------
# FilterRangeBar
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# TileFilterDialog
# ---------------------------------------------------------------------------


def _cloud_color(cloud):
    """Green under 10 %, orange under 30 %, red above."""
    return "#27ae60" if cloud < 10 else "#f39c12" if cloud < 30 else "#e74c3c"


def _count(n, word):
    """`n` followed by `word`, plural when `n` is not 1."""
    return f"{n} {word}{'s' if n != 1 else ''}"


def _tiles_preview(tiles, limit, more):
    """The first `limit` tiles joined by commas, followed by `more` when there are others."""
    preview = ", ".join(tiles[:limit])
    return preview + more if len(tiles) > limit else preview


def _info_label(text, style):
    """Frameless result card label."""
    label = QLabel(text)
    label.setStyleSheet(style)
    label.setFrameShape(QFrame.Shape.NoFrame)
    return label


# ---------------------------------------------------------------------------
# ResultItemWidget
# ---------------------------------------------------------------------------


class ResultItemWidget(QFrame):
    """Card that shows one search result."""

    selectionChanged = pyqtSignal(bool)

    # Pre-built stylesheets (class-level constants, shared by all instances)
    _STYLE_SELECTED = "ResultItemWidget { background-color: #e3f2fd; border: 2px solid #2196f3; border-radius: 4px; }"
    _STYLE_UNSELECTED = "ResultItemWidget { background-color: white; border: 1px solid #ddd; border-radius: 4px; }"
    _BROWSER_BTN_STYLE = (
        "QPushButton { background-color: #5b7fa5; color: white; border: none; border-radius: 4px; "
        "font-size: 9px; font-weight: bold; } "
        "QPushButton:hover { background-color: #4a6d8c; } "
        "QPushButton:pressed { background-color: #3a5a73; }"
    )
    _DOWNLOAD_BTN_STYLE = (
        "QPushButton { background-color: #27ae60; color: white; border: none; border-radius: 4px; "
        "font-size: 14px; font-weight: bold; } "
        "QPushButton:hover { background-color: #219a52; } "
        "QPushButton:pressed { background-color: #1a7a40; } "
        "QPushButton:disabled { background-color: #95a5a6; }"
    )
    _DOWNLOADED_BTN_STYLE = (
        "QPushButton { background-color: #95a5a6; color: white; border: none; border-radius: 4px; "
        "font-size: 14px; font-weight: bold; }"
    )

    def __init__(self, item, collection_id="", grid_type="", selected=True, compact=False, parent=None):
        super().__init__(parent)
        self.item = item
        self.collection_id = collection_id
        self.grid_type = grid_type
        self._selected = selected
        self._compact = compact
        self._thumbnail_loaded = False
        self._thumbnail_loading = False
        self._thumbnail_attempts = 0
        self._thumb_job = None  # the pending thumbnail/preview request, if any
        self._download_callback = None  # Set by parent dialog
        self._downloaded = False
        self._downloaded_badge = None
        self.setup_ui()
        if language() != "en":
            translate_tree(self)
        self.set_selected(selected)
        self.setCursor(Qt.CursorShape.PointingHandCursor)  # Pointing hand: the card is clickable

    def _is_shape_mosaic(self):
        """True only for a real shape-based mosaic, never an extent crop.

        The underlying bdc:is_shape_mosaic property is true for both, since
        it also marks which results need the merged-tile download/VRT path;
        this method narrows it to what the widget's labels/titles/thumbnails
        need — a check mutually exclusive with _is_extent_crop().
        """
        props = getattr(self.item, "properties", {}) or {}
        return bool(props.get("bdc:is_shape_mosaic")) and not bool(props.get("bdc:is_extent_crop"))

    def _is_extent_crop(self):
        return bool((getattr(self.item, "properties", {}) or {}).get("bdc:is_extent_crop"))

    def _is_any_mosaic(self):
        return self._is_shape_mosaic() or self._is_extent_crop()

    # Cached mosaic placeholder pixmaps (shared by all instances)
    _mosaic_placeholder_pm = None
    _crop_placeholder_pm = None

    def _set_mosaic_placeholder(self):
        if self.thumbnail_label is None:
            return
        is_crop = self._is_extent_crop()
        # Use cached pixmap if available
        cache_attr = "_crop_placeholder_pm" if is_crop else "_mosaic_placeholder_pm"
        cached = getattr(ResultItemWidget, cache_attr)
        if cached is not None:
            self.thumbnail_label.setPixmap(cached)
            self._thumbnail_loaded = True
            self._thumbnail_loading = False
            return
        pm = QPixmap(90, 90)
        pm.fill(QColor("#eef6ff") if not is_crop else QColor("#f0f4ff"))
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#d7ebff"))
        painter.drawRoundedRect(8, 10, 32, 24, 4, 4)
        painter.drawRoundedRect(26, 24, 32, 24, 4, 4)
        painter.drawRoundedRect(44, 14, 32, 24, 4, 4)
        painter.setPen(QPen(QColor("#155796"), 1))
        painter.drawText(0, 56, 90, 22, Qt.AlignmentFlag.AlignCenter, "CROP" if is_crop else "MOSAIC")
        painter.setPen(QPen(QColor("#4b5563"), 1))
        painter.drawText(0, 72, 90, 14, Qt.AlignmentFlag.AlignCenter, "extent crop" if is_crop else "shape mode")
        painter.end()
        setattr(ResultItemWidget, cache_attr, pm)
        self.thumbnail_label.setPixmap(pm)
        self._thumbnail_loaded = True
        self._thumbnail_loading = False

    def setup_ui(self):
        self.setFrameShape(QFrame.Shape.StyledPanel)

        if self._compact:
            self.setFixedHeight(36)
            self._setup_compact()
        else:
            self.setFixedHeight(110)
            self._setup_detailed()

    def _setup_compact(self):
        """Compact layout: checkbox + inline info + browser button."""
        layout = QHBoxLayout()
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(6)

        self.checkbox = QCheckBox()
        self.checkbox.setChecked(self._selected)
        self.checkbox.stateChanged.connect(self._on_checkbox_changed)
        layout.addWidget(self.checkbox)

        info_label = QLabel(self._compact_summary())
        info_label.setStyleSheet("font-size: 9px;")
        layout.addWidget(info_label, stretch=1)

        self._downloaded_badge = QLabel("LOCAL")
        self._downloaded_badge.setStyleSheet(
            "background-color: #27ae60; color: white; font-size: 8px; font-weight: bold; "
            "padding: 1px 5px; border-radius: 3px;"
        )
        self._downloaded_badge.setFixedHeight(16)
        self._downloaded_badge.hide()
        layout.addWidget(self._downloaded_badge)

        self._add_browser_button(layout)
        self._add_download_button(layout)

        self.thumbnail_label = None  # the compact card has no thumbnail
        self.setLayout(layout)

    def _compact_summary(self):
        """One-line rich text: kind or tile, date, counts and cloud cover."""
        props = self.item.properties
        date_str = self._get_date_str()
        cloud = cloud_cover(self.item)
        cloud_str = (
            f" | <span style='color:{_cloud_color(cloud)}'>Cloud: {cloud:.0f}%</span>" if cloud is not None else ""
        )

        if self._is_shape_mosaic():
            tile_count = props.get("bdc:tile_count", 0)
            tile_txt = f" | {_count(tile_count, 'tile')}" if tile_count else ""
            return (
                f"<b>Mosaic</b> | {date_str} | {_count(props.get('bdc:item_count', 0), 'scene')}{tile_txt}{cloud_str}"
            )
        if self._is_extent_crop():
            tiles = props.get("bdc:tiles", []) or []
            tile_txt = f"{_count(props.get('bdc:tile_count', 0), 'tile')}: {_tiles_preview(tiles, 3, '…')}"
            return f"<b>Crop</b> | {date_str} | {tile_txt}{cloud_str}"
        tile_display = format_tile_display(extract_tile_from_item(self.item), self.grid_type)
        return f"<b>{tile_display}</b> | {date_str}{cloud_str}"

    def _setup_detailed(self):
        """Detailed layout: checkbox + thumbnail + info + browser button."""
        layout = QHBoxLayout()
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(10)

        self.checkbox = QCheckBox()
        self.checkbox.setChecked(self._selected)
        self.checkbox.stateChanged.connect(self._on_checkbox_changed)
        layout.addWidget(self.checkbox)

        self.thumbnail_label = QLabel()
        self.thumbnail_label.setFixedSize(90, 90)
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ddd; border-radius: 4px;")
        self.thumbnail_label.setText("...")
        layout.addWidget(self.thumbnail_label)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(1)
        info_layout.setContentsMargins(0, 0, 0, 0)
        if self._is_shape_mosaic():
            self._add_mosaic_lines(info_layout)
        elif self._is_extent_crop():
            self._add_crop_lines(info_layout)
        else:
            self._add_scene_lines(info_layout)
        self._add_period_line(info_layout)
        self._add_cloud_line(info_layout)
        # A crop or feature mosaic has no STAC id, and its title and dates already
        # say what it is; that keeps room for the LOCAL badge after a download.
        if not self._is_any_mosaic():
            info_layout.addWidget(self._item_id_label())

        self._downloaded_badge = QLabel("LOCAL")
        self._downloaded_badge.setStyleSheet(
            "background-color: #27ae60; color: white; font-size: 8px; font-weight: bold; "
            "padding: 1px 6px; border-radius: 3px;"
        )
        self._downloaded_badge.setFixedHeight(15)
        self._downloaded_badge.hide()
        info_layout.addWidget(self._downloaded_badge)

        info_layout.addStretch()
        layout.addLayout(info_layout, stretch=1)

        self._add_browser_button(layout)
        self._add_download_button(layout)
        self.setLayout(layout)

    def _add_mosaic_lines(self, info_layout):
        """Feature mosaic: feature name, date, scene and tile counts, tile list."""
        props = self.item.properties
        title = props.get("bdc:feature_name") or "Shape Mosaic"
        info_layout.addWidget(_info_label(f"<b>{html.escape(str(title))}</b>", "font-size: 11px;"))
        info_layout.addWidget(_info_label(f"Date: {self._get_date_str()}", "font-size: 10px; color: #555;"))

        summary_parts = [_count(props.get("bdc:item_count", 0), "scene")]
        tile_count = props.get("bdc:tile_count", 0)
        if tile_count:
            summary_parts.append(_count(tile_count, "tile"))
        info_layout.addWidget(_info_label(f"Intersection: {' / '.join(summary_parts)}", "font-size: 9px; color: #444;"))

        tiles = props.get("bdc:tiles", []) or []
        if tiles:
            tiles_label = _info_label(f"Tiles: {_tiles_preview(tiles, 4, ', ...')}", "font-size: 8px; color: #666;")
            tiles_label.setToolTip(", ".join(tiles))
            info_layout.addWidget(tiles_label)

    def _add_crop_lines(self, info_layout):
        """Extent crop: title, date and the tiles it covers."""
        props = self.item.properties
        info_layout.addWidget(_info_label("<b>Extent Crop</b>", "font-size: 11px; color: #1565c0;"))
        info_layout.addWidget(_info_label(f"Date: {self._get_date_str()}", "font-size: 10px; color: #555;"))

        tiles = props.get("bdc:tiles", []) or []
        tiles_label = _info_label(
            f"Tiles ({props.get('bdc:tile_count', 0)}): {_tiles_preview(tiles, 4, ', ...')}",
            "font-size: 9px; color: #444;",
        )
        tiles_label.setToolTip(", ".join(tiles))
        info_layout.addWidget(tiles_label)

    def _add_scene_lines(self, info_layout):
        """Single scene: its tile and date."""
        tile_display = format_tile_display(extract_tile_from_item(self.item), self.grid_type)
        info_layout.addWidget(_info_label(f"<b>{tile_display}</b>", "font-size: 11px;"))
        info_layout.addWidget(_info_label(f"Date: {self._get_date_str()}", "font-size: 10px; color: #555;"))

    def _add_period_line(self, info_layout):
        """Composite period, shown when the item spans more than one day."""
        start_dt = self.item.properties.get("start_datetime")
        end_dt = self.item.properties.get("end_datetime")
        if not (start_dt and end_dt):
            return
        try:
            s_dt = datetime.fromisoformat(start_dt.replace("Z", "+00:00"))
            e_dt = datetime.fromisoformat(end_dt.replace("Z", "+00:00"))
            if s_dt.date() == e_dt.date():
                return
            period = f"Period: {s_dt.strftime('%d/%m')} - {e_dt.strftime('%d/%m/%Y')}"
        except (AttributeError, TypeError, ValueError):
            return
        info_layout.addWidget(_info_label(period, "font-size: 9px; color: #666;"))

    def _add_cloud_line(self, info_layout):
        """Cloud cover in green, orange or red; a mosaic shows the mean of its scenes."""
        cloud = cloud_cover(self.item)
        if cloud is None:
            return
        prefix = "Mean cloud" if self._is_any_mosaic() else "Cloud"
        text = f"{prefix}: <span style='color:{_cloud_color(cloud)}'>{cloud:.1f}%</span>"
        info_layout.addWidget(_info_label(text, "font-size: 10px; color: #555;"))

    def _item_id_label(self):
        """Selectable STAC item id with the collection in its tooltip."""
        id_label = QLabel(f"{self.item.id}")
        id_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        set_text(id_label, f"Collection: {self.collection_id}\nID: {self.item.id}", "tip")
        id_label.setStyleSheet("font-size: 8px; color: #888; font-style: italic;")
        id_label.setFrameShape(QFrame.Shape.NoFrame)
        return id_label

    def _add_browser_button(self, layout):
        """Add button to open in STAC Browser."""
        browser_btn = QPushButton("STAC")
        if self._compact:
            browser_btn.setFixedSize(40, 24)
        else:
            browser_btn.setFixedSize(40, 90)
        browser_btn.setToolTip(f"Open in STAC Browser\n{self.item.id}")
        browser_btn.setStyleSheet(self._BROWSER_BTN_STYLE)
        browser_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        browser_btn.clicked.connect(self._open_browser)
        layout.addWidget(browser_btn)

    def _open_browser(self):
        """Open item in STAC Browser."""
        if not self.collection_id:
            return

        if self._is_any_mosaic():
            source_items = getattr(self.item, "_source_items", [])
            if source_items:
                stac_browser_url = (
                    f"https://data.inpe.br/stac/browser/collections/{self.collection_id}/items/{source_items[0].id}"
                )
            else:
                stac_browser_url = f"https://data.inpe.br/stac/browser/collections/{self.collection_id}"
        else:
            stac_browser_url = (
                f"https://data.inpe.br/stac/browser/collections/{self.collection_id}/items/{self.item.id}"
            )

        webbrowser.open(stac_browser_url)

    def _add_download_button(self, layout):
        """Add COG download button."""
        self.download_btn = QPushButton()
        self.download_btn.setIcon(download_icon())
        self.download_btn.setIconSize(QSize(14, 14))
        if self._compact:
            self.download_btn.setFixedSize(28, 24)
        else:
            self.download_btn.setFixedSize(28, 90)
        self.download_btn.setToolTip("Download image to local disk")
        self.download_btn.setStyleSheet(self._DOWNLOAD_BTN_STYLE)
        self.download_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.download_btn.clicked.connect(self._on_download_clicked)
        layout.addWidget(self.download_btn)

    def _on_download_clicked(self):
        """Ask the parent dialog to download this item."""
        if self._download_callback:
            self._download_callback(self)

    def set_downloaded(self, downloaded=True):
        """Mark or unmark item as already downloaded."""
        self._downloaded = downloaded
        self.download_btn.setText("")
        if downloaded:
            self.download_btn.setIcon(check_icon())
            self.download_btn.setStyleSheet(self._DOWNLOADED_BTN_STYLE)
            set_text(self.download_btn, "Image already downloaded", "tip")
            self.download_btn.setEnabled(False)
            if self._downloaded_badge is not None:
                self._downloaded_badge.show()
        else:
            self.download_btn.setIcon(download_icon())
            self.download_btn.setStyleSheet(self._DOWNLOAD_BTN_STYLE)
            set_text(self.download_btn, "Download image to local disk", "tip")
            self.download_btn.setEnabled(True)
            if self._downloaded_badge is not None:
                self._downloaded_badge.hide()

    def set_download_busy(self, busy=True):
        """Show "..." while a download runs, and the download icon when it stops."""
        if busy:
            self.download_btn.setIcon(QIcon())
            self.download_btn.setText("...")
        else:
            self.download_btn.setText("")
            self.download_btn.setIcon(download_icon())

    def _get_date_str(self):
        if hasattr(self.item, "datetime") and self.item.datetime:
            return self.item.datetime.strftime("%d/%m/%Y")
        elif "datetime" in self.item.properties:
            try:
                dt = datetime.fromisoformat(self.item.properties["datetime"].replace("Z", "+00:00"))
                return dt.strftime("%d/%m/%Y")
            except (AttributeError, TypeError, ValueError):
                pass
        return "N/A"

    def _on_checkbox_changed(self, state):
        self._selected = state == Qt.CheckState.Checked
        self._update_style()
        self.selectionChanged.emit(self._selected)

    def set_selected(self, selected):
        self._selected = selected
        self.checkbox.setChecked(selected)
        self._update_style()

    def is_selected(self):
        return self._selected

    def _update_style(self):
        if self._selected:
            self.setStyleSheet(self._STYLE_SELECTED)
        else:
            self.setStyleSheet(self._STYLE_UNSELECTED)

    def mousePressEvent(self, event):
        """Allow selecting/deselecting by clicking anywhere on the card."""
        if event.button() == Qt.MouseButton.LeftButton:
            # A click on the checkbox is left to the checkbox
            checkbox_rect = self.checkbox.geometry()
            if not checkbox_rect.contains(event.pos()):
                self.set_selected(not self._selected)
        super().mousePressEvent(event)

    preview_bands = ()

    def _start_thumb_job(self):
        job = _ThumbJob()
        self._thumb_job = job
        return job

    def cancel_thumbnail(self):
        """Drop a thumbnail or preview still waiting or downloading for this card.

        Called when the card leaves the screen or the results are cleared, so
        the queue serves the cards on screen first; the card asks again when
        it comes back into view.
        """
        job, self._thumb_job = self._thumb_job, None
        if job is None:
            return
        job.wanted = False
        self._thumbnail_loading = False
        self._thumbnail_loaded = False

    @uses_gdal
    def _area_preview_request(self):
        """(cache path, render arguments) of this crop's preview, or None."""
        props = getattr(self.item, "properties", {}) or {}
        area_wkt = props.get("bdc:area_wkt")
        bbox = props.get("bdc:crop_bbox")
        if area_wkt:
            try:
                from osgeo import ogr

                xmin, xmax, ymin, ymax = ogr.CreateGeometryFromWkt(area_wkt).GetEnvelope()
                bbox = [xmin, ymin, xmax, ymax]
            except Exception:
                bbox = None
        bands = list(self.preview_bands or [])
        sources = list(getattr(self.item, "_source_items", []))
        if not bbox or not bands or not sources:
            return None
        from ..core.crop_preview import preview_key

        key = preview_key(self.item.id, self.collection_id, bands, area_wkt or bbox)
        cache_dir = os.path.join(tempfile.gettempdir(), "bdc_loader_thumbs")
        os.makedirs(cache_dir, exist_ok=True)
        return os.path.join(cache_dir, f"crop_{key}.png"), (sources, bands, bbox, area_wkt)

    def _show_preview_bytes(self, data):
        image = QImage()
        if not data or not image.loadFromData(data):
            return False
        canvas = QPixmap(90, 90)
        canvas.fill(QColor("#f0f0f0"))
        scaled = QPixmap.fromImage(image).scaled(
            86, 86, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        painter = QPainter(canvas)
        painter.drawPixmap((90 - scaled.width()) // 2, (90 - scaled.height()) // 2, scaled)
        painter.end()
        self.thumbnail_label.setPixmap(canvas)
        return True

    def _load_area_preview(self):
        """Replace the crop placeholder by a preview of the area (built in the background)."""
        request = self._area_preview_request()
        if request is None:
            return
        cache_path, args = request
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "rb") as f:
                    if self._show_preview_bytes(f.read()):
                        return
            except OSError:
                pass
        from qgis.PyQt import sip as _sip

        from ..core.crop_preview import render_preview

        widget_ref = self
        job = self._start_thumb_job()

        def _render():
            if not job.wanted:
                return
            try:
                data = render_preview(*args, cancel_check=lambda: not job.wanted)
            except Exception:
                data = None
            if not job.wanted:
                return
            if data:
                try:
                    with open(cache_path, "wb") as f:
                        f.write(data)
                except OSError:
                    pass

            def _apply():
                try:
                    if not job.wanted or _sip.isdeleted(widget_ref) or widget_ref.thumbnail_label is None:
                        return
                    widget_ref._thumb_job = None
                    if data:
                        widget_ref._show_preview_bytes(data)
                except (RuntimeError, ReferenceError):
                    pass

            _invoke_on_ui_thread(_apply)

        try:
            _thumb_executor.submit(_render)
        except RuntimeError:
            pass  # executor already shut down

    def load_thumbnail_if_needed(self):
        if self._thumbnail_loaded or self._thumbnail_loading or self.thumbnail_label is None:
            return
        if self._is_any_mosaic():
            self._set_mosaic_placeholder()
            self._load_area_preview()
            return
        thumbnail_url = None
        for key in ["thumbnail", "preview"]:
            if key in self.item.assets:
                thumbnail_url = self.item.assets[key].href
                break
        if not thumbnail_url:
            self._thumbnail_loaded = True
            self.thumbnail_label.setText("N/A")
            return
        # Look in the disk cache before queueing a download
        cache_path = _get_thumb_cache_path(thumbnail_url)
        if os.path.exists(cache_path):
            try:
                pm = QPixmap(cache_path)
                if not pm.isNull():
                    self._thumbnail_loaded = True
                    self.thumbnail_label.setPixmap(
                        pm.scaled(
                            90, 90, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                        )
                    )
                    return
            except Exception:
                pass
        # Queue the download in the thread pool
        from qgis.PyQt import sip as _sip

        self._thumbnail_loading = True
        self._thumbnail_attempts += 1
        self.thumbnail_label.setText("...")
        url = thumbnail_url
        widget_ref = self
        job = self._start_thumb_job()

        def _do_download():
            if not job.wanted:
                return
            data = _fetch_thumbnail_bytes(url)

            def _apply():
                try:
                    if not job.wanted or _sip.isdeleted(widget_ref) or widget_ref.thumbnail_label is None:
                        return
                    widget_ref._thumb_job = None
                    widget_ref._thumbnail_loading = False
                    if not data:
                        if widget_ref._thumbnail_attempts < 3 and widget_ref.isVisible():
                            widget_ref._thumbnail_loaded = False
                            QTimer.singleShot(
                                THUMBNAIL_RETRY_MS * widget_ref._thumbnail_attempts, widget_ref.load_thumbnail_if_needed
                            )
                        else:
                            widget_ref._thumbnail_loaded = True
                            widget_ref.thumbnail_label.setText("X")
                        return
                    image = QImage()
                    if image.loadFromData(data):
                        pm = QPixmap.fromImage(image).scaled(
                            90, 90, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                        )
                        widget_ref._thumbnail_loaded = True
                        widget_ref.thumbnail_label.setPixmap(pm)
                    else:
                        if widget_ref._thumbnail_attempts < 3 and widget_ref.isVisible():
                            widget_ref._thumbnail_loaded = False
                            QTimer.singleShot(
                                THUMBNAIL_RETRY_MS * widget_ref._thumbnail_attempts, widget_ref.load_thumbnail_if_needed
                            )
                        else:
                            widget_ref._thumbnail_loaded = True
                            widget_ref.thumbnail_label.setText("?")
                except (RuntimeError, ReferenceError):
                    pass

            _invoke_on_ui_thread(_apply)

        try:
            _thumb_executor.submit(_do_download)
        except RuntimeError:
            self._thumbnail_loading = False
            self._thumbnail_loaded = False
            pass  # the executor is already shut down
