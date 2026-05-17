"""Segmented control widget for page mode switches."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from worklogger.presentation.widgets._style import refresh_style


class SegmentedControl(QWidget):
    value_changed = Signal(str)

    def __init__(
        self,
        items: Iterable[tuple[str, str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("segmented_control_widget")
        self._buttons: dict[str, QPushButton] = {}
        self._value = ""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        for key, label in items:
            button = QPushButton(label)
            button.setObjectName(f"segment_{key}_button")
            button.setProperty("segment", True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, item_key=key: self.set_value(item_key))
            self._buttons[str(key)] = button
            layout.addWidget(button)
        if self._buttons:
            self.set_value(next(iter(self._buttons)), emit=False)

    @property
    def value(self) -> str:
        return self._value

    def set_value(self, value: str, *, emit: bool = True) -> None:
        normalized = str(value or "").strip()
        if normalized not in self._buttons:
            return
        changed = normalized != self._value
        self._value = normalized
        for key, button in self._buttons.items():
            button.setProperty("checked", key == normalized)
            refresh_style(button)
        if changed and emit:
            self.value_changed.emit(normalized)

