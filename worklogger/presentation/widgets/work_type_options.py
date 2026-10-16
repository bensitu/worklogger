"""Work-type choices with theme-aware calendar marker previews."""

from __future__ import annotations

import math

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtWidgets import QComboBox, QStyledItemDelegate, QStyleOptionViewItem

from worklogger.domain.worklog.models import CustomWorkType, WorkType
from worklogger.presentation.theme import ThemeEngine
from worklogger.presentation.theme.context import current_colors
from worklogger.presentation.work_type_labels import work_type_label


class _WorkTypeMarkerIconEngine(QIconEngine):
    def __init__(self, definition: WorkType | CustomWorkType) -> None:
        super().__init__()
        self._definition = definition

    def clone(self) -> QIconEngine:
        return _WorkTypeMarkerIconEngine(self._definition)

    def paint(self, painter: QPainter, rect: QRect, mode: QIcon.Mode, state: QIcon.State) -> None:
        color = ThemeEngine().work_type_marker_color(self._definition, dark=current_colors().dark)
        if color is None:
            return
        painter.save()
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            if mode == QIcon.Mode.Disabled:
                painter.setOpacity(painter.opacity() * 0.45)
            width = min(3.0, rect.width())
            height = min(16.0, rect.height())
            painter.drawRoundedRect(QRectF(rect.x() + (rect.width() - width) / 2,
                                          rect.y() + (rect.height() - height) / 2,
                                          width, height), width / 2, width / 2)
        finally:
            painter.restore()

    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        return self.scaledPixmap(size, mode, state, 1.0)

    def scaledPixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State, scale: float) -> QPixmap:
        pixmap = QPixmap(math.ceil(size.width() * scale), math.ceil(size.height() * scale))
        pixmap.setDevicePixelRatio(scale)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        try:
            self.paint(painter, QRect(0, 0, size.width(), size.height()), mode, state)
        finally:
            painter.end()
        return pixmap


class _WorkTypeOptionDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index) -> None:
        super().initStyleOption(option, index)
        option.features |= QStyleOptionViewItem.ViewItemFeature.HasDecoration
        option.decorationSize = QSize(4, 20)


def work_type_icon(definition: WorkType | CustomWorkType) -> QIcon:
    if ThemeEngine().work_type_marker_color(definition) is None:
        return QIcon()
    return QIcon(_WorkTypeMarkerIconEngine(definition))


def add_work_type_option(combo: QComboBox, definition: WorkType | CustomWorkType,
                         *, index: int | None = None) -> None:
    if combo.property("work_type_picker") is not True:
        combo.setProperty("work_type_picker", True)
        combo.setItemDelegate(_WorkTypeOptionDelegate(combo))
    combo.setIconSize(QSize(4, 20))
    combo.insertItem(combo.count() if index is None else index,
                     work_type_icon(definition), work_type_label(definition), definition.value)
