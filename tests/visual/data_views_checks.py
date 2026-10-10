"""Opt-in rendering checks for shared table and tree data surfaces."""

import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from worklogger.presentation.theme import (
    ThemeEngine,
    configure_application_style,
    install_bundled_fonts,
)


class DataViewLayoutChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        configure_application_style()
        install_bundled_fonts()

    def test_data_rows_and_empty_viewports_use_theme_surfaces(self):
        engine = ThemeEngine()
        old_style, old_palette = self.app.styleSheet(), self.app.palette()
        try:
            for theme in ("blue", "pink", "green", "purple", "custom"):
                for dark in (False, True):
                    colors = engine.palette(theme, dark=dark, custom_color="#168078")
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
                                expected = colors.surface_alt if dark and row == 1 else colors.surface
                                self.assertEqual(rendered.pixelColor(center).name(), expected,
                                                 (theme, dark, type(view).__name__, row))
                            self.assertEqual(rendered.pixelColor(rendered.width() - 5, rendered.height() - 5).name(),
                                             colors.surface)
                            if view is table:
                                table.selectRow(0)
                            else:
                                tree.topLevelItem(0).setSelected(True)
                            self.app.processEvents()
                            selected = view.viewport().grab().toImage()
                            center = view.visualRect(view.model().index(0, 1)).center()
                            self.assertNotEqual(selected.pixelColor(center).name(), colors.surface)
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
