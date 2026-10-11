"""Numeric editor content alignment after Qt stylesheet layout."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QTimer, Slot
from PySide6.QtWidgets import QAbstractSpinBox, QStyle, QStyleOptionFrame
from shiboken6 import isValid


class _NumericInputPadding(QObject):
    def __init__(self, spin: QAbstractSpinBox) -> None:
        super().__init__(spin)
        self._spin = spin
        self._editor = spin.lineEdit()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._update_padding)
        spin.installEventFilter(self)
        self._editor.installEventFilter(self)
        self._timer.start(0)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Show,
                            QEvent.Type.Polish, QEvent.Type.StyleChange, QEvent.Type.LayoutDirectionChange):
            # Query style geometry after Qt finishes polishing and laying out widgets.
            self._timer.start(0)
        return False

    @Slot()
    def _update_padding(self) -> None:
        if not isValid(self._spin) or not isValid(self._editor):
            return
        option = QStyleOptionFrame()
        option.initFrom(self._spin)
        contents = self._spin.style().subElementRect(QStyle.SubElement.SE_LineEditContents, option, self._spin)
        geometry = self._editor.geometry()
        # Preserve the stylesheet's content bounds when Qt lays out the editor at x=0.
        left = max(0, contents.left() - geometry.left())
        right = max(0, geometry.right() - contents.right())
        margins = self._editor.textMargins()
        if (margins.left(), margins.top(), margins.right(), margins.bottom()) != (left, 0, right, 0):
            self._editor.setTextMargins(left, 0, right, 0)


def apply_numeric_input_padding(spin: QAbstractSpinBox) -> None:
    if not hasattr(spin, "_numeric_padding_controller"):
        spin._numeric_padding_controller = _NumericInputPadding(spin)

