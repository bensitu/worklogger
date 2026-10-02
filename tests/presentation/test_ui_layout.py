from __future__ import annotations

from dataclasses import replace
from datetime import date
import os
from pathlib import Path
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, qInstallMessageHandler
from PySide6.QtWidgets import QApplication, QLabel, QToolButton, QPushButton, QMessageBox

from worklogger.app.use_cases.analytics import GetAnalyticsBundleHandler, GetAnalyticsDashboardHandler
from worklogger.domain.worklog.models import WorkLog, WorkType
from worklogger.domain.auth.models import User
from worklogger.domain.shared.result import Result
from worklogger.domain.shared.errors import ValidationError
from worklogger.infrastructure.export import AnalyticsCsvExporter, AnalyticsPdfExporter
from worklogger.infrastructure.i18n import set_language, get_language, available_languages
from worklogger.presentation.auth.dialogs import LoginDialog
from worklogger.presentation.settings import SettingsPage
from worklogger.presentation.viewmodels import AnalyticsViewModel
from worklogger.presentation.theme import ThemeEngine, THEME_KEYS
from worklogger.presentation.widgets.assets import ASSETS_ROOT, application_icon_path
from worklogger.presentation.widgets.icons import ui_icon
from tests.presentation.test_app_window import MemoryWorkLogRepository, _window
from tests.presentation.test_settings_presentation import MemorySettingsRepository, _view_model
from tests.presentation.test_shell_pages import ReportsViewModel


class NativeSettingsWorkflow:
    def create_page(self, parent=None):
        page = SettingsPage(_view_model(MemorySettingsRepository()), parent)
        page.set_account(User(id=1, username="sample.user", is_admin=True))
        page.refresh()
        return page


def sample_window():
    records = MemoryWorkLogRepository()
    for index in range(1, 21):
        records.save(WorkLog(1, date(2026, 4, index), "09:00", "18:30", 1.0, "Feature work", WorkType.REMOTE if index % 3 == 0 else WorkType.NORMAL))
    model = AnalyticsViewModel(
        user_id=1, bundle_handler=GetAnalyticsBundleHandler(records),
        dashboard_handler=GetAnalyticsDashboardHandler(records),
        csv_exporter=AnalyticsCsvExporter(), pdf_exporter=AnalyticsPdfExporter(),
    )
    analytics = type("AnalyticsWorkflow", (), {"view_model": model})()
    reports = type("ReportsWorkflow", (), {"view_model": ReportsViewModel()})()
    return _window(records, account_name="Sample User", settings_workflow=NativeSettingsWorkflow(), analytics_workflow=analytics, reports_workflow=reports)


class UiLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        set_language("en_US")

    def capture(self, widget, name):
        directory = os.environ.get("WORKLOGGER_SCREENSHOTS")
        if directory:
            target = Path(directory)
            target.mkdir(parents=True, exist_ok=True)
            self.assertTrue(widget.grab().save(str(target / f"{get_language()}-{name}.png")))

    def test_login_assets_and_icons_render_without_invalid_fonts(self):
        warnings = []
        previous = qInstallMessageHandler(lambda kind, context, message: warnings.append(message))
        try:
            for language in available_languages():
                set_language(language)
                dialog = LoginDialog()
                dialog.show()
                self.app.processEvents()
                self.assertEqual(dialog.hero_frame.width(), dialog.form_frame.width())
                self.assertFalse(dialog.hero_image_label.pixmap().isNull())
                for field in (dialog.username_input, dialog.password_input):
                    for button in field.findChildren(QToolButton):
                        self.assertTrue(field.rect().contains(button.geometry()), language)
                        self.assertLessEqual(abs(button.geometry().center().y() - field.rect().center().y()), 1)
                self.capture(dialog, "login")
                dialog.close()
            for asset in (ASSETS_ROOT / "icons/ui").glob("*.svg"):
                rendered = ui_icon(asset.stem).pixmap(20, 20).toImage()
                self.assertTrue(any(rendered.pixelColor(x, y).alpha() > 0 for x in range(20) for y in range(20)), asset.name)
            for platform in ("win32", "darwin", "linux"):
                self.assertTrue(application_icon_path(platform).is_file())
            self.assertFalse(list(ASSETS_ROOT.rglob("*.avif")))
            self.assertFalse(any("Point size <= 0" in message for message in warnings), warnings)
        finally:
            qInstallMessageHandler(previous)

    def test_logout_exists_only_in_settings_account_and_keeps_shell_signal(self):
        window = sample_window()
        requests = []
        window.logout_requested.connect(lambda: requests.append(True))
        try:
            self.assertFalse(window.sidebar.findChildren(QPushButton, "logout_button"))
            self.assertFalse(hasattr(window, "logout_button"))
            self.assertTrue(window._switch_route("settings"))
            window.settings_page.category_nav.set_category("account")
            window.settings_page.logout_button.click()
            self.assertEqual(requests, [True])
            self.assertTrue(window.status_label.isHidden())
        finally:
            window.close()

    def test_shell_page_backgrounds_and_idle_status_across_themes(self):
        window = sample_window()
        window.show()
        try:
            for theme in THEME_KEYS:
                for dark in (False, True):
                    window._config = replace(window._config, theme=theme, dark=dark)
                    window.apply_theme()
                    self.assertTrue(window.refresh())
                    expected = ThemeEngine().palette(theme, dark=dark).surface
                    for route in ("calendar", "analytics", "reports"):
                        self.assertTrue(window._switch_route(route))
                        self.app.processEvents()
                        page = window.page_stack.currentWidget()
                        self.assertEqual(page.grab().toImage().pixelColor(4, 4).name(), expected, (theme, dark, route))
                        self.assertEqual(window.status_label.text(), "")
                        self.assertTrue(window.status_label.isHidden())
                        if route != "calendar":
                            self.assertEqual(page.status_label.text(), "")
                            self.assertTrue(page.status_label.isHidden())
                        else:
                            self.assertEqual(window.entry_panel.status_label.text(), "")
                            self.assertTrue(window.entry_panel.status_label.isHidden())
                            self.assertEqual(window.entry_panel.auto_status_label.text(), "")
                        if route == "reports":
                            body = page.history_panel.scroll_widget
                            self.assertEqual(body.grab().toImage().pixelColor(body.width() // 2, body.height() - 4).name(), expected)
        finally:
            window.close()

    def test_reports_and_analytics_feedback_uses_dialogs_without_footer(self):
        window = sample_window()
        try:
            with patch.object(QMessageBox, "information") as information, patch.object(QMessageBox, "warning") as warning:
                for route in ("reports", "analytics"):
                    self.assertTrue(window._switch_route(route))
                    page = window.page_stack.currentWidget()
                    model = page._view_model
                    if route == "reports":
                        page._save_current()
                        information.assert_called_with(page, "Reports", "Report saved.")
                        with patch.object(model, "export_markdown", create=True, return_value=Result.success(Path("qa.md"))):
                            self.assertTrue(page.export_markdown(Path("qa.md")))
                        information.assert_called_with(page, "Reports", "Exported Markdown")
                        method = "export_markdown"
                    else:
                        for method, message in (("export_csv", "Exported CSV"), ("export_pdf", "Exported PDF")):
                            with patch.object(model, method, return_value=Result.success(Path("qa-export"))):
                                self.assertTrue(getattr(page, method)(Path("qa-export")))
                            information.assert_called_with(page, "Analytics", message)
                        method = "export_csv"
                    with patch.object(model, method, create=True, return_value=Result.failure(ValidationError("export_failed", "export_failed"))):
                        self.assertFalse(getattr(page, method)(Path("qa-export")))
                    warning.assert_called_with(page, "Reports" if route == "reports" else "Analytics", "export_failed")
                    self.assertTrue(page.status_label.isHidden())
                    self.assertTrue(window.status_label.isHidden())
        finally:
            window.close()

    def test_shell_routes_fit_supported_window_sizes_and_themes(self):
        for language in available_languages():
            with self.subTest(language=language):
                set_language(language)
                self.check_shell_routes()

    def check_shell_routes(self):
        language = get_language()
        for dark in (False, True):
            window = sample_window()
            window._config = replace(window._config, dark=dark)
            window.apply_theme()
            self.assertTrue(window.refresh())
            window.show()
            try:
                for width, height in ((880, 580), (1100, 700)):
                    window.resize(width, height)
                    self.app.processEvents()
                    self.assertEqual((window.width(), window.height()), (width, height))
                    for route in ("calendar", "analytics", "reports", "settings"):
                        self.assertTrue(window._switch_route(route))
                        self.app.processEvents()
                        self.assertEqual((window.width(), window.height()), (width, height), route)
                        self.capture(window, f"{route}-{'dark' if dark else 'light'}-{width}")
                        if route == "settings":
                            for button in window.settings_page.category_nav._buttons.values():
                                for line in button.text().splitlines():
                                    self.assertLessEqual(button.fontMetrics().horizontalAdvance(line),
                                                         button.width() - button.iconSize().width() - 28,
                                                         (language, button.text(), width))
                            for category in window.settings_page._category_pages:
                                window.settings_page.category_nav.set_category(category)
                                self.app.processEvents()
                                scroll = window.settings_page.category_stack.currentWidget()
                                self.assertEqual(scroll.horizontalScrollBar().maximum(), 0, (language, category, width))
                                for button in scroll.findChildren(QPushButton):
                                    if not button.isVisible() or not button.text():
                                        continue
                                    required = button.fontMetrics().horizontalAdvance(button.text())
                                    if not button.icon().isNull():
                                        required += button.iconSize().width() + 4
                                    self.assertLessEqual(required, button.width() - 16, (language, category, button.text(), width))
                                self.capture(window, f"settings-{category}-{'dark' if dark else 'light'}-{width}")
                        elif route == "analytics":
                            self.assertTrue(window.analytics_page.period_combo.currentText())
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
