"""Opt-in checks for report actions, record-based rest counts, and service availability."""

from datetime import date
import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFormLayout
from tests.presentation.test_settings_presentation import MemorySettingsRepository, _view_model
from tests.presentation.test_shell_pages import ReportsViewModel
from worklogger.infrastructure.i18n import get_language, available_languages, set_language
from worklogger.presentation.settings import SettingsPage
from worklogger.presentation.shell.reports_page import ReportsPage
from worklogger.presentation.job_runner import ImmediateJobRunner
from worklogger.presentation.theme import configure_application_style, install_bundled_fonts, ThemeEngine
from worklogger.domain.shared.result import Result
from worklogger.presentation.viewmodels.reports import ReportEditorState
from worklogger.domain.auth.models import User
from worklogger.infrastructure.i18n import _


class ReportSettingsLayoutChecks(unittest.TestCase):
    def test_settings_groups_and_processing_feedback_fit_localized_pages(self):
        from PySide6.QtWidgets import QLabel
        from worklogger.app.job_runner import JobHandle
        from worklogger.domain.worklog.models import WorkLog, WorkType
        from tests.presentation.test_app_window import _window, MemoryWorkLogRepository
        from types import SimpleNamespace
        class DeferredRunner:
            def submit(self, name, work, *, on_complete):
                return JobHandle(name, lambda: None)
        engine = ThemeEngine()
        old_language, old_style, old_palette = get_language(), self.app.styleSheet(), self.app.palette()
        try:
            for language in available_languages():
                set_language(language)
                for dark in (False, True):
                    self.app.setPalette(engine.qt_palette(dark=dark))
                    self.app.setStyleSheet(engine.application_stylesheet(dark=dark))
                    settings = SettingsPage(_view_model(MemorySettingsRepository()))
                    settings.refresh()
                    settings.resize(880, 680)
                    settings.show()
                    settings.category_nav.set_category("general")
                    self.app.processEvents()
                    general = settings.category_stack.currentWidget()
                    headings = [label.text() for label in general.findChildren(QLabel, "settings_section_title_label")]
                    self.assertEqual(headings, [_("Work and recording"), _("Calendar display"), _("Application behavior")])
                    self.capture(settings, f"{language}-general-groups-{dark}")
                    settings.set_data_directory(Path("D:/Application Data/WorkLogger"))
                    settings.category_nav.set_category("data")
                    self.app.processEvents()
                    card = settings.data_directory_input.parentWidget()
                    description = card.findChild(QLabel, "settings_secondary_label")
                    self.assertTrue(description.text())
                    self.assertLess(description.geometry().bottom(), settings.data_directory_input.geometry().top())
                    self.capture(settings, f"{language}-data-description-{dark}")
                    settings.close()
                    window = _window(MemoryWorkLogRepository())
                    window.resize(1100, 700)
                    window.refresh()
                    panel = window.entry_panel
                    panel.view_model.service.projects = SimpleNamespace(catalog=lambda: Result.success(((), {})), recent_contexts=lambda: Result.success(()))
                    panel.context_picker.show()
                    panel.view_model._rewrite_handler = SimpleNamespace(available=True)
                    panel.refresh_ai_availability()
                    panel._polish_task._runner = DeferredRunner()
                    panel.view_model.select(WorkLog(1, window._selected_day, "09:00", "10:00", note="Meeting agenda", work_type=WorkType.MEETING, id=1))
                    panel._render_editor()
                    window.show()
                    panel.polish_button.click()
                    self.app.processEvents()
                    self.assertTrue(panel.processing_progress.isVisible())
                    self.assertTrue(panel.processing_progress.cancel_button.isEnabled())
                    self.assertTrue(panel.isEnabled())
                    self.assertTrue(panel.content_input.isReadOnly())
                    self.assertEqual(panel.processing_progress.bar.minimum(), panel.processing_progress.bar.maximum())
                    self.assertTrue(panel.rect().contains(panel.processing_progress.rect().translated(panel.processing_progress.mapTo(panel, panel.rect().topLeft()))))
                    input_bottom = panel.content_input.mapTo(window, panel.content_input.rect().bottomLeft()).y()
                    actions_top = panel.actions_widget.mapTo(window, panel.actions_widget.rect().topLeft()).y()
                    self.assertLess(input_bottom, actions_top)
                    self.capture(window, f"{language}-record-processing-{dark}")
                    panel.processing_progress.cancel_button.click()
                    panel.clear_button.click()
                    window.close()
                    page = ReportsPage(ReportsViewModel(), date(2026, 5, 21), job_runner=ImmediateJobRunner())
                    page.refresh()
                    page._rewrite_task._runner = DeferredRunner()
                    page.resize(1000, 650)
                    page.show()
                    page._rewrite_current()
                    self.app.processEvents()
                    self.assertTrue(page.processing_progress.isVisible())
                    self.assertTrue(page.processing_progress.cancel_button.isEnabled())
                    self.capture(page, f"{language}-report-processing-{dark}")
                    page.processing_progress.cancel_button.click()
                    page.close()
        finally:
            set_language(old_language)
            self.app.setStyleSheet(old_style)
            self.app.setPalette(old_palette)

    def test_data_location_controls_fit_long_paths_and_localized_pages(self):
        old_language, old_style, old_palette = get_language(), self.app.styleSheet(), self.app.palette()
        engine = ThemeEngine()
        try:
            for language in available_languages():
                set_language(language)
                for dark in (False, True):
                    self.app.setPalette(engine.qt_palette(dark=dark))
                    self.app.setStyleSheet(engine.application_stylesheet(dark=dark))
                    page = SettingsPage(_view_model(MemorySettingsRepository()))
                    page.refresh()
                    page.set_data_directory(Path("D:/Application Data/WorkLogger/" + "Records/" * 6))
                    page.category_nav.set_category("data")
                    page.resize(880, 680)
                    page.show()
                    self.app.processEvents()
                    for control in (page.data_directory_input, page.open_data_directory_button):
                        self.assertTrue(control.parentWidget().rect().contains(control.geometry()))
                    self.assertTrue(page.open_data_directory_button.isEnabled())
                    self.capture(page, f"{language}-data-location-{dark}")
                    page.close()
        finally:
            set_language(old_language)
            self.app.setStyleSheet(old_style)
            self.app.setPalette(old_palette)

    def test_timesheet_files_render_multiperiod_unicode_content_and_page_headers(self):
        from datetime import datetime, timezone
        import tempfile
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QImage, QPainter
        from PySide6.QtPdf import QPdfDocument
        from worklogger.domain.reporting.timesheets import Timesheet
        from worklogger.domain.worklog.models import WorkLog, WorkType
        from worklogger.domain.projects.models import WorkContext
        from worklogger.infrastructure.export.timesheets import TimesheetXlsxExporter, TimesheetPdfExporter
        old_language = get_language()
        output = os.environ.get("WORKLOGGER_SCREENSHOTS")
        try:
            with tempfile.TemporaryDirectory() as temporary:
                directory = Path(output) if output else Path(temporary)
                directory.mkdir(parents=True, exist_ok=True)
                entries = []
                for number in range(1, 29):
                    day = date(2026, 10, number)
                    entries.extend((WorkLog(1, day, "09:00", "12:00", note="Planning and research / \u5de5\u4f5c\u5185\u5bb9 / \u52e4\u52d9",
                        context=WorkContext(project_label="Research", work_item_label="Review")),
                        WorkLog(1, day, "12:00", "13:00", work_type=WorkType.BREAK),
                        WorkLog(1, day, "14:00", "18:00", note="Implementation and validation")))
                snapshot = Timesheet(date(2026, 10, 1), date(2026, 10, 31), "Mary", datetime(2026, 11, 1, tzinfo=timezone.utc), 8, tuple(entries))
                for language in available_languages():
                    set_language(language)
                    pdf, xlsx = directory / f"{language}-timesheet.pdf", directory / f"{language}-timesheet.xlsx"
                    self.assertTrue(TimesheetPdfExporter().export_timesheet(pdf, snapshot).ok)
                    self.assertTrue(TimesheetXlsxExporter().export_timesheet(xlsx, snapshot).ok)
                    document = QPdfDocument()
                    self.assertEqual(document.load(str(pdf)), QPdfDocument.Error.None_)
                    try:
                        self.assertGreater(document.pageCount(), 1)
                        for index in (0, document.pageCount() - 1):
                            rendered = document.render(index, QSize(1400, 1000))
                            self.assertFalse(rendered.isNull())
                            opaque = QImage(rendered.size(), QImage.Format.Format_RGB32)
                            opaque.fill(0xFFFFFFFF)
                            painter = QPainter(opaque)
                            painter.drawImage(0, 0, rendered)
                            painter.end()
                            rendered = opaque
                            self.assertGreater(len({rendered.pixelColor(x, y).name() for x in range(10, 1380, 13) for y in range(10, 980, 13)}), 2)
                            if output:
                                self.assertTrue(rendered.save(str(directory / f"{language}-timesheet-page-{index + 1}.png")))
                        text = "\n".join(document.getAllText(index).text() for index in range(document.pageCount()))
                        self.assertIn("2026-10-31", "".join(text.split()))
                        self.assertIn("196.00", text)
                    finally:
                        document.close()
        finally:
            set_language(old_language)

    def test_local_context_settings_fit_model_limits_and_supported_languages(self):
        old_language, old_style, old_palette = get_language(), self.app.styleSheet(), self.app.palette()
        engine = ThemeEngine()
        try:
            for language in available_languages():
                set_language(language)
                for dark in (False, True):
                    self.app.setPalette(engine.qt_palette(dark=dark))
                    self.app.setStyleSheet(engine.application_stylesheet(dark=dark))
                    repository = MemorySettingsRepository()
                    repository.set(1, "local_model_context_tokens", "131072")
                    page = SettingsPage(_view_model(repository))
                    try:
                        page.refresh()
                        page.set_local_model_context_limit(32768)
                        page.category_nav.set_category("ai")
                        page.resize(880, 680)
                        page.show()
                        self.app.processEvents()
                        page.category_stack.currentWidget().ensureWidgetVisible(page.local_context_spin_box)
                        control = page.local_context_spin_box
                        form = next(layout for layout in control.parentWidget().findChildren(QFormLayout)
                                    if layout.labelForField(control) is not None)
                        caption = form.labelForField(control)
                        self.assertLessEqual(abs(caption.geometry().center().y() - control.geometry().center().y()), 1)
                        self.assertLessEqual(control.width(), 200)
                        self.assertLessEqual(control.height(), control.fontMetrics().height() + 12)
                        self.assertTrue(control.parentWidget().rect().contains(control.geometry()))
                        self.assertGreaterEqual(control.width(), control.fontMetrics().horizontalAdvance(control.text()) + 36)
                        self.assertEqual(control.value(), 32768)
                        self.assertIn("131072", page.local_context_status_label.text())
                        self.capture(page, f"{language}-context-{'dark' if dark else 'light'}")
                    finally:
                        page.hide()
                        page.deleteLater()
        finally:
            set_language(old_language)
            self.app.setPalette(old_palette)
            self.app.setStyleSheet(old_style)

    def test_display_name_actions_fit_read_edit_and_error_states(self):
        old_language, old_style, old_palette = get_language(), self.app.styleSheet(), self.app.palette()
        engine = ThemeEngine()
        try:
            for language in available_languages():
                set_language(language)
                for dark in (False, True):
                    self.app.setPalette(engine.qt_palette(dark=dark))
                    self.app.setStyleSheet(engine.application_stylesheet(dark=dark))
                    page = SettingsPage(_view_model(MemorySettingsRepository()))
                    try:
                        page.refresh()
                        page.set_account(User(1, "han_meimei", display_name="Mary"))
                        page.set_profile_available(True)
                        page.category_nav.set_category("account")
                        page.resize(880, 580)
                        page.show()
                        editor = page.display_name_editor
                        for mode in ("read", "edit", "error"):
                            if mode != "read":
                                editor.begin_editing()
                                editor.input.setText("Mary Han")
                            if mode == "error":
                                editor.set_error(_("Unable to save your display name. Your input has been retained."))
                            self.app.processEvents()
                            buttons = [button for button in (editor.edit_button, editor.save_button, editor.cancel_button)
                                       if button.isVisible()]
                            for button in buttons:
                                self.assertTrue(editor.rect().contains(button.geometry()))
                                self.assertEqual((button.width(), button.height()), (40, 40))
                                self.assertFalse(button.icon().pixmap(20, 20).isNull())
                                self.assertLess(editor.input.geometry().right(), button.geometry().left())
                            self.assertTrue(page.current_user_id_line_edit.isReadOnly())
                            self.capture(page, f"{language}-profile-{'dark' if dark else 'light'}-{mode}")
                    finally:
                        page.hide()
                        page.deleteLater()
        finally:
            set_language(old_language)
            self.app.setPalette(old_palette)
            self.app.setStyleSheet(old_style)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        configure_application_style()
        install_bundled_fonts()

    def test_report_and_unavailable_settings_fit_supported_languages(self):
        old_language, old_style, old_palette = get_language(), self.app.styleSheet(), self.app.palette()
        engine = ThemeEngine()

        class Model(ReportsViewModel):
            def load(self, kind, day):
                return Result.success(ReportEditorState(1, kind, date(2026, 5, 18), date(2026, 5, 24),
                    "# Sample report\n\nRecorded activities", saved=True, report_id=42))

        try:
            for language in available_languages():
                set_language(language)
                for dark in (False, True):
                    self.app.setPalette(engine.qt_palette(dark=dark))
                    self.app.setStyleSheet(engine.application_stylesheet(dark=dark))
                    page = ReportsPage(Model(), date(2026, 5, 20), job_runner=ImmediateJobRunner())
                    settings = SettingsPage(_view_model(MemorySettingsRepository()))
                    try:
                        page.refresh()
                        page.report_type_control.set_value("weekly")
                        page.show()
                        for width, height in ((740, 580), (960, 700)):
                            page.resize(width, height)
                            self.app.processEvents()
                            self.assertEqual((page.width(), page.height()), (width, height))
                            for button in (page.generate_button, page.export_current_button, page.save_button, page.templates_button):
                                self.assertLessEqual(button.fontMetrics().horizontalAdvance(button.text()) + 40, button.width())
                            self.assertTrue(page.history_panel.export_button.isHidden())
                            self.capture(page, f"{language}-report-{'dark' if dark else 'light'}-{width}")
                        settings.refresh()
                        settings.resize(880, 580)
                        settings.show()
                        for category in ("general", "ai", "network", "account"):
                            settings.category_nav.set_category(category)
                            self.app.processEvents()
                            scroll = settings.category_stack.currentWidget()
                            self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
                            self.capture(settings, f"{language}-{category}-{'dark' if dark else 'light'}")
                    finally:
                        page.hide()
                        page.deleteLater()
                        settings.hide()
                        settings.deleteLater()
        finally:
            set_language(old_language)
            self.app.setPalette(old_palette)
            self.app.setStyleSheet(old_style)

    def capture(self, widget, name):
        directory = os.environ.get("WORKLOGGER_SCREENSHOTS")
        if directory:
            target = Path(directory)
            target.mkdir(parents=True, exist_ok=True)
            self.assertTrue(widget.grab().save(str(target / f"{name}.png")))
