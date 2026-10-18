"""Classification choices with shared, theme-aware color previews."""

from __future__ import annotations

import math

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtWidgets import QComboBox, QStyledItemDelegate, QStyleOptionViewItem

from worklogger.domain.worklog.models import CustomEntryType, CustomWorkMode, EntryType, WorkMode
from worklogger.presentation.theme import ThemeEngine
from worklogger.presentation.theme.context import current_colors
from worklogger.presentation.entry_type_labels import entry_type_label, work_mode_label

ClassificationDefinition = EntryType | CustomEntryType | WorkMode | CustomWorkMode

class _EntryTypeColorIconEngine(QIconEngine):
    def __init__(self, definition: ClassificationDefinition) -> None:
        super().__init__()
        self._definition = definition

    def clone(self) -> QIconEngine:
        return _EntryTypeColorIconEngine(self._definition)

    def paint(self, painter: QPainter, rect: QRect, mode: QIcon.Mode, state: QIcon.State) -> None:
        color = ThemeEngine().entry_type_color(self._definition, dark=current_colors().dark)
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


class _EntryTypeOptionDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index) -> None:
        super().initStyleOption(option, index)
        option.features |= QStyleOptionViewItem.ViewItemFeature.HasDecoration
        option.decorationSize = QSize(4, 20)


def entry_type_icon(definition: ClassificationDefinition | None) -> QIcon:
    if ThemeEngine().entry_type_color(definition) is None:
        return QIcon()
    return QIcon(_EntryTypeColorIconEngine(definition))


def _prepare_combo(combo):
    if combo.property("entry_type_picker") is not True:
        combo.setProperty("entry_type_picker", True)
        combo.setItemDelegate(_EntryTypeOptionDelegate(combo))
    combo.setIconSize(QSize(4, 20))


def add_entry_type_option(combo: QComboBox, definition: EntryType | CustomEntryType,
                         *, index: int | None = None) -> None:
    _prepare_combo(combo)
    combo.insertItem(combo.count() if index is None else index,
                     entry_type_icon(definition), entry_type_label(definition), definition.value)


def add_work_mode_option(combo: QComboBox, definition: WorkMode | CustomWorkMode | None) -> None:
    _prepare_combo(combo)
    combo.addItem(entry_type_icon(definition), work_mode_label(definition), definition)
