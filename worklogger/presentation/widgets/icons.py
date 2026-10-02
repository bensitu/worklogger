"""Bundled Lucide icons rendered against the active application palette."""

from __future__ import annotations

from xml.etree import ElementTree

from PySide6.QtCore import QByteArray, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QIconEngine, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QAbstractButton

from worklogger.presentation.widgets.assets import asset_path


class _PaletteIconEngine(QIconEngine):
    def __init__(self, name: str, accent: bool = False, primary: bool = False) -> None:
        super().__init__()
        self._name = name
        self._accent = accent
        self._primary = primary

    def clone(self) -> QIconEngine:
        return _PaletteIconEngine(self._name, self._accent, self._primary)

    def paint(self, painter: QPainter, rect: QRect, mode: QIcon.Mode, state: QIcon.State) -> None:
        palette = QGuiApplication.palette()
        role = QPalette.ColorRole.Highlight if self._accent else QPalette.ColorRole.ButtonText
        if self._primary:
            role = QPalette.ColorRole.HighlightedText
        group = QPalette.ColorGroup.Disabled if mode == QIcon.Mode.Disabled else QPalette.ColorGroup.Active
        if mode == QIcon.Mode.Disabled:
            role = QPalette.ColorRole.ButtonText
        tree = ElementTree.parse(asset_path(f"icons/ui/{self._name}.svg"))
        tree.getroot().set("stroke", palette.color(group, role).name())
        renderer = QSvgRenderer(QByteArray(ElementTree.tostring(tree.getroot())))
        renderer.render(painter, QRectF(rect))

    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        pixmap = QPixmap(size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        self.paint(painter, QRect(0, 0, size.width(), size.height()), mode, state)
        painter.end()
        return pixmap


def ui_icon(name: str, *, accent: bool = False, primary: bool = False) -> QIcon:
    return QIcon(_PaletteIconEngine(name, accent, primary))


def set_button_icon(button: QAbstractButton, name: str, *, accent: bool = False) -> None:
    button.setIcon(ui_icon(name, accent=accent, primary=button.property("variant") == "primary"))
    button.setIconSize(QSize(20, 20))
