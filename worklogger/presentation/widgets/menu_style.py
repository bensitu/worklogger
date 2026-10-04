"""Stable styling for menu buttons with pixel-sized fonts on Windows."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QAbstractButton, QStyleFactory


def configure_menu_button_style(button: QAbstractButton) -> None:
    if sys.platform != "win32":
        return
    # Windows 11 menu indicators assume point-sized fonts; QSS uses pixel sizes.
    style = QStyleFactory.create("Fusion")
    style.setParent(button)
    button.setStyle(style)
