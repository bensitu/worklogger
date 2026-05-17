"""Settings category navigation."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QVBoxLayout, QPushButton, QWidget

from worklogger.presentation.widgets._style import refresh_style


class SettingsNav(QFrame):
    category_changed = Signal(str)

    def __init__(
        self,
        items: Iterable[tuple[str, str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settings_navigation_frame")
        self._buttons: dict[str, QPushButton] = {}
        self._category = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        for key, label in items:
            button = QPushButton(label)
            button.setObjectName(f"settings_{key}_button")
            button.setProperty("settings_nav_item", True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, item_key=key: self.set_category(item_key))
            self._buttons[str(key)] = button
            layout.addWidget(button)
        layout.addStretch(1)
        if self._buttons:
            self.set_category(next(iter(self._buttons)), emit=False)

    @property
    def category(self) -> str:
        return self._category

    def set_category(self, category: str, *, emit: bool = True) -> None:
        normalized = str(category or "").strip()
        if normalized not in self._buttons:
            return
        changed = normalized != self._category
        self._category = normalized
        for key, button in self._buttons.items():
            button.setProperty("active", key == normalized)
            refresh_style(button)
        if changed and emit:
            self.category_changed.emit(normalized)

