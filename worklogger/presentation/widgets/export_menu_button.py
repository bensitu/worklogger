"""Dropdown export button."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMenu, QToolButton, QWidget


class ExportMenuButton(QToolButton):
    export_requested = Signal(str)

    def __init__(
        self,
        label: str,
        actions: Iterable[tuple[str, str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("export_menu_button")
        self.setText(label)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setProperty("variant", "primary")
        menu = QMenu(self)
        for key, text in actions:
            action = menu.addAction(text)
            action.triggered.connect(lambda _checked=False, item_key=key: self.export_requested.emit(item_key))
        self.setMenu(menu)

