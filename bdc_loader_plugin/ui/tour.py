"""Guided tour: dims every window but the widget of the current step, with a callout beside it.

The dimming is a child widget laid over each window's own content, so it is
painted by Qt inside the window and needs no compositor. It stops clicks on
the shade and lets them through its holes, so only the highlighted widgets are
used during the tour. The callout is a frameless tool window kept on the
screen next to the target, or centred on the anchor window when a step has no
target.

A step can ask the user for an action (choose, click, draw on the map): its
``done`` check is polled, the Next button stays off until it passes, and the
tour moves on by itself once it does. When the plugin window steps aside for a
drag or a click on the map (Draw on Canvas, Select on Map), the callout goes to
the map with the step's map text and comes back with the window. Steps on the
map or on the panels of the QGIS window hide the anchor window, which comes
back before the next step inside it is prepared: a collapsible group opened
or closed while its window is hidden keeps its old look. Nothing in the
inspected windows moves or resizes.
"""

import math
from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Union

from qgis.PyQt.QtCore import QEvent, QObject, QPoint, QRect, QRectF, Qt, QTimer, pyqtSignal
from qgis.PyQt.QtGui import QColor, QCursor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QRegion
from qgis.PyQt.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..i18n import LANGUAGES, both, tr

_RING = QColor("#f59e0b")
_SCRIM = QColor(15, 23, 42, 170)
_GAP = 16
_HOLE_MARGIN = 6
_CALLOUT_WIDTH = 420
_TICK_MS = 50
_CHECK_EVERY = 2  # ticks between two done checks
_ADVANCE_MS = 1500

_WAITING = "Waiting for your action"
_DONE = "Done"

_ACCENT = "#0969da"
_BUTTON_PADDING = 16
_CALLOUT_STYLE = """
    QFrame#bdcTourCallout { background: #ffffff; border: 1px solid #cbd5e1; border-radius: 10px; }
    QLabel { background: transparent; border: none; }
    QLabel#bdcTourSection { color: #0969da; font-size: 11px; font-weight: 700; }
    QLabel#bdcTourCounter { color: #64748b; font-size: 11px; }
    QLabel#bdcTourTitle { color: #0f172a; font-size: 19px; font-weight: 600; }
    QLabel#bdcTourBody { color: #334155; font-size: 15px; }
    QFrame#bdcTourRule { background: #e2e8f0; border: none; }
    QPushButton {
        font-size: 13px; padding: 7px 16px; border-radius: 6px; min-width: 0;
        border: 1px solid #cbd5e1; background: #ffffff; color: #1e293b;
    }
    QPushButton:hover { background: #f1f5f9; }
    QPushButton:disabled { color: #94a3b8; border-color: #e2e8f0; }
    QPushButton#bdcTourPrimary { background: #0969da; color: #ffffff; border: 1px solid #0969da; font-weight: 600; }
    QPushButton#bdcTourPrimary:hover { background: #0757b8; }
    QPushButton#bdcTourPrimary:disabled { background: #a5c8f0; border-color: #a5c8f0; color: #ffffff; }
    QPushButton#bdcTourSkip { border: none; background: transparent; color: #64748b; padding: 7px 0; }
    QPushButton#bdcTourSkip:hover { color: #0f172a; }
"""
_STATUS_COLORS = {"wait": "#64748b", "fix": "#b45309", "done": "#15803d"}
_STATUS_MARKS = {"wait": "\u25cf", "fix": "\u25b2", "done": "\u2713"}


@dataclass
class TourStep:
    """One stop of the tour.

    ``target`` returns the widget to point at, a (widget, QRect) pair for a
    part of one (an item of an open list), or None to centre the callout on
    the anchor window; ``also`` returns more widgets left unshaded (the map
    while the step points at a button that picks on it). ``prepare`` runs
    before the step shows (fill a field, outline on the map where to click).
    ``done`` checks the action the step asks for: True when it is done, a text
    saying what to fix, or False while waiting; ``watch`` runs with each check,
    to answer what the user just did. ``map_body`` replaces
    ``body`` while the plugin window is out of the way for the user to work on
    the map, and the callout then points at ``map_view``. ``aside`` hides the
    anchor window for the whole step. ``body`` is a text or returns one.
    ``section`` names the part of the tour the step belongs to. Texts are in
    English and shown through ``tr``.
    """

    title: str
    body: Union[str, Callable[[], str]]
    section: str = ""
    target: Optional[Callable[[], Optional[QWidget]]] = None
    prepare: Optional[Callable[[], None]] = None
    done: Optional[Callable[[], Union[bool, str]]] = None
    map_body: str = ""
    aside: bool = False
    also: Optional[Callable[[], Iterable]] = None
    watch: Optional[Callable[[], None]] = None

    def text(self):
        return self.body() if callable(self.body) else self.body


class _Dimmer(QWidget):
    """Shades a whole window except its holes, around the first of which it draws a pulsing ring.

    The shade takes the clicks made on it; its mask leaves the holes out, so
    clicks there reach the widgets below.
    """

    def __init__(self, window: QWidget):
        super().__init__(window)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.holes = []
        self.ring = False
        self.phase = 0.0
        window.installEventFilter(self)
        self.setGeometry(window.rect())

    def eventFilter(self, obj, event):
        if obj is self.parentWidget():
            if event.type() == QEvent.Type.Resize:
                self.setGeometry(obj.rect())
                self._mask_holes()
            elif event.type() == QEvent.Type.ChildAdded and self.isVisible():
                # A dock or panel added later must stay under the shade.
                QTimer.singleShot(0, self.raise_)
        return False

    def cover(self, holes: List[QRect], ring: bool):
        self.holes, self.ring = holes, ring and bool(holes)
        self.setGeometry(self.parentWidget().rect())
        self._mask_holes()
        self.show()
        self.raise_()
        self.update()

    def _mask_holes(self):
        region = QRegion(self.rect())
        for hole in self.holes:
            region = region.subtracted(QRegion(_rounded(hole).toFillPolygon().toPolygon()))
        self.setMask(region)

    def _swallow(self, event):
        event.accept()

    mousePressEvent = mouseReleaseEvent = mouseDoubleClickEvent = wheelEvent = contextMenuEvent = _swallow

    def pulse(self, phase):
        self.phase = phase
        if self.ring:
            self.update(self.holes[0].adjusted(-16, -16, 16, 16))

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        shade = QPainterPath()
        shade.addRect(QRectF(self.rect()))
        for hole in self.holes:
            shade = shade.subtracted(_rounded(hole))
        painter.fillPath(shade, _SCRIM)
        if not self.ring:
            return
        # Just outside the hole, where the mask lets it be painted.
        ring = QRectF(self.holes[0]).adjusted(-2, -2, 2, 2)
        glow = QColor(_RING)
        glow.setAlpha(int(40 + 90 * (1 - self.phase)))
        spread = 3 + 9 * self.phase
        painter.setPen(QPen(glow, 3))
        painter.drawRoundedRect(ring.adjusted(-spread, -spread, spread, spread), 12, 12)
        painter.setPen(QPen(_RING, 3))
        painter.drawRoundedRect(ring, 10, 10)


def _rounded(hole: QRect) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(QRectF(hole), 10, 10)
    return path


class _Progress(QWidget):
    """A thin bar filled up to the current step."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fraction = 0.0
        self.setFixedHeight(4)

    def set_position(self, index, count):
        self.fraction = (index + 1) / max(count, 1)
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        track = QRectF(self.rect())
        painter.setBrush(QColor("#e2e8f0"))
        painter.drawRoundedRect(track, 2, 2)
        painter.setBrush(QColor(_ACCENT))
        painter.drawRoundedRect(QRectF(0, 0, track.width() * self.fraction, track.height()), 2, 2)


class _Callout(QFrame):
    """Section and step count, a progress bar, title, text, a status line, and Skip / Back / Next."""

    def __init__(self):
        # No parent: the callout must stay visible while the plugin window is hidden.
        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.setObjectName("bdcTourCallout")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setStyleSheet(_CALLOUT_STYLE)
        self.setFixedWidth(_CALLOUT_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 16)
        layout.setSpacing(10)
        top = QHBoxLayout()
        self.section = QLabel()
        self.section.setObjectName("bdcTourSection")
        font = self.section.font()
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
        self.section.setFont(font)
        self.counter = QLabel()
        self.counter.setObjectName("bdcTourCounter")
        top.addWidget(self.section, 1)
        top.addWidget(self.counter)
        layout.addLayout(top)
        self.progress = _Progress()
        layout.addWidget(self.progress)
        layout.addSpacing(4)
        self.title = QLabel()
        self.title.setObjectName("bdcTourTitle")
        self.title.setWordWrap(True)
        self.body = QLabel()
        self.body.setObjectName("bdcTourBody")
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.TextFormat.RichText)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setFixedHeight(36)
        layout.addWidget(self.title)
        layout.addWidget(self.body)
        layout.addStretch()
        layout.addWidget(self.status)
        rule = QFrame()
        rule.setObjectName("bdcTourRule")
        rule.setFixedHeight(1)
        layout.addWidget(rule)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.skip_btn = QPushButton()
        self.skip_btn.setObjectName("bdcTourSkip")
        self.back_btn = QPushButton()
        self.next_btn = QPushButton()
        self.next_btn.setObjectName("bdcTourPrimary")
        for btn in (self.skip_btn, self.back_btn, self.next_btn):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        buttons.addWidget(self.skip_btn)
        buttons.addStretch()
        buttons.addWidget(self.back_btn)
        buttons.addWidget(self.next_btn)
        layout.addLayout(buttons)

    def size_for(self, steps: List[TourStep]):
        """Fix the height and the button widths to the largest step in either language,
        so nothing moves between steps or after a language switch."""
        self.next_btn.ensurePolished()
        bold = QFont(self.next_btn.font())
        bold.setBold(True)
        words = [t for word in ("Start", "Next", "Finish") for t in both(word)]
        self.next_btn.setFixedWidth(
            max(QFontMetrics(bold).horizontalAdvance(w) for w in words) + 2 * _BUTTON_PADDING + 4
        )
        height = 0
        for lang in LANGUAGES:
            for i, step in enumerate(steps):
                self.fill(step, i, len(steps), lang)
                for text in (step.text(), step.map_body):
                    self.body.setText(tr(text, lang))
                    height = max(height, self.layout().totalHeightForWidth(_CALLOUT_WIDTH))
        self.setFixedHeight(height)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, _CALLOUT_WIDTH, height), 10, 10)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def fill(self, step: TourStep, index: int, count: int, lang=None):
        self.progress.set_position(index, count)
        self.section.setText(tr(step.section, lang).upper())
        self.counter.setText(tr("Step {} of {}", lang).format(index + 1, count))
        self.title.setText(tr(step.title, lang))
        self.body.setText(tr(step.text(), lang))
        self.back_btn.setVisible(index > 0)
        self.back_btn.setText(tr("Back", lang))
        self.skip_btn.setText(tr("Skip tutorial", lang))
        word = "Start" if index == 0 else "Finish" if index == count - 1 else "Next"
        self.next_btn.setText(tr(word, lang))
        self.show_state(None, lang)

    def show_state(self, state, lang=None):
        """None: nothing to do; True: done; a text: what to fix; anything else: waiting."""
        if state is None or state is True:
            kind, text = ("done", _DONE) if state is True else ("wait", "")
        elif isinstance(state, str):
            kind, text = "fix", state
        else:
            kind, text = "wait", _WAITING
        self.next_btn.setEnabled(state is None or state is True)
        self.status.setStyleSheet(f"color: {_STATUS_COLORS[kind]}; font-size: 13px;")
        self.status.setText(f"{_STATUS_MARKS[kind]}  {tr(text, lang)}" if text else "")


def _screen_rect(widget: QWidget, part: Optional[QRect] = None) -> QRect:
    part = part or widget.rect()
    return QRect(widget.mapToGlobal(part.topLeft()), part.size())


def _available_geometry(point: QPoint) -> QRect:
    screen = QApplication.screenAt(point) or QApplication.primaryScreen()
    return screen.availableGeometry()


def _overlaps(a, b):
    """Whether two (x, y, w, h) rectangles share any pixel."""
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def _inside(a, area):
    return area[0] <= a[0] and area[1] <= a[1] and a[0] + a[2] <= area[0] + area[2] and a[1] + a[3] <= area[1] + area[3]


def callout_position(target, size, area, avoid=()):
    """Top-left (x, y) of a callout of ``size`` (w, h) beside ``target``, kept inside ``area``.

    Rectangles are (x, y, w, h). Tries right, left, below and above the
    target and takes the first side with room, sliding along that side to stay
    in the area; a side that also keeps clear of every ``avoid`` rectangle (the
    other widgets the step leaves unshaded) wins over one that does not. A
    target too large for any side (the map) gets the callout in its lower
    right corner.
    """
    tx, ty, tw, th = target
    w, h = size
    ax, ay, aw, ah = area
    candidates = (
        (tx + tw + _GAP, ty),
        (tx - _GAP - w, ty),
        (tx, ty + th + _GAP),
        (tx, ty - _GAP - h),
    )
    fits = []
    for side, (x, y) in enumerate(candidates):
        if side < 2:  # beside the target: slide up or down
            y = min(max(y, ay), ay + ah - h)
        else:  # below or above: slide left or right
            x = min(max(x, ax), ax + aw - w)
        box = (x, y, w, h)
        if _inside(box, area) and not _overlaps(box, target):
            fits.append((x, y))
            if not any(_overlaps(box, other) for other in avoid):
                return x, y
    if fits:
        return fits[0]
    x, y = tx + tw - w - _GAP, ty + th - h - _GAP
    return min(max(x, ax), ax + aw - w), min(max(y, ay), ay + ah - h)


def _shown(widget):
    return widget is not None and widget.isVisible() and not widget.window().isMinimized()


class GuidedTour(QObject):
    """Shows ``steps`` one at a time; emits ``finished(completed)`` when it ends or is skipped.

    ``windows`` returns the windows to dim besides the anchor's and the
    target's (the QGIS main window, for a tour started from a dialog);
    ``map_view`` returns the widget a step's ``map_body`` points at.
    """

    finished = pyqtSignal(bool)

    def __init__(
        self,
        steps: List[TourStep],
        anchor: QWidget,
        windows: Optional[Callable[[], Iterable]] = None,
        map_view: Optional[Callable[[], Optional[QWidget]]] = None,
    ):
        super().__init__(anchor)
        self.steps = steps
        self.anchor = anchor
        self.index = -1
        self._windows = windows or (lambda: ())
        self._map_view = map_view or (lambda: None)
        self._dimmers = {}
        self._anchor_hidden = False
        self._placed = None
        self._scrolled = None
        self._was_done = False
        self._lit = None
        self._callout = _Callout()
        self._callout.size_for(steps)
        anchor.destroyed.connect(self._callout.deleteLater)
        self._callout.next_btn.clicked.connect(self._on_next)
        self._callout.back_btn.clicked.connect(self.back)
        self._callout.skip_btn.clicked.connect(lambda: self.stop(completed=False))
        self._tick = QTimer(self)
        self._tick.setInterval(_TICK_MS)
        self._tick.timeout.connect(self._on_tick)
        self._ticks = 0
        self._advance = QTimer(self)
        self._advance.setSingleShot(True)
        self._advance.setInterval(_ADVANCE_MS)
        self._advance.timeout.connect(self._advance_if_done)

    @property
    def running(self):
        return self.index >= 0

    def _step(self):
        return self.steps[self.index] if self.running else None

    def start(self, index=0):
        self._tick.start()
        self.show_step(index)

    def next(self):
        if self.index + 1 >= len(self.steps):
            self.stop(completed=True)
        else:
            self.show_step(self.index + 1)

    def back(self):
        if self.index > 0:
            self.show_step(self.index - 1)

    def stop(self, completed=False):
        if not self.running:
            return
        self.index = -1
        self._tick.stop()
        self._advance.stop()
        for dimmer in self._dimmers.values():
            dimmer.hide()
        self._callout.hide()
        self._light(None)
        self._set_aside(False)
        self.finished.emit(completed)

    def refresh(self):
        """Show the current step again, in the interface language just chosen."""
        step = self._step()
        if step is None:
            return
        self._callout.fill(step, self.index, len(self.steps))
        self._callout.show_state(self._state(step))
        self._place()

    def show_step(self, index):
        self._advance.stop()
        self.index = index
        step = self.steps[index]
        if not step.aside:
            self._set_aside(False)
        if step.prepare:
            step.prepare()
        if not self.running:  # prepare may stop the tour
            return
        self._callout.fill(step, index, len(self.steps))
        state = self._state(step)
        self._was_done = state is True
        self._callout.show_state(state)
        self._placed = None
        # Panels opened by prepare get their geometry on the next event loop turn.
        QTimer.singleShot(0, self._place)

    @staticmethod
    def _state(step):
        if step.done is None:
            return None
        try:
            return step.done()
        except Exception:  # a widget the check reads is gone: still waiting
            return False

    def _on_next(self):
        step = self._step()
        if step is not None and self._state(step) in (None, True):
            self.next()

    def _check_done(self):
        step = self._step()
        if step is not None and step.watch is not None:
            step.watch()
        if step is None or step.done is None:
            return
        state = self._state(step)
        self._callout.show_state(state)
        if state is True and not self._was_done:
            self._advance.start()
        elif state is not True:
            self._advance.stop()
        self._was_done = state is True

    def _advance_if_done(self):
        step = self._step()
        if step is not None and self._state(step) is True:
            self.next()

    def _on_tick(self):
        self._ticks += 1
        phase = (math.sin(self._ticks * _TICK_MS / 1000 * math.pi) + 1) / 2
        for dimmer in self._dimmers.values():
            if dimmer.isVisible():
                dimmer.pulse(phase)
        if self._ticks % _CHECK_EVERY == 0:
            self._check_done()
            self._keep_target_in_front()
            step = self._step()
            if step is not None:
                self._light(self._target(step)[0])
        if self.running and self._layout_key() != self._placed:
            self._place()

    def _light(self, widget):
        """Draw the ringed button as if the pointer were on it, so it stands out before the user reaches it.

        Qt styles draw the hover look from the widget's under-mouse flag; the
        tour sets it on the ringed button and gives the previous one back the
        flag the pointer gives it.
        """
        if not isinstance(widget, (QAbstractButton, QComboBox)) or not _shown(widget):
            widget = None
        previous, self._lit = self._lit, widget
        try:
            if previous is not None and previous is not widget:
                under = previous.rect().contains(previous.mapFromGlobal(QCursor.pos()))
                previous.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, under)
                previous.update()
            if widget is not None and not widget.testAttribute(Qt.WidgetAttribute.WA_UnderMouse):
                widget.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
                widget.update()
        except RuntimeError:  # the button was deleted with its card or dialog
            self._lit = None

    def _keep_target_in_front(self):
        """Bring the target's window back in front when another window of QGIS took its place.

        A click on the shade of the QGIS window still makes the window manager
        raise that window over the plugin window. Nothing is done while a
        dialog or a list is open, or while another program is in front.
        """
        step = self._step()
        if step is None or QApplication.activeModalWidget() or QApplication.activePopupWidget():
            return
        target, _part, _text = self._target(step)
        if not _shown(target):
            return
        window, active = target.window(), QApplication.activeWindow()
        if active is None or active is window or active is self._callout:
            return
        window.raise_()
        window.activateWindow()
        self._callout.raise_()

    def _anchor_away(self):
        """The plugin window stepped aside by itself, for the user to work on the map."""
        window = self.anchor.window()
        return not self._anchor_hidden and not _shown(window)

    def _target(self, step):
        """The widget to point at, the part of it (None for all of it) and the text to show.

        They follow the plugin window: while it is out of the way, a step with
        a map text points at the map.
        """
        if step.map_body and self._anchor_away():
            return self._map_view(), None, step.map_body
        target = step.target() if step.target else None
        widget, part = target if isinstance(target, tuple) else (target, None)
        return widget, part, step.text()

    def _layout_key(self):
        """What the callout and the shade depend on; the tour redraws them when it changes."""
        step = self._step()
        if step is None:
            return None
        target, part, _text = self._target(step)
        rect = _screen_rect(target, part).getRect() if _shown(target) else None
        modal = QApplication.activeModalWidget()
        return self.index, id(target), rect, _shown(self.anchor.window()), id(modal) if modal else None

    def _set_aside(self, aside):
        """Hide the anchor window, or bring back the one the tour hid.

        The window's own state is checked, not only the tour's, because the
        plugin can show its window again by itself (after loading a grid).
        """
        window = self.anchor.window()
        if aside:
            if _shown(window):
                self._anchor_hidden = True
                window.hide()
        elif self._anchor_hidden:
            # As the plugin brings itself back after Draw on Canvas: without
            # activating it, a window manager can keep it behind QGIS.
            self._anchor_hidden = False
            if not window.isVisible():
                window.show()
            window.raise_()
            window.activateWindow()

    def _dimmer(self, window):
        dimmer = self._dimmers.get(window)
        if dimmer is None:
            dimmer = _Dimmer(window)
            self._dimmers[window] = dimmer
            window.destroyed.connect(lambda *_a, w=window: self._dimmers.pop(w, None))
        return dimmer

    def _place(self):
        step = self._step()
        if step is None:
            return
        self._set_aside(step.aside)
        target, part, text = self._target(step)
        self._callout.body.setText(tr(text))
        visible = _shown(target)
        if visible and self._scrolled != (self.index, id(target)):
            # Once per step and target, so the user can still scroll away.
            self._scrolled = (self.index, id(target))
            _scroll_into_view(target)
        holes = {}
        if visible:
            holes[target.window()] = [_hole(target, part)]
        for widget in step.also() if step.also else ():
            if _shown(widget):
                holes.setdefault(widget.window(), []).append(_hole(widget))
        windows = [self.anchor.window(), *[w for w in self._windows() if w is not None], *holes]
        covered = set()
        for window in dict.fromkeys(windows):
            if not _shown(window):
                continue
            ring = visible and window is target.window()
            self._dimmer(window).cover(holes.get(window, []), ring)
            covered.add(window)
        for window, dimmer in self._dimmers.items():
            if window not in covered:
                dimmer.hide()
        others = [_screen_rect(w).getRect() for w in (step.also() if step.also else ()) if _shown(w)]
        self._move_callout(target if visible else None, part, others)
        self._placed = self._layout_key()

    def _move_callout(self, target, part=None, avoid=()):
        size = self._callout.size()
        modal = QApplication.activeModalWidget()
        if modal is not None and modal is not self._callout and modal.isVisible():
            # A dialog the step opened (the grid offer) must stay readable.
            target, part = modal, None
        if target is not None:
            rect = _screen_rect(target, part)
            area = _available_geometry(rect.center())
            x, y = callout_position(rect.getRect(), (size.width(), size.height()), area.getRect(), avoid)
            self._callout.move(x, y)
        else:
            windows = [self.anchor.window(), *[w for w in self._windows() if w is not None]]
            window = next((w for w in windows if _shown(w)), self.anchor.window())
            self._callout.move(_screen_rect(window).center() - QPoint(size.width() // 2, size.height() // 2))
        self._callout.show()
        self._callout.raise_()

    def delete(self):
        """Stop and remove everything the tour added to other windows."""
        self.stop(completed=False)
        for dimmer in self._dimmers.values():
            dimmer.deleteLater()
        self._dimmers.clear()
        self._callout.deleteLater()


def _hole(widget: QWidget, part: Optional[QRect] = None) -> QRect:
    """``part`` of ``widget`` (all of it by default) in its window, with a margin, kept inside the window."""
    window = widget.window()
    part = part or widget.rect()
    top_left = widget.mapTo(window, part.topLeft())
    hole = QRect(top_left, part.size()).adjusted(-_HOLE_MARGIN, -_HOLE_MARGIN, _HOLE_MARGIN, _HOLE_MARGIN)
    return hole.intersected(window.rect().adjusted(3, 3, -3, -3))


def _scroll_into_view(widget: QWidget):
    """Scroll every scroll area that contains ``widget`` so it is visible."""
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QScrollArea) and parent.widget() is not None and parent.widget().isAncestorOf(widget):
            parent.ensureWidgetVisible(widget, 20, 20)
        parent = parent.parentWidget()
