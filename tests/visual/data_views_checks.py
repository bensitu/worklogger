"""Opt-in rendering checks for shared table and tree data surfaces."""

import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QListWidget,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from worklogger.presentation.theme import (
    ThemeEngine,
    THEME_KEYS,
    configure_application_style,
    install_bundled_fonts,
)


class DataViewLayoutChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        configure_application_style()
        install_bundled_fonts()

    def test_item_hover_highlights_unselected_content_without_changing_selection(self):
        engine = ThemeEngine()
        old_style, old_palette = self.app.styleSheet(), self.app.palette()
        old_context = self.app.property("worklogger_theme_context")
        try:
            for theme in THEME_KEYS:
                for dark in (False, True):
                    colors = engine.apply_to(self.app, theme, dark=dark, custom_color="#168078")
                    for factory in (QTableWidget, QTreeWidget, QListWidget):
                        view = factory()
                        if isinstance(view, QTableWidget):
                            view.setRowCount(3)
                            view.setColumnCount(2)
                            for row in range(3):
                                for column in range(2):
                                    view.setItem(row, column, QTableWidgetItem(""))
                            view.selectRow(0)
                        elif isinstance(view, QTreeWidget):
                            view.setColumnCount(2)
                            view.addTopLevelItems([QTreeWidgetItem(("", "")) for _ in range(3)])
                            view.setCurrentItem(view.topLevelItem(0))
                        else:
                            view.addItems(("", "", ""))
                            view.setCurrentRow(0)
                        view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
                        view.resize(420, 240)
                        view.show()
                        self.app.processEvents()
                        try:
                            column_count = 1 if isinstance(view, QListWidget) else view.columnCount()
                            indexes = [view.model().index(1, column) for column in range(column_count)]
                            geometry = view.geometry()
                            selection = view.selectionModel().selectedIndexes()
                            def row_colors(row):
                                image = view.viewport().grab().toImage().scaled(view.viewport().size())
                                samples = []
                                for column in range(column_count):
                                    rect = view.visualRect(view.model().index(row, column))
                                    samples.append(image.pixelColor(QPoint(rect.right() - 8, rect.center().y())).name())
                                return samples
                            original, selected = row_colors(1), row_colors(0)
                            self.move_pointer(view.viewport(), view.visualRect(indexes[-1]).center())
                            expected = ([*original[:-1], colors.accent_dim] if isinstance(view, QTableWidget)
                                        else [colors.accent_dim] * len(indexes))
                            self.assertEqual(row_colors(1), expected,
                                             (theme, dark, factory.__name__))
                            destination = os.environ.get("WORKLOGGER_SCREENSHOTS")
                            if destination:
                                path = Path(destination)
                                path.mkdir(parents=True, exist_ok=True)
                                self.assertTrue(view.grab().save(str(path /
                                    f"{theme}-{dark}-{factory.__name__}-hover.png")))
                            self.assertEqual(row_colors(0), selected)
                            self.assertEqual(view.geometry(), geometry)
                            self.assertEqual(view.selectionModel().selectedIndexes(), selection)
                            self.move_pointer(view.viewport(), view.visualRect(view.model().index(0, 0)).center())
                            self.assertEqual(row_colors(0), selected)
                            self.assertEqual(row_colors(1), original)
                            self.move_pointer(view.viewport(), view.viewport().rect().bottomRight() - QPoint(3, 3))
                            self.assertEqual(row_colors(1), original)
                            view.setEnabled(False)
                            self.app.processEvents()
                            disabled = row_colors(1)
                            self.move_pointer(view.viewport(), view.visualRect(indexes[-1]).center())
                            self.assertEqual(row_colors(1), disabled)
                        finally:
                            view.close()
                            view.deleteLater()
        finally:
            self.app.setStyleSheet(old_style)
            self.app.setPalette(old_palette)
            self.app.setProperty("worklogger_theme_context", old_context)

    def move_pointer(self, widget, point):
        event = QMouseEvent(QEvent.Type.MouseMove, QPointF(point), QPointF(widget.mapToGlobal(point)),
                            Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(widget, event)
        self.app.processEvents()

    def test_data_rows_and_empty_viewports_use_theme_surfaces(self):
        engine = ThemeEngine()
        old_style, old_palette = self.app.styleSheet(), self.app.palette()
        try:
            for theme in THEME_KEYS:
                for dark in (False, True):
                    colors = engine.palette(theme, dark=dark, custom_color="#168078")
                    table_fill = colors.input_background if colors.material == "glass" else colors.surface
                    self.app.setPalette(engine.qt_palette(theme, dark=dark, custom_color="#168078"))
                    self.app.setStyleSheet(engine.application_stylesheet(theme, dark=dark, custom_color="#168078"))
                    panel = QWidget()
                    layout = QHBoxLayout(panel)
                    table = QTableWidget(4, 2)
                    table.setHorizontalHeaderLabels(["User", "Role"])
                    tree = QTreeWidget()
                    tree.setHeaderLabels(["Date", "Content"])
                    tree.setRootIsDecorated(False)
                    for row in range(4):
                        table.setItem(row, 0, QTableWidgetItem(f"Sample {row + 1}"))
                        table.setItem(row, 1, QTableWidgetItem(""))
                        tree.addTopLevelItem(QTreeWidgetItem([f"2026-10-{row + 1:02}", ""]))
                    for view in (table, tree):
                        view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
                        view.setAlternatingRowColors(True)
                        header = tree.header() if view is tree else table.horizontalHeader()
                        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
                        layout.addWidget(view)
                    try:
                        panel.resize(840, 400)
                        panel.show()
                        self.app.processEvents()
                        for view in (table, tree):
                            view.clearSelection()
                            self.app.processEvents()
                            rendered = view.viewport().grab().toImage()
                            for row in range(2):
                                center = view.visualRect(view.model().index(row, 1)).center()
                                expected = colors.table_alternate if dark and row == 1 else table_fill
                                self.assertEqual(rendered.pixelColor(center).name(), expected,
                                                 (theme, dark, type(view).__name__, row))
                            self.assertEqual(rendered.pixelColor(rendered.width() - 5, rendered.height() - 5).name(),
                                             table_fill)
                            if view is table:
                                table.selectRow(0)
                            else:
                                tree.topLevelItem(0).setSelected(True)
                            self.app.processEvents()
                            selected = view.viewport().grab().toImage()
                            center = view.visualRect(view.model().index(0, 1)).center()
                            self.assertNotEqual(selected.pixelColor(center).name(), table_fill)
                        destination = os.environ.get("WORKLOGGER_SCREENSHOTS")
                        if destination:
                            path = Path(destination)
                            path.mkdir(parents=True, exist_ok=True)
                            self.assertTrue(panel.grab().save(str(path / f"{theme}-data-views-{'dark' if dark else 'light'}.png")))
                    finally:
                        panel.close()
                        panel.deleteLater()
        finally:
            self.app.setPalette(old_palette)
            self.app.setStyleSheet(old_style)
