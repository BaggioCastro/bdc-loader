"""
group_title.py

A pointing-hand cursor over the parts of a collapsible group that open and
close it: its arrow and its title. Elsewhere in the group, and while the group
is locked (disabled), the cursor stays the default one.
"""

from qgis.PyQt.QtCore import QEvent, QObject, Qt
from qgis.PyQt.QtWidgets import QToolButton

_HAND = Qt.CursorShape.PointingHandCursor


def _event_pos(event):
    return event.position().toPoint() if hasattr(event, "position") else event.pos()


def over_title(group, pos):
    """Whether ``pos`` (group coordinates) is on the title QGIS toggles the group from."""
    return group.isEnabled() and group.titleRect().contains(pos)


class _TitleCursor(QObject):
    def __init__(self, group):
        super().__init__(group)
        self._arrow = group.findChild(QToolButton, "collapseButton")
        self._sync_arrow(group)

    def _sync_arrow(self, group):
        if self._arrow is not None:
            if group.isEnabled():
                self._arrow.setCursor(_HAND)
            else:
                self._arrow.unsetCursor()

    def eventFilter(self, group, event):
        kind = event.type()
        if kind == QEvent.Type.MouseMove:
            if over_title(group, _event_pos(event)):
                group.setCursor(_HAND)
            else:
                group.unsetCursor()
        elif kind == QEvent.Type.Leave:
            group.unsetCursor()
        elif kind == QEvent.Type.EnabledChange:
            self._sync_arrow(group)
            group.unsetCursor()
        return False


def hand_cursor_on_title(*groups):
    """Show the pointing hand over each group's arrow and title."""
    for group in groups:
        group.setMouseTracking(True)
        group.installEventFilter(_TitleCursor(group))
