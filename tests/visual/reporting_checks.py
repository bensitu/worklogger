from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import qInstallMessageHandler
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QScrollArea

from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkLog, EntryType
from worklogger.infrastructure.i18n import available_languages, set_language
from worklogger.presentation.viewmodels.reports import ReportEditorState
from worklogger.presentation.widgets.report_history import ReportHistoryDisplayItem
from tests.visual.shell_checks import sample_window
from tests.presentation.test_shell_pages import ReportsViewModel


class WeeklyReports(ReportsViewModel):
    def load(self, report_type, day):
        start = day - timedelta(days=day.weekday()) if report_type == "weekly" else day
        end = start + timedelta(days=6) if report_type == "weekly" else day
        return Result.success(ReportEditorState(1, report_type, start, end,
            "# Weekly Summary\n\n## Key Achievements\n- Implemented calendar updates.\n\n"
            "## Challenges & Solutions\n- Verified layout at different display scales.\n\n"
            "## Plan for Next Week\n- Complete regression testing.", saved=True, report_id=1))

    def list_history(self, report_type):
        return Result.success(tuple(ReportHistoryDisplayItem(index, 1, report_type, start,
            start + timedelta(days=6), "", "Saved report", index == 1,
            created_at=datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc))
            for index, start in enumerate((date(2026, 5, 18), date(2026, 5, 11), date(2026, 5, 4),
                date(2026, 4, 27), date(2026, 4, 20)), 1)))


class ReportingLayoutChecks(unittest.TestCase):
    def test_analytics_overview_fits_default_window_and_scrolls_when_needed(self):
        from PySide6.QtCore import QCoreApplication, QEvent
        from worklogger.domain.worklog.models import CustomEntryType
        from worklogger.presentation.theme import configure_application_style, install_bundled_fonts

        configure_application_style()
        install_bundled_fonts()
        old_style, old_palette = self.app.styleSheet(), self.app.palette()
        old_context = self.app.property("worklogger_theme_context")

        def settle():
            for _ in range(4):
                self.app.processEvents()

        try:
            for language in available_languages():
                set_language(language)
                for dark in (False, True):
                    window = sample_window()
                    window._config = replace(window._config, theme="blue", dark=dark)
                    page = window.analytics_page
                    records = page._view_model._dashboard_handler._repository
                    for day, entry_type in enumerate(EntryType, 1):
                        records.save(WorkLog(1, date(2026, 5, day), "09:00", "18:00", entry_type=entry_type))
                    try:
                        window.apply_theme()
                        window.resize(1100, 700)
                        window.show()
                        window._switch_route("analytics")
                        self.assertTrue(page.refresh(date(2026, 5, 21)))
                        settle()
                        scroll = page.findChild(QScrollArea, "analytics_scroll_widget")
                        self.assertEqual(len(page.breakdown_chart.chart._segments), len(EntryType))
                        self.assertEqual(scroll.verticalScrollBar().maximum(), 0, (language, dark))
                        self.assertEqual(scroll.horizontalScrollBar().maximum(), 0, (language, dark))
                        self.capture(window, f"analytics-overview-{'dark' if dark else 'light'}", language)
                        page.breakdown_dimension_control.set_value("work_mode")
                        settle()
                        self.assertEqual(scroll.verticalScrollBar().maximum(), 0, (language, dark))
                        if language == "en_US" and not dark:
                            page.breakdown_dimension_control.set_value("entry_type")
                            for scope in ("quarterly", "annual", "monthly"):
                                page.scope_control.set_value(scope)
                                settle()
                                self.assertEqual(scroll.verticalScrollBar().maximum(), 0, scope)
                            window.resize(880, 580)
                            settle()
                            self.assertGreater(scroll.verticalScrollBar().maximum(), 0)
                            self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
                            self.capture(window, "analytics-compact-window", language)
                            window.resize(1100, 700)
                            settle()
                            self.assertEqual(scroll.verticalScrollBar().maximum(), 0)
                            for day in range(11, 31):
                                definition = CustomEntryType(f"custom:{day:032x}", f"Research and development activity {day}", "work")
                                records.save(WorkLog(1, date(2026, 5, day), "09:00", "10:00", entry_type=definition))
                            self.assertTrue(page.refresh())
                            settle()
                            self.assertEqual(len(page.breakdown_chart.chart._segments), 30)
                            self.assertGreater(scroll.verticalScrollBar().maximum(), 0)
                            self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
                    finally:
                        window.hide()
                        window.deleteLater()
                        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        finally:
            self.app.setStyleSheet(old_style)
            self.app.setPalette(old_palette)
            self.app.setProperty("worklogger_theme_context", old_context)

    def test_project_hierarchy_and_scoped_record_results_fit_themed_dialogs(self):
        from types import SimpleNamespace
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        from worklogger.domain.analytics.projects import context_summaries
        from worklogger.domain.projects.models import Project, WorkContext, WorkItem
        from worklogger.domain.worklog.search import EntryFilter, EntryPage
        from worklogger.presentation.date_labels import duration_label
        from worklogger.presentation.job_runner import ImmediateJobRunner
        from worklogger.presentation.theme import ThemeEngine, configure_application_style, install_bundled_fonts
        from worklogger.presentation.widgets.project_analytics import ProjectAnalyticsDialog
        from worklogger.presentation.widgets.record_search import RecordSearchDialog
        from worklogger.infrastructure.i18n import get_language
        configure_application_style()
        install_bundled_fonts()
        project = Project("1" * 32, "Research")
        item = WorkItem("2" * 32, project.id, "Interface review")
        context = WorkContext(project.id, item.id, project.name, item.title)
        entries = tuple(WorkLog(1, date(2026, 10, day), "09:00", "17:00", 1,
                               "Reviewed calendar interactions and navigation. " * 4,
                               id=day, context=context) for day in range(1, 9))
        groups = context_summaries(entries)
        records = SimpleNamespace(list_entry_types=lambda: Result.success(()),
            project_inventory=lambda: Result.success(((project,), {project.id: (item,)})),
            search=lambda *_args, **_kwargs: Result.success(EntryPage(entries)))
        analytics = SimpleNamespace(load_projects=lambda *_args: Result.success(groups))
        criteria = EntryFilter(date(2026, 10, 1), date(2026, 10, 11), project_id=project.id, work_item_id=item.id)
        old_language, old_style, old_palette = get_language(), self.app.styleSheet(), self.app.palette()
        try:
            for language in available_languages():
                set_language(language)
                for theme in ("blue", "liquid_glass"):
                    for dark in (False, True):
                        ThemeEngine().apply_to(self.app, theme, dark=dark)
                        summary = ProjectAnalyticsDialog(analytics, records, criteria.end)
                        detail = RecordSearchDialog(records, criteria.end, criteria=criteria,
                                                    job_runner=ImmediateJobRunner())
                        try:
                            for dialog in (summary, detail):
                                dialog.resize(740, 560)
                                dialog.show()
                            QTest.qWait(1)
                            self.assertEqual([label.text() for label in summary.summary_values],
                                             [duration_label(56), duration_label(8), duration_label(0)])
                            parent = summary.results.topLevelItem(0)
                            self.assertEqual(parent.childCount(), 1)
                            summary.results.setCurrentItem(parent.child(0))
                            detail.results.setCurrentItem(detail.results.topLevelItem(0))
                            self.assertTrue(summary.detail_button.isEnabled())
                            self.assertTrue(detail.open_button.isEnabled())
                            self.assertEqual(detail.project_combo.currentData(), project.id)
                            self.assertEqual(detail.item_combo.currentData(), item.id)
                            for dialog in (summary, detail):
                                tree = dialog.results
                                self.assertGreaterEqual(tree.visualItemRect(tree.topLevelItem(0)).height(), 28)
                                self.assertGreaterEqual(tree.header().height(), 30)
                                self.assertEqual(tree.horizontalScrollBar().maximum(), 0)
                                for field in (dialog.start_input, dialog.end_input):
                                    self.assertTrue(dialog.rect().contains(field.rect().translated(field.mapTo(dialog, QPoint()))))
                                action = summary.detail_button if dialog is summary else detail.open_button
                                self.assertTrue(dialog.rect().contains(action.rect().translated(action.mapTo(dialog, QPoint()))))
                                self.capture(dialog, f"data-browser-{type(dialog).__name__}-{theme}-{dark}", language)
                            self.assertTrue(parent.textAlignment(2) & Qt.AlignmentFlag.AlignRight)
                        finally:
                            summary.close()
                            detail.close()
                            summary.deleteLater()
                            detail.deleteLater()
        finally:
            set_language(old_language)
            self.app.setStyleSheet(old_style)
            self.app.setPalette(old_palette)

    def test_date_popups_share_navigation_and_calendar_styles(self):
        from types import SimpleNamespace
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QSpinBox, QToolButton
        from worklogger.domain.worklog.search import EntryPage
        from worklogger.presentation.job_runner import ImmediateJobRunner
        from worklogger.presentation.theme import ThemeEngine, configure_application_style, install_bundled_fonts
        from worklogger.presentation.widgets.date_picker import MonthCalendar
        from worklogger.presentation.widgets.end_timer import EndTimerDialog
        from worklogger.presentation.widgets.project_analytics import ProjectAnalyticsDialog
        from worklogger.presentation.widgets.record_search import RecordSearchDialog
        from worklogger.infrastructure.i18n import get_language
        configure_application_style()
        install_bundled_fonts()
        old_language, old_style, old_palette = get_language(), self.app.styleSheet(), self.app.palette()
        records = SimpleNamespace(list_entry_types=lambda: Result.success(()),
            project_inventory=lambda: Result.success(((), {})),
            search=lambda *_args, **_kwargs: Result.success(EntryPage(())))
        analytics = SimpleNamespace(load_projects=lambda *_args: Result.success(()))
        started = datetime(2026, 10, 11, 9, tzinfo=timezone.utc)
        try:
            for language in ("en_US", "zh_CN"):
                set_language(language)
                for theme in ("blue", "liquid_glass"):
                    for dark in (False, True):
                        colors = ThemeEngine().apply_to(self.app, theme, dark=dark)
                        dialogs = (ProjectAnalyticsDialog(analytics, records, started.date()),
                                   RecordSearchDialog(records, started.date(), job_runner=ImmediateJobRunner()),
                                   EndTimerDialog(started, started + timedelta(hours=2), timezone.utc))
                        for dialog in dialogs:
                            try:
                                dialog.show()
                                fields = ((dialog.end_input,) if isinstance(dialog, EndTimerDialog)
                                          else (dialog.start_input, dialog.end_input))
                                for index, field in enumerate(fields):
                                    QTest.mouseClick(field, Qt.MouseButton.LeftButton,
                                                     pos=QPoint(field.width() - 12, field.height() // 2))
                                    QTest.qWait(1)
                                    calendar = field.calendarWidget()
                                    self.assertIsInstance(calendar, MonthCalendar)
                                    self.assertTrue(calendar.isVisible())
                                    self.assertEqual(calendar.locale().name(), language)
                                    self.assertEqual(calendar.weekdayTextFormat(Qt.DayOfWeek.Saturday).foreground().color().name(), colors.accent)
                                    for name in ("qt_calendar_prevmonth", "qt_calendar_nextmonth"):
                                        self.assertFalse(calendar.findChild(QToolButton, name).icon().isNull())
                                    month = calendar.findChild(QToolButton, "qt_calendar_monthbutton")
                                    year = calendar.findChild(QToolButton, "qt_calendar_yearbutton")
                                    self.assertLessEqual(abs(month.height() - year.height()), 2)
                                    year.click()
                                    QTest.qWait(1)
                                    editor = calendar.findChild(QSpinBox, "qt_calendar_yearedit")
                                    self.assertLessEqual(editor.width(), 90)
                                    self.assertLessEqual(abs(editor.height() - month.height()), 2)
                                    self.capture(calendar.window(), f"date-popup-{type(dialog).__name__}-{index}-{theme}-{dark}", language)
                                    calendar.window().hide()
                            finally:
                                dialog.close()
                                dialog.deleteLater()
        finally:
            set_language(old_language)
            self.app.setStyleSheet(old_style)
            self.app.setPalette(old_palette)

    def test_report_versions_preview_fits_localized_dialogs(self):
        from worklogger.presentation.widgets.report_revisions import ReportRevisionsDialog
        from worklogger.domain.reporting.models import ReportRevision
        from worklogger.presentation.job_runner import ImmediateJobRunner
        from worklogger.presentation.theme import configure_application_style, install_bundled_fonts, ThemeEngine
        configure_application_style()
        install_bundled_fonts()
        class Model:
            def list_revisions(self, state):
                return Result.success((ReportRevision(1, "Updated report", datetime(2026, 10, 10, tzinfo=timezone.utc)),
                                       ReportRevision(0, "Original report", None)))
        old_style, old_palette = self.app.styleSheet(), self.app.palette()
        try:
            for language in available_languages():
                set_language(language)
                for dark in (False, True):
                    engine = ThemeEngine()
                    self.app.setPalette(engine.qt_palette(dark=dark))
                    self.app.setStyleSheet(engine.application_stylesheet(dark=dark))
                    state = ReportEditorState(1, "monthly", date(2026, 10, 1), date(2026, 10, 31), "Updated", True, 1, revision=1)
                    dialog = ReportRevisionsDialog(Model(), state, job_runner=ImmediateJobRunner())
                    dialog.show()
                    self.app.processEvents()
                    self.assertFalse(dialog.restore_button.isEnabled())
                    for width, height in ((780, 520), (950, 620)):
                        dialog.resize(width, height)
                        self.app.processEvents()
                        for row in (0, 1):
                            dialog.versions.setCurrentRow(row)
                            self.assertEqual(dialog.restore_button.isEnabled(), row == 1)
                            self.assertEqual(dialog.preview.toPlainText(), "Original report" if row else "Updated report")
                            item = dialog.versions.item(row)
                            self.assertGreaterEqual(dialog.versions.visualItemRect(item).height(),
                                                    len(item.text().splitlines()) * dialog.versions.fontMetrics().height() + 20)
                        for tab, field in enumerate((dialog.preview, dialog.sources)):
                            dialog.preview_tabs.setCurrentIndex(tab)
                            self.app.processEvents()
                            self.assertTrue(dialog.rect().contains(field.mapTo(dialog, field.rect().bottomRight())))
                        dialog.preview_tabs.setCurrentIndex(0)
                        for field in (dialog.versions, dialog.preview, dialog.restore_button, dialog.status_label):
                            self.assertTrue(dialog.rect().contains(field.mapTo(dialog, field.rect().bottomRight())))
                        self.assertEqual(dialog.versions.horizontalScrollBar().maximum(), 0)
                        self.capture(dialog, f"report-versions-{dark}-{width}", language)
                    dialog.close()
        finally:
            self.app.setStyleSheet(old_style)
            self.app.setPalette(old_palette)

    def test_project_range_controls_fit_all_languages(self):
        from worklogger.presentation.widgets.project_analytics import ProjectAnalyticsDialog
        from worklogger.domain.analytics.projects import ContextSummary
        from worklogger.domain.projects.models import WorkContext
        from worklogger.presentation.theme import ThemeEngine, configure_application_style, install_bundled_fonts
        configure_application_style()
        install_bundled_fonts()
        class Analytics:
            def load_projects(self, start, end):
                return Result.success((ContextSummary(WorkContext(project_label="Research", work_item_label="Review"), 7, 1, 0, 1, 2),))
        old_style, old_palette = self.app.styleSheet(), self.app.palette()
        try:
            for language in available_languages():
                set_language(language)
                for dark in (False, True):
                    engine = ThemeEngine()
                    self.app.setPalette(engine.qt_palette(dark=dark))
                    self.app.setStyleSheet(engine.application_stylesheet(dark=dark))
                    dialog = ProjectAnalyticsDialog(Analytics(), None, date(2026, 10, 10))
                    dialog.show()
                    self.app.processEvents()
                    self.assertEqual(dialog.results.topLevelItemCount(), 1)
                    for field in (dialog.start_input, dialog.end_input, dialog.refresh_button, dialog.detail_button):
                        self.assertTrue(dialog.rect().contains(field.mapTo(dialog, field.rect().bottomRight())))
                        self.assertGreater(field.height(), 20)
                    self.capture(dialog, "project-statistics-" + str(dark), language)
                    dialog.close()
        finally:
            self.app.setStyleSheet(old_style)
            self.app.setPalette(old_palette)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        set_language("en_US")

    def capture(self, widget, name, language):
        directory = os.environ.get("WORKLOGGER_SCREENSHOTS")
        if directory:
            path = Path(directory)
            path.mkdir(parents=True, exist_ok=True)
            self.assertTrue(widget.grab().save(str(path / f"{language}-{name}.png")))

    def test_calendar_cells_do_not_stretch_with_tall_window(self):
        window = sample_window()
        window.show()
        try:
            window.resize(1100, 950)
            self.assertTrue(window.refresh())
            self.app.processEvents()
            cells = [button for button in window.calendar_view.day_buttons() if button.isVisible()]
            self.assertTrue(cells)
            for button in cells:
                self.assertLessEqual(button.height(), button.width() * 1.25)
            self.assertLess(window.calendar_view.grid_frame.height(), window.calendar_view.height() - 50)
        finally:
            window.close()

    def test_filled_reports_and_analytics_fit_all_languages(self):
        warnings = []
        previous = qInstallMessageHandler(lambda kind, context, message: warnings.append(message))
        try:
            for language in available_languages():
                set_language(language)
                for dark in ((False, True) if language == "en_US" else (language in ("ja_JP", "zh_TW"),)):
                    window = sample_window()
                    window.reports_page._view_model = WeeklyReports()
                    window._config = replace(window._config, dark=dark)
                    records = window.analytics_page._view_model._dashboard_handler._repository
                    for day, mode in ((5, EntryType.REMOTE), (12, EntryType.BUSINESS_TRIP), (19, EntryType.PAID_LEAVE), (20, EntryType.NORMAL)):
                        records.save(WorkLog(1, date(2026, 5, day), "09:00", "18:30", 1, "Test record", mode))
                    window.apply_theme()
                    window.refresh()
                    window.show()
                    try:
                        sizes = ((880, 580), (1100, 700)) if language == "en_US" else ((880, 580),)
                        for width, height in sizes:
                            window.resize(width, height)
                            for route in ("reports", "analytics"):
                                self.assertTrue(window._switch_route(route))
                                page = window.page_stack.currentWidget()
                                self.assertTrue(page.refresh(date(2026, 5, 21)))
                                if route == "reports":
                                    page.report_type_control.set_value("weekly")
                                self.app.processEvents()
                                self.assertEqual((window.width(), window.height()), (width, height))
                                for scroll in page.findChildren(QScrollArea):
                                    self.assertEqual(scroll.horizontalScrollBar().maximum(), 0, (language, route, width))
                                if route == "reports":
                                    button = page.history_panel._buttons[0]
                                    self.assertTrue(button.property("active"))
                                    self.assertIn("\n", button.text())
                                    self.assertLessEqual(button._document.size().height(), button.height() - 20)
                                    page.history_panel.search_line_edit.setText("11")
                                    self.assertTrue(QSignalSpy(page.history_panel._search_timer.timeout).wait(1000))
                                    self.assertEqual(len(page.history_panel._buttons), 1)
                                    page.history_panel.search_line_edit.clear()
                                    self.assertTrue(QSignalSpy(page.history_panel._search_timer.timeout).wait(1000))
                                    self.app.processEvents()
                                    self.assertTrue(all(button.isVisible() for button in page.history_panel._buttons.values()))
                                    buttons = tuple(page.history_panel._buttons.values())
                                    for first, second in zip(buttons, buttons[1:]):
                                        self.assertLess(first.geometry().bottom(), second.geometry().top())
                                    for button in buttons:
                                        self.assertLessEqual(button._document.size().height(), button.height() - 20)
                                else:
                                    self.assertEqual(page._summary_grid.itemAtPosition(0, 0).widget(), page.monthly_hours_card)
                                    self.assertIsNotNone(page._summary_grid.itemAtPosition(1, 0) if width == 880 else page._summary_grid.itemAtPosition(0, 3))
                                    self.assertEqual(len(page.breakdown_chart.chart._segments), 4)
                                    self.assertEqual(page.breakdown_chart.chart._keys, ("normal", "remote", "business_trip", "paid_leave"))
                                self.capture(window, f"filled-{route}-{'dark' if dark else 'light'}-{width}", language)
                    finally:
                        window.close()
            self.assertFalse([message for message in warnings if "QFont::" in message or "QPainter::" in message or "QSvg" in message], warnings)
        finally:
            qInstallMessageHandler(previous)
