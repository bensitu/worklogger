"""Verify report history ownership and visibility during repeated rendering."""

from datetime import date
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid

from worklogger.presentation.widgets.report_history import ReportHistoryDisplayItem, ReportHistoryPanel
from worklogger.domain.shared.result import Result
from worklogger.presentation.viewmodels.reports import ReportHistoryItem


class WindowShowObserver(QObject):
    def __init__(self, allowed_window):
        super().__init__()
        self.allowed_window = allowed_window
        self.unexpected_windows = []

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.Type.Show and isinstance(watched, QWidget)
                and watched.isWindow() and watched is not self.allowed_window):
            self.unexpected_windows.append((type(watched).__name__, watched.objectName()))
        return False


class ReportHistoryWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = ReportHistoryPanel()
        self.panel.resize(320, 480)
        self.panel.show()
        self.application.processEvents()
        self.addCleanup(self.panel.deleteLater)
        self.addCleanup(self.panel.close)
        self.item = ReportHistoryDisplayItem(
            1, 1, "daily", date(2026, 5, 21), date(2026, 5, 21),
            "May 21, 2026", "Saved report", True,
        )

    def test_repeated_rendering_never_shows_independent_history_windows(self):
        observer = WindowShowObserver(self.panel)
        self.application.installEventFilter(observer)
        try:
            for items in ((self.item,), (), (self.item,)):
                self.panel.set_items(items)
                self.panel.set_items(items)
                self.application.processEvents()
            self.assertEqual(observer.unexpected_windows, [])
        finally:
            self.application.removeEventFilter(observer)

    def test_replaced_widgets_remain_hidden_children_until_deleted(self):
        self.panel.set_items((self.item,))
        self.application.processEvents()
        old_widgets = [self.panel.scroll_layout.itemAt(index).widget()
                       for index in range(self.panel.scroll_layout.count())
                       if self.panel.scroll_layout.itemAt(index).widget() is not None]
        self.panel.set_items(())
        for widget in old_widgets:
            self.assertIs(widget.parentWidget(), self.panel.scroll_widget)
            self.assertTrue(widget.isHidden())
            self.assertFalse(widget.isWindow())
        for widget in old_widgets:
            self.application.sendPostedEvents(widget, QEvent.Type.DeferredDelete)
        self.assertTrue(all(not isValid(widget) for widget in old_widgets))

    def test_sidebar_report_types_and_search_do_not_create_windows(self):
        from tests.presentation.test_ui_layout import sample_window

        window = sample_window()
        window.reports_page._view_model.list_history = lambda report_type: Result.success((
            ReportHistoryItem(1, 1, report_type, self.item.period_start,
                              self.item.period_end, self.item.content),
        ))
        observer = WindowShowObserver(window)
        window.show()
        self.application.processEvents()
        self.application.installEventFilter(observer)
        try:
            for _ in range(3):
                window.sidebar._buttons["reports"].click()
                self.application.processEvents()
                for report_type in ("daily", "weekly", "monthly"):
                    window.reports_page.report_type_control.set_value(report_type)
                    self.application.processEvents()
                    window.reports_page.history_panel.search_line_edit.setText("No matching report")
                    window.reports_page.history_panel.search_line_edit.clear()
                    self.application.processEvents()
                window.sidebar._buttons["calendar"].click()
                self.application.processEvents()
            self.assertEqual(observer.unexpected_windows, [])
        finally:
            self.application.removeEventFilter(observer)
            window.close()
            window.deleteLater()


if __name__ == "__main__":
    unittest.main()
