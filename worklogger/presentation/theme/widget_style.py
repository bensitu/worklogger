"""Targeted Qt stylesheet refresh for dynamic properties and inherited selectors."""

from PySide6.QtWidgets import QWidget


def refresh_style(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def set_style_property(widget: QWidget, name: str, value: bool | str | int) -> None:
    if widget.property(name) != value:
        widget.setProperty(name, value)
        refresh_style(widget)


def refresh_style_tree(widget: QWidget) -> None:
    refresh_style(widget)
    for child in widget.findChildren(QWidget):
        refresh_style(child)
