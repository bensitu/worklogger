"""Bundled Lucide icons rendered against the active application palette."""

from __future__ import annotations

from xml.etree import ElementTree

from PySide6.QtCore import QByteArray, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QIconEngine, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QAbstractButton, QWidget

from worklogger.presentation.widgets.assets import asset_path


class _PaletteIconEngine(QIconEngine):
    def __init__(self, name: str, accent: bool = False, primary: bool = False, success: bool = False) -> None:
        super().__init__()
        self._name = name
        self._accent = accent
        self._primary = primary
        self._success = success

    def clone(self) -> QIconEngine:
        return _PaletteIconEngine(self._name, self._accent, self._primary, self._success)

    def paint(self, painter: QPainter, rect: QRect, mode: QIcon.Mode, state: QIcon.State) -> None:
        palette = QGuiApplication.palette()
        role = QPalette.ColorRole.Highlight if self._accent else QPalette.ColorRole.ButtonText
        if self._primary:
            role = QPalette.ColorRole.HighlightedText
        group = QPalette.ColorGroup.Disabled if mode == QIcon.Mode.Disabled else QPalette.ColorGroup.Active
        if mode == QIcon.Mode.Disabled:
            role = QPalette.ColorRole.ButtonText
        tree = ElementTree.parse(asset_path(f"icons/ui/{self._name}.svg"))
        color = palette.color(group, role).name()
        if self._success and mode != QIcon.Mode.Disabled:
            color = "#45c97a" if palette.color(QPalette.ColorRole.Window).lightness() < 128 else "#16a34a"
        tree.getroot().set("stroke", color)
        renderer = QSvgRenderer(QByteArray(ElementTree.tostring(tree.getroot())))
        renderer.render(painter, QRectF(rect))

    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        pixmap = QPixmap(size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        self.paint(painter, QRect(0, 0, size.width(), size.height()), mode, state)
        painter.end()
        return pixmap


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


def set_button_icon(button: QAbstractButton, name: str, *, accent: bool = False) -> None:
    button.setIcon(ui_icon(name, accent=accent, primary=button.property("variant") == "primary"))
    button.setIconSize(QSize(20, 20))
