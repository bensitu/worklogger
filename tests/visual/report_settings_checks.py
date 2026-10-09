"""Opt-in checks for report actions, record-based rest counts, and service availability."""

from datetime import date
import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from tests.presentation.test_settings_presentation import MemorySettingsRepository, _view_model
from tests.presentation.test_shell_pages import ReportsViewModel
from worklogger.infrastructure.i18n import get_language, available_languages, set_language
from worklogger.presentation.settings import SettingsPage
from worklogger.presentation.shell.reports_page import ReportsPage
from worklogger.presentation.theme import configure_application_style, install_bundled_fonts, ThemeEngine
from worklogger.domain.shared.result import Result
from worklogger.presentation.viewmodels.reports import ReportEditorState


class ReportSettingsLayoutChecks(unittest.TestCase):
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
                    page = ReportsPage(Model(), date(2026, 5, 20))
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
                        for category in ("ai", "network"):
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
