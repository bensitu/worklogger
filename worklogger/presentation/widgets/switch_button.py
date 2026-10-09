"""Reusable Qt switch button."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QCheckBox, QSizePolicy, QWidget


class SwitchButton(QCheckBox):

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
        super().setChecked(bool(checked))
        self._color_on = QColor(color_on)
        self._color_off = QColor(color_off)
        self.setFixedSize(self._WIDTH, self._HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.toggled.connect(lambda _checked: self.update())

    def is_checked(self) -> bool:
        return super().isChecked()

    def set_checked(self, checked: bool) -> None:
        super().setChecked(bool(checked))

    def setEnabled(self, enabled: bool) -> None:
        super().setEnabled(enabled)
        self.setCursor(
            Qt.CursorShape.PointingHandCursor
            if enabled
            else Qt.CursorShape.ArrowCursor
        )
        self.update()

    def hitButton(self, position) -> bool:
        return self.rect().contains(position)

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        checked = self.is_checked()
        track = QColor(self._color_on if checked else self._color_off)
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
        x = self._WIDTH - self._HEIGHT + padding if checked else padding
        painter.setBrush(QBrush(thumb))
        painter.drawEllipse(QRectF(x, padding, diameter, diameter))
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(self.palette().highlight().color(), 2, Qt.PenStyle.DotLine))
            painter.drawRoundedRect(QRectF(1, 1, self._WIDTH - 2, self._HEIGHT - 2), 10, 10)
        painter.end()
