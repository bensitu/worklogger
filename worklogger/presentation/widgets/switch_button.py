"""Reusable Qt switch button."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QCheckBox, QSizePolicy, QWidget

from worklogger.presentation.theme.context import current_colors


class SwitchButton(QCheckBox):

    _WIDTH = 42
    _HEIGHT = 24

    def __init__(
        self,
        *,
        checked: bool = False,
        color_on: str | None = None,
        color_off: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        super().setChecked(bool(checked))
        self._color_on = QColor(color_on) if color_on is not None else None
        self._color_off = QColor(color_off) if color_off is not None else None
        self.setFixedSize(self._WIDTH, self._HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.toggled.connect(lambda _checked: self.update())

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.update()

    def is_checked(self) -> bool:
        return super().isChecked()

    def set_checked(self, checked: bool) -> None:
        super().setChecked(bool(checked))

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.EnabledChange:
            self.setCursor(Qt.CursorShape.PointingHandCursor if self.isEnabled() else Qt.CursorShape.ArrowCursor)
            self.update()

    def hitButton(self, position) -> bool:
        return self.rect().contains(position)

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        checked = self.is_checked()
        colors = current_colors()
        override = self._color_on if checked else self._color_off
        track = QColor(override if override is not None else colors.accent if checked else colors.border_strong)
        thumb = QColor(colors.highlighted_text if checked else colors.surface)
        border: QColor | None = None
        if not self.isEnabled():
            track = QColor(colors.disabled_background)
            thumb = QColor(colors.disabled_text)
            border = QColor(colors.border_strong)
        elif self.underMouse():
            track = track.lighter(115) if track.lightness() < 128 else track.darker(110)

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
