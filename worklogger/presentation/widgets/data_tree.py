"""Shared table layout for record browsing and project summaries."""

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView


def configure_data_tree(tree, widths, *, stretch_column):
    tree.setProperty("data_browser", True)
    tree.setUniformRowHeights(True)
    tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    tree.setWordWrap(False)
    tree.setTextElideMode(Qt.TextElideMode.ElideRight)
    tree.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    tree.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    tree.setIndentation(18)
    header = tree.header()
    header.setHighlightSections(False)
    header.setMinimumSectionSize(64)
    header.setStretchLastSection(False)
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    for column, width in enumerate(widths):
        tree.setColumnWidth(column, width)
    header.setSectionResizeMode(stretch_column, QHeaderView.ResizeMode.Stretch)


def set_data_tooltips(row, overrides=None):
    overrides = overrides or {}
    for column in range(row.columnCount()):
        text = overrides.get(column, row.text(column))
        if text:
            row.setToolTip(column, "<qt>" + escape(text).replace("\n", "<br>") + "</qt>")
