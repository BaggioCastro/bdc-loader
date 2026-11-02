"""The cursor says what a press does, the same way in every window of the plugin.

  - pointing hand: a single click acts here (buttons, check boxes, radio
    buttons, combo boxes, the arrows of number and date boxes, the arrow and
    title of a collapsible group, the track of a slider);
  - open hand over a handle that can be dragged, closed hand while dragging
    (set by the sliders themselves);
  - the default cursor over anything disabled, and the text cursor over the
    text of a box, which keeps its own.

A widget that sets its own cursor keeps it. ``watch(widget)`` applies the rule
to the widget, to the windows opened over it, and to what they hold when they
show.
"""

from qgis.PyQt.QtCore import QEvent, QObject, Qt
from qgis.PyQt.QtWidgets import QAbstractButton, QAbstractSpinBox, QComboBox, QToolButton, QWidget

from .group_title import hand_cursor_on_title

_HAND = Qt.CursorShape.PointingHandCursor
_MANAGED = "bdc_click_cursor"
# Number and date boxes get the hand on the whole box; their text field, a
# child that keeps the text cursor, leaves the hand on the arrows only.
_CLICKABLE = tuple(cls for cls in (QAbstractButton, QComboBox, QAbstractSpinBox) if isinstance(cls, type))


def _sync(widget):
    if widget.isEnabled():
        widget.setCursor(_HAND)
    else:
        widget.unsetCursor()


class _EnabledFilter(QObject):
    """Drops the hand while a managed widget is disabled and gives it back after."""

    def eventFilter(self, widget, event):
        if event.type() == QEvent.Type.EnabledChange and widget.property(_MANAGED):
            _sync(widget)
        return False


def _is_collapsible_group(widget):
    return hasattr(widget, "titleRect") and widget.findChild(QToolButton, "collapseButton") is not None


def apply_click_cursors(root):
    """Give ``root`` and the widgets inside it the cursor of what a press does there."""
    if root is None:
        return
    for widget in [root, *root.findChildren(QWidget)]:
        if _is_collapsible_group(widget) and not widget.property("bdc_title_cursor"):
            widget.setProperty("bdc_title_cursor", True)
            hand_cursor_on_title(widget)
        if not isinstance(widget, _CLICKABLE) or widget.property(_MANAGED):
            continue
        if widget.objectName() == "collapseButton":
            continue  # the group's arrow follows the group
        if widget.testAttribute(Qt.WidgetAttribute.WA_SetCursor) and widget.cursor().shape() != _HAND:
            continue  # its own cursor
        widget.setProperty(_MANAGED, True)
        widget.installEventFilter(_FILTER)
        _sync(widget)


class _WindowWatcher(QObject):
    """Applies the rule to the watched widgets and to every window that shows over them."""

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QEvent.Type.ChildAdded:
            child = event.child()
            if child is not None and child.isWidgetType() and child.isWindow():
                child.installEventFilter(self)
        elif kind == QEvent.Type.Show and obj.isWidgetType() and obj.isWindow():
            apply_click_cursors(obj)
        return False


_FILTER = _EnabledFilter()
_WATCHER = _WindowWatcher()


def watch(widget):
    """Apply the rule to ``widget`` now and to the windows opened over it later."""
    if widget is None:
        return
    apply_click_cursors(widget)
    widget.installEventFilter(_WATCHER)
