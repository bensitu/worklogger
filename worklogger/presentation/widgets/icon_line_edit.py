"""Line edit with optional leading and trailing controls."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget


class IconLineEdit(QWidget):
    def __init__(
        self,
        *,
        placeholder: str = "",
        icon_text: str = "",
        object_name: str = "",
        trailing_button: QPushButton | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("icon_line_edit_widget")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        if icon_text:
            self.icon_label = QLabel(icon_text)
            self.icon_label.setObjectName("icon_text_label")
            self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self.icon_label)
        else:
            self.icon_label = QLabel("")
            self.icon_label.setVisible(False)
        self.line_edit = QLineEdit()
        if object_name:
            self.line_edit.setObjectName(object_name)
        self.line_edit.setPlaceholderText(placeholder)
        layout.addWidget(self.line_edit, 1)
        self.trailing_button = trailing_button
        if trailing_button is not None:
            layout.addWidget(trailing_button)

