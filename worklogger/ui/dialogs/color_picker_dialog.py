from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from config.themes import color_preview_qss, normalize_hex_color
from ui.widgets import ColorCircle, ColorPickerSliders
from utils.i18n import _, msg


class ColorPickerDialog(QDialog):
    """Dialog shell for choosing a custom accent color."""

    selected_color_changed = Signal(str)
    color_selected = Signal(str)

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._color = normalize_hex_color(color)
        self.setWindowTitle(msg("custom_theme_color"))
        self.setModal(True)
        self.setMinimumSize(420, 430)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        self._circle = ColorCircle(self._color)
        outer.addWidget(self._circle, 1)

        self._sliders = ColorPickerSliders(self._color)
        outer.addWidget(self._sliders)

        preview_row = QWidget()
        preview_row.setObjectName("transparent_container")
        preview_l = QHBoxLayout(preview_row)
        preview_l.setContentsMargins(0, 0, 0, 0)
        preview_l.setSpacing(8)
        label = QLabel(msg("selected_color"))
        label.setObjectName("muted")
        self._preview = QLabel()
        self._preview.setFixedHeight(28)
        self._preview.setMinimumWidth(110)
        self._preview.setAlignment(Qt.AlignCenter)
        preview_l.addWidget(label)
        preview_l.addWidget(self._preview)
        preview_l.addStretch()
        outer.addWidget(preview_row)

        self._circle.selected_color_changed.connect(
            lambda hex_color: self._set_color(hex_color, source="circle", emit=False)
        )
        self._sliders.selected_color_changed.connect(
            lambda hex_color: self._set_color(hex_color, source="sliders", emit=False)
        )

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(_("OK"))
        buttons.button(QDialogButtonBox.Cancel).setText(_("Cancel"))
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self._set_color(self._color, emit=False)

    def color(self) -> str:
        return self._color

    def _accept(self) -> None:
        self.color_selected.emit(self._color)
        self.accept()

    def _set_color(
        self,
        color: str,
        source: str | None = None,
        emit: bool = True,
    ) -> None:
        normalized = normalize_hex_color(color)
        self._color = normalized
        if source != "circle":
            self._circle.set_color(normalized)
        if source != "sliders":
            self._sliders.set_color(normalized)
        self._preview.setText(normalized.upper())
        self._preview.setStyleSheet(color_preview_qss(normalized))
        if emit:
            self.selected_color_changed.emit(normalized)
