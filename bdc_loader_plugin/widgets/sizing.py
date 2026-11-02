"""
sizing.py

Size helpers for controls whose content changes at runtime.

A control that changes its text or appears and disappears must keep its size,
or the controls around it jump:

- ``fix_width_for_texts`` sizes a button once for the widest label it can show
  ("Tiles" / "Mosaics", "Cancel" / "Cancelling...");
- ``keep_space_when_hidden`` keeps the place of a widget that is shown only
  at times (a progress bar, a Cancel button);
- ``FixedLinesLabel`` is a message line whose height never follows its text.
"""

from qgis.PyQt.QtCore import QEvent, QObject, QRect, Qt
from qgis.PyQt.QtGui import QFont, QFontMetrics
from qgis.PyQt.QtWidgets import QLabel


def _with_translations(texts):
    """``texts`` and their Portuguese versions, so a widget fits the text of either language."""
    from ..i18n import both

    return [t for text in texts for t in both(text)]


def fix_width_for_texts(button, texts, extra=0):
    """Fix ``button`` width to fit the widest of ``texts`` in regular or bold weight.

    The style sheet font and padding are taken into account, so call this after
    ``setStyleSheet``. Returns the width that was set.
    """
    button.ensurePolished()
    texts = _with_translations(texts)
    regular = QFont(button.font())
    bold = QFont(regular)
    bold.setBold(True)
    widest = max(QFontMetrics(font).horizontalAdvance(text) for font in (regular, bold) for text in texts)
    current = button.text()
    padding = button.sizeHint().width() - QFontMetrics(regular).horizontalAdvance(current)
    width = widest + max(padding, 16) + extra
    button.setFixedWidth(width)
    return width


def fix_label_width_for_texts(label, texts, pixel_size, extra=4):
    """Fix a rich-text ``label`` width to its widest plain ``texts`` drawn at ``pixel_size`` px.

    For status labels whose text changes (a latency, online or offline), so the
    widgets around them never move. Returns the width that was set.
    """
    texts = _with_translations(texts)
    font = QFont(label.font())
    font.setPixelSize(pixel_size)
    bold = QFont(font)
    bold.setBold(True)
    width = max(QFontMetrics(f).horizontalAdvance(text) for f in (font, bold) for text in texts) + extra
    label.setFixedWidth(width)
    return width


def keep_space_when_hidden(widget):
    """Keep ``widget``'s place in its layout while it is hidden, so showing it moves nothing."""
    policy = widget.sizePolicy()
    policy.setRetainSizeWhenHidden(True)
    widget.setSizePolicy(policy)
    return widget


_ELLIPSIS = "\u2026"


def _looks_rich(text):
    return "<" in text and ">" in text


class FixedLinesLabel(QLabel):
    """Word-wrapped label exactly ``lines`` lines tall, whatever its text.

    Plain text that does not fit is cut at a word and ends with an ellipsis;
    ``text()`` and the tooltip keep the whole message. Rich text is shown as
    is, clipped to the same height. The label never asks for more width than
    it has, so a long message cannot widen the panel either.
    """

    def __init__(self, text="", lines=1, parent=None):
        super().__init__(parent)
        self._lines = max(1, int(lines))
        self._full_text = ""
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setMinimumWidth(1)
        self._fix_height()
        self.setText(text)

    def text(self):
        return self._full_text

    def setText(self, text):
        self._full_text = str(text or "")
        self._fit()

    def setStyleSheet(self, sheet):
        super().setStyleSheet(sheet)
        self._fix_height()
        self._fit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if event.oldSize().width() != event.size().width():
            self._fit()

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(1)
        return hint

    def sizeHint(self):
        hint = super().sizeHint()
        hint.setWidth(1)
        return hint

    def _text_height(self, metrics):
        return metrics.height() + (self._lines - 1) * metrics.lineSpacing()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._fix_height()
            self._fit()

    def _fix_height(self):
        self.ensurePolished()
        # Border and padding from the style sheet, plus the label margin.
        frame = self.height() - self.contentsRect().height() + 2 * self.margin()
        self.setFixedHeight(self._text_height(self.fontMetrics()) + max(0, frame))

    def _fits(self, metrics, width, text):
        flags = int(Qt.TextFlag.TextWordWrap)
        rect = metrics.boundingRect(QRect(0, 0, width, 100000), flags, text)
        return rect.height() <= self._text_height(metrics)

    def _fit(self):
        text = self._full_text
        shown = text
        width = self.contentsRect().width() - 2 * self.margin() - 2
        if text and width > 0 and not _looks_rich(text):
            metrics = self.fontMetrics()
            if not self._fits(metrics, width, text):
                words = text.split()
                while words and not self._fits(metrics, width, " ".join(words) + _ELLIPSIS):
                    words.pop()
                shown = (
                    " ".join(words) + _ELLIPSIS
                    if words
                    else metrics.elidedText(text, Qt.TextElideMode.ElideRight, width)
                )
        super().setText(shown)
        self.setToolTip(text if shown != text else "")


class _ScrollMinWidthKeeper(QObject):
    """Event filter that keeps a scroll area at least as wide as its content's minimum."""

    def __init__(self, scroll_area):
        super().__init__(scroll_area)
        self._scroll = scroll_area

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.LayoutRequest, QEvent.Type.Show):
            self.update()
        return False

    def update(self):
        content = self._scroll.widget()
        if content is None:
            return
        bar = self._scroll.verticalScrollBar().sizeHint().width()
        frame = 2 * self._scroll.frameWidth()
        self._scroll.setMinimumWidth(content.minimumSizeHint().width() + bar + frame)


def keep_scroll_min_width(scroll_area):
    """Stop ``scroll_area`` from becoming narrower than its content needs.

    The vertical scroll bar is always shown, so expanding a group never takes
    width from the content; horizontal scrolling is turned off, so a splitter
    or a small window cannot clip the content's right edge. The minimum follows
    the content when groups expand or collapse.
    """
    scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
    scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    keeper = _ScrollMinWidthKeeper(scroll_area)
    scroll_area.widget().installEventFilter(keeper)
    keeper.update()
    return keeper
