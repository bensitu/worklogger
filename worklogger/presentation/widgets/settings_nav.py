"""Settings category navigation."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QEvent, Qt, Signal, QTimer
from PySide6.QtGui import QFont, QTextLayout, QTextOption
from PySide6.QtWidgets import QFrame, QVBoxLayout, QPushButton, QWidget

from worklogger.presentation.theme.widget_style import set_style_property
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
        self._wrap_timer = QTimer(self)
        self._wrap_timer.setSingleShot(True)
        self._wrap_timer.timeout.connect(self._wrap_labels)
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
        self._wrap_timer.start(0)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if (event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange)
                and hasattr(self, "_wrap_timer")):
            self._wrap_timer.start(0)

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
            wrapped = "\n".join(lines)
            if button.text() != wrapped:
                button.setText(wrapped)
            height = max(50, len(lines) * button.fontMetrics().height() + 20)
            if button.minimumHeight() != height:
                button.setMinimumHeight(height)

    @property
    def category(self) -> str:
        return self._category

    def set_category(self, category: str, *, emit: bool = True) -> None:
        normalized = str(category or "").strip()
        if normalized not in self._buttons or normalized == self._category:
            return
        self._category = normalized
        for key, button in self._buttons.items():
            set_style_property(button, "active", key == normalized)
        self._wrap_timer.start(0)
        if emit:
            self.category_changed.emit(normalized)

