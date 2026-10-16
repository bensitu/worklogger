"""Bundled Lucide icons rendered against the active application palette."""

from __future__ import annotations

from xml.etree import ElementTree
from functools import lru_cache
import math
import weakref

from PySide6.QtCore import QByteArray, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QIconEngine, QPainter, QPalette, QPixmap, QPixmapCache
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QAbstractButton, QWidget
from shiboken6 import isValid

from worklogger.presentation.widgets.assets import asset_path
from worklogger.presentation.theme.context import current_colors


@lru_cache(maxsize=128)
def _renderer(name: str, color: str) -> QSvgRenderer:
    tree = ElementTree.parse(asset_path(f"icons/ui/{name}.svg"))
    tree.getroot().set("stroke", color)
    return QSvgRenderer(QByteArray(ElementTree.tostring(tree.getroot())))


def _render_pixmap(name: str, color: str, size: QSize, ratio: float, format_label: str = "") -> QPixmap:
    font_key = QGuiApplication.font().key() if format_label else ""
    key = f"worklogger:icon:{name}:{color}:{size.width()}:{size.height()}:{ratio}:{format_label}:{font_key}"
    cached = QPixmapCache.find(key)
    if cached is not None:
        return cached
    pixmap = QPixmap(math.ceil(size.width() * ratio), math.ceil(size.height() * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        side = min(size.width(), size.height())
        bounds = QRectF((size.width() - side) / 2, (size.height() - side) / 2, side, side)
        if format_label:
            label_bounds = QRectF(bounds.left(), bounds.top(), side, side / 3)
            font = QFont(QGuiApplication.font())
            font.setPixelSize(max(1, round(side / 3)))
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            painter.setPen(QColor(color))
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            painter.drawText(label_bounds, Qt.AlignmentFlag.AlignCenter, format_label)
            glyph_side = side * 2 / 3
            bounds = QRectF(bounds.left() + (side - glyph_side) / 2,
                            bounds.bottom() - glyph_side, glyph_side, glyph_side)
        _renderer(name, color).render(painter, bounds)
    finally:
        painter.end()
    QPixmapCache.insert(key, pixmap)
    return pixmap


class _PaletteIconEngine(QIconEngine):
    def __init__(self, name: str, accent: bool = False, primary: bool = False, success: bool = False,
                 *, button: QAbstractButton | None = None, format_label: str = "") -> None:
        super().__init__()
        self._name = name
        self._accent = accent
        self._primary = primary
        self._success = success
        self._format_label = format_label
        self._button = weakref.ref(button) if button is not None else None

    def clone(self) -> QIconEngine:
        button = self._button() if self._button is not None else None
        return _PaletteIconEngine(self._name, self._accent, self._primary, self._success,
                                  button=button if button is not None and isValid(button) else None,
                                  format_label=self._format_label)

    def _color(self, mode: QIcon.Mode) -> str:
        button = self._button() if self._button is not None else None
        if button is not None and isValid(button):
            group = QPalette.ColorGroup.Disabled if mode == QIcon.Mode.Disabled or not button.isEnabled() else QPalette.ColorGroup.Active
            return button.palette().color(group, QPalette.ColorRole.ButtonText).name()
        palette = QGuiApplication.palette()
        role = QPalette.ColorRole.Highlight if self._accent else QPalette.ColorRole.ButtonText
        if self._primary:
            role = QPalette.ColorRole.HighlightedText
        group = QPalette.ColorGroup.Disabled if mode == QIcon.Mode.Disabled else QPalette.ColorGroup.Active
        if mode == QIcon.Mode.Disabled:
            role = QPalette.ColorRole.ButtonText
        color = palette.color(group, role).name()
        if self._success and mode != QIcon.Mode.Disabled:
            color = current_colors().success
        return color

    def paint(self, painter: QPainter, rect: QRect, mode: QIcon.Mode, state: QIcon.State) -> None:
        ratio = painter.device().devicePixelRatioF()
        painter.drawPixmap(rect, _render_pixmap(self._name, self._color(mode), rect.size(), ratio, self._format_label))

    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        return _render_pixmap(self._name, self._color(mode), size, 1.0, self._format_label)

    def scaledPixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State, scale: float) -> QPixmap:
        return _render_pixmap(self._name, self._color(mode), size, scale, self._format_label)


def ui_icon(name: str, *, accent: bool = False, primary: bool = False, success: bool = False,
            format_label: str = "") -> QIcon:
    return QIcon(_PaletteIconEngine(name, accent, primary, success, format_label=format_label))


class IconLabel(QWidget):
    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon = ui_icon(name)
        self.setFixedSize(22, 22)

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        self._icon.paint(painter, self.rect(), mode=QIcon.Mode.Normal if self.isEnabled() else QIcon.Mode.Disabled)
        painter.end()


def set_button_icon(button: QAbstractButton, name: str, *, format_label: str = "") -> None:
    button.setIcon(QIcon(_PaletteIconEngine(name, button=button, format_label=format_label)))
    side = 24 if format_label else 20
    button.setIconSize(QSize(side, side))
