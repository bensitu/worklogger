"""Helpers for refreshing Qt dynamic-property styling."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget


def refresh_style(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()

