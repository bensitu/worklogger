"""Status text that takes no space while idle."""

from PySide6.QtWidgets import QLabel, QWidget


class StatusLabel(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("", parent)
        self.setWordWrap(True)
        self.hide()

    def setText(self, text: str) -> None:
        super().setText(text)
        self.setVisible(bool(text))

    def clear(self) -> None:
        self.setText("")
