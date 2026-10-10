"""Bundled Lucide icons rendered against the active application palette."""

from __future__ import annotations

from xml.etree import ElementTree
from functools import lru_cache
import math
import weakref

from PySide6.QtCore import QByteArray, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QIconEngine, QPainter, QPalette, QPixmap, QPixmapCache
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QAbstractButton, QWidget
from shiboken6 import isValid

from worklogger.presentation.widgets.assets import asset_path


@lru_cache(maxsize=128)
def _renderer(name: str, color: str) -> QSvgRenderer:
    tree = ElementTree.parse(asset_path(f"icons/ui/{name}.svg"))
    tree.getroot().set("stroke", color)
    return QSvgRenderer(QByteArray(ElementTree.tostring(tree.getroot())))


def _render_pixmap(name: str, color: str, size: QSize, ratio: float) -> QPixmap:
    key = f"worklogger:icon:{name}:{color}:{size.width()}:{size.height()}:{ratio}"
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
        _renderer(name, color).render(painter, bounds)
    finally:
        painter.end()
    QPixmapCache.insert(key, pixmap)
    return pixmap


class _PaletteIconEngine(QIconEngine):
    def __init__(self, name: str, accent: bool = False, primary: bool = False, success: bool = False,
                 *, button: QAbstractButton | None = None) -> None:
        super().__init__()
        self._name = name
        self._accent = accent
        self._primary = primary
        self._success = success
        self._button = weakref.ref(button) if button is not None else None

    def clone(self) -> QIconEngine:
        button = self._button() if self._button is not None else None
        return _PaletteIconEngine(self._name, self._accent, self._primary, self._success,
                                  button=button if button is not None and isValid(button) else None)

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
            color = "#45c97a" if palette.color(QPalette.ColorRole.Window).lightness() < 128 else "#16a34a"
        return color

    def paint(self, painter: QPainter, rect: QRect, mode: QIcon.Mode, state: QIcon.State) -> None:
        ratio = painter.device().devicePixelRatioF()
        painter.drawPixmap(rect, _render_pixmap(self._name, self._color(mode), rect.size(), ratio))

    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        return _render_pixmap(self._name, self._color(mode), size, 1.0)

    def scaledPixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State, scale: float) -> QPixmap:
        return _render_pixmap(self._name, self._color(mode), size, scale)


def ui_icon(name: str, *, accent: bool = False, primary: bool = False, success: bool = False) -> QIcon:
    return QIcon(_PaletteIconEngine(name, accent, primary, success))


class IconLabel(QWidget):
    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon = ui_icon(name)
        self.setFixedSize(22, 22)

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        self._icon.paint(painter, self.rect())
        painter.end()


def set_button_icon(button: QAbstractButton, name: str) -> None:
    button.setIcon(QIcon(_PaletteIconEngine(name, button=button)))
    button.setIconSize(QSize(20, 20))
