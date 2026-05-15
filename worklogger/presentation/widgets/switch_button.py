"""Reusable Qt switch button."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget


class SwitchButton(QWidget):
    toggled = Signal(bool)

    _WIDTH = 42
    _HEIGHT = 24

    def __init__(
        self,
        *,
        checked: bool = False,
        color_on: str = "#4f8ef7",
        color_off: str = "#c9cfdd",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._checked = bool(checked)
        self._color_on = QColor(color_on)
        self._color_off = QColor(color_off)
        self.setFixedSize(self._WIDTH, self._HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def is_checked(self) -> bool:
        return self._checked

    def set_checked(self, checked: bool) -> None:
        checked = bool(checked)
        if checked == self._checked:
            return
        self._checked = checked
        self.toggled.emit(self._checked)
        self.update()

    isChecked = is_checked
    setChecked = set_checked

    def setEnabled(self, enabled: bool) -> None:
        super().setEnabled(enabled)
        self.setCursor(
            Qt.CursorShape.PointingHandCursor
            if enabled
            else Qt.CursorShape.ArrowCursor
        )
        self.update()

    def mousePressEvent(self, event: object) -> None:
        if not self.isEnabled():
            if hasattr(event, "ignore"):
                event.ignore()
            return
        if getattr(event, "button", lambda: None)() == Qt.MouseButton.LeftButton:
            self.set_checked(not self._checked)
        super().mousePressEvent(event)

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        track = QColor(self._color_on if self._checked else self._color_off)
        thumb = QColor("#ffffff")
        border: QColor | None = None
        if not self.isEnabled():
            track = QColor("#d9dfef")
            thumb = QColor("#f5f7fb")
            border = QColor("#aab1c5")

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(track))
        painter.drawRoundedRect(
            QRectF(0, 0, self._WIDTH, self._HEIGHT),
            self._HEIGHT / 2,
            self._HEIGHT / 2,
        )
        if border is not None:
            painter.setPen(QPen(border, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(
                QRectF(0.5, 0.5, self._WIDTH - 1, self._HEIGHT - 1),
                self._HEIGHT / 2,
                self._HEIGHT / 2,
            )
            painter.setPen(Qt.PenStyle.NoPen)

        padding = 3
        diameter = self._HEIGHT - padding * 2
        x = self._WIDTH - self._HEIGHT + padding if self._checked else padding
        painter.setBrush(QBrush(thumb))
        painter.drawEllipse(QRectF(x, padding, diameter, diameter))
        painter.end()
