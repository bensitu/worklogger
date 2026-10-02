"""Settings category navigation."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont, QTextLayout, QTextOption
from PySide6.QtWidgets import QFrame, QVBoxLayout, QPushButton, QWidget

from worklogger.presentation.widgets._style import refresh_style
from worklogger.presentation.widgets.icons import set_button_icon


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
        self._labels: dict[str, str] = {}
        self._category = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        for key, label in items:
            button = QPushButton(label)
            button.setObjectName(f"settings_{key}_button")
            button.setProperty("settings_nav_item", True)
            icon_name = {"appearance": "palette", "general": "settings", "ai": "sparkles", "data": "database", "network": "globe", "account": "user-round", "about": "info"}.get(key)
            if icon_name:
                set_button_icon(button, icon_name)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAccessibleName(label)
            button.setToolTip(label)
            button.clicked.connect(lambda _checked=False, item_key=key: self.set_category(item_key))
            self._buttons[str(key)] = button
            self._labels[str(key)] = label
            layout.addWidget(button)
        layout.addStretch(1)
        if self._buttons:
            self.set_category(next(iter(self._buttons)), emit=False)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._wrap_labels()

    def _wrap_labels(self) -> None:
        for key, button in self._buttons.items():
            label = self._labels[key]
            width = max(40, self.width() - 28 - button.iconSize().width() - 8)
            font = QFont(button.font())
            font.setWeight(QFont.Weight.DemiBold)
            text = QTextLayout(label, font)
            option = QTextOption()
            option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
            text.setTextOption(option)
            text.beginLayout()
            lines = []
            while True:
                line = text.createLine()
                if not line.isValid():
                    break
                line.setLineWidth(width)
                lines.append(label[line.textStart():line.textStart() + line.textLength()].strip())
            text.endLayout()
            button.setText("\n".join(lines))
            button.setMinimumHeight(max(50, len(lines) * button.fontMetrics().height() + 20))

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
        QTimer.singleShot(0, self, self._wrap_labels)
        if changed and emit:
            self.category_changed.emit(normalized)

