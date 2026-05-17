"""Reusable card container widgets."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget


class CardFrame(QFrame):
    """A QSS-styled card frame for dashboard and settings surfaces."""

    def __init__(self, parent: QWidget | None = None, *, object_name: str = "") -> None:
        super().__init__(parent)
        if object_name:
            self.setObjectName(object_name)
        self.setProperty("card", True)
        self.content_layout = QVBoxLayout(self)
        self.content_layout.setContentsMargins(18, 16, 18, 16)
        self.content_layout.setSpacing(12)

