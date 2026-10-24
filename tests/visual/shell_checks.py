from __future__ import annotations

from dataclasses import replace
from datetime import date
import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, qInstallMessageHandler
from PySide6.QtWidgets import QApplication, QToolButton, QPushButton

from worklogger.app.use_cases.analytics import GetAnalyticsBundleHandler, GetAnalyticsDashboardHandler
from worklogger.domain.worklog.models import WorkLog, EntryType
from worklogger.domain.auth.models import User
from worklogger.infrastructure.export import AnalyticsCsvExporter, AnalyticsPdfExporter
from worklogger.infrastructure.i18n import set_language, get_language, available_languages
from worklogger.presentation.auth.dialogs import LoginDialog
from worklogger.presentation.settings import SettingsPage
from worklogger.presentation.viewmodels import AnalyticsViewModel
from worklogger.presentation.widgets.assets import ASSETS_ROOT, application_icon_path
from worklogger.presentation.widgets.icons import ui_icon
from tests.presentation.test_app_window import MemoryWorkLogRepository, _window
from tests.presentation.test_settings_presentation import MemorySettingsRepository, _view_model
from tests.presentation.test_shell_pages import ReportsViewModel


class SampleSettingsWorkflow:
    def create_page(self, parent=None):
        page = SettingsPage(_view_model(MemorySettingsRepository()), parent)
        page.set_account(User(id=1, username="sample.user", is_admin=True))
        page.refresh()
        return page


def sample_window():
    records = MemoryWorkLogRepository()
    for index in range(1, 21):
        records.save(WorkLog(1, date(2026, 4, index), "09:00", "18:30", 1.0, "Feature work", EntryType.REMOTE if index % 3 == 0 else EntryType.NORMAL))
    model = AnalyticsViewModel(
        user_id=1, bundle_handler=GetAnalyticsBundleHandler(records),
        dashboard_handler=GetAnalyticsDashboardHandler(records),
        csv_exporter=AnalyticsCsvExporter(), pdf_exporter=AnalyticsPdfExporter(),
    )
    analytics = type("AnalyticsWorkflow", (), {"view_model": model})()
    reports = type("ReportsWorkflow", (), {"view_model": ReportsViewModel()})()
    return _window(records, account_name="Sample User", settings_workflow=SampleSettingsWorkflow(), analytics_workflow=analytics, reports_workflow=reports)


class ShellLayoutChecks(unittest.TestCase):
    def test_minimal_view_and_shared_settings_fit_supported_languages(self):
        from types import SimpleNamespace
        from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
        from PySide6.QtWidgets import QLabel, QSpinBox
        from tests.presentation.test_app_window import _entry_model
        from tests.background_samples import still_background_bytes
        from worklogger.domain.settings.background import BackgroundState
        from worklogger.domain.calendar.models import Holiday
        from worklogger.domain.shared.result import Result
        from worklogger.infrastructure.images.background import validate_background_data
        from tests.job_runner import ImmediateJobRunner
        from worklogger.presentation.settings import SettingsDialog
        from worklogger.presentation.settings_capabilities import SettingsCapabilities
        from worklogger.presentation.shell import MinimalView, MinimalViewConfig
        from worklogger.presentation.theme import ThemeEngine

        repository = MemoryWorkLogRepository()
        repository.save(WorkLog(1, date(2026, 4, 20), "09:00", "10:00", 0, "Recorded review"))
        media = BackgroundState(validate_background_data(still_background_bytes()), True, 50)
        service = SimpleNamespace(load=lambda: Result.success(media))
        projects = SimpleNamespace(catalog=lambda: Result.success(((), {})), recent_contexts=lambda: Result.success(()))

        class Holidays:
            def handle(self, query):
                return Result.success(tuple(Holiday(day, "Sample holiday") for day in
                    (date(2026, 9, 28), date(2026, 10, 12), date(2026, 11, 2)) if query.start_day <= day <= query.end_day))

        class Settings:
            def create_dialog(self, parent):
                settings = MemorySettingsRepository()
                settings.set(1, "minimal_mode", "1")
                dialog = SettingsDialog(_view_model(settings), parent)
                dialog.set_capabilities(SettingsCapabilities(minimal_view=True))
                dialog.set_account(User(1, "sample.user", True, display_name="Alex Morgan"))
                dialog.refresh()
                return dialog

        original_style, original_palette = self.app.styleSheet(), self.app.palette()
        try:
            for language in available_languages():
                set_language(language)
                for dark in (False, True):
                    workflow = Settings()
                    entry_model = _entry_model(repository)
                    entry_model.service.projects = projects
                    view = MinimalView(time_entry_view_model=entry_model, settings_workflow=workflow,
                        notes_workflow=SimpleNamespace(open=lambda *_args: None), job_runner=ImmediateJobRunner(),
                        holidays_handler=Holidays(), holiday_country="JP",
                        background_service=service, config=MinimalViewConfig(selected_day=date(2026, 4, 20),
                            today=date(2026, 4, 20), account_name="Alex Morgan", theme="green", dark=dark))
                    dialog = None
                    try:
                        view.refresh()
                        view.show()
                        self.app.processEvents()
                        self.assertEqual(view.width(), 680)
                        for width, height in ((640, 840), (680, 760), (900, 920)):
                            view.resize(width, height)
                            for mode in (0, 1):
                                view.entry_panel.time_tabs.setCurrentIndex(mode)
                                self.app.processEvents()
                                self.assertEqual((view.width(), view.height()), (width, height))
                                date_center = view.date_button.mapTo(view, view.date_button.rect().center())
                                self.assertLessEqual(abs(date_center.x() - view.rect().center().x()), 1)
                                today = view.today_button.rect().translated(view.today_button.mapTo(view, QPoint()))
                                previous = view.previous_button.rect().translated(view.previous_button.mapTo(view, QPoint()))
                                following = view.next_button.rect().translated(view.next_button.mapTo(view, QPoint()))
                                account = view.account_label.rect().translated(view.account_label.mapTo(view, QPoint()))
                                self.assertLess(today.right(), previous.left())
                                self.assertLess(previous.right(), date_center.x())
                                self.assertLess(date_center.x(), following.left())
                                self.assertLess(following.right(), account.left())
                                self.assertEqual(account.right(), width - 13)
                                self.assertTrue(view.account_label.alignment() & Qt.AlignmentFlag.AlignRight)
                                panel = view.entry_panel
                                caption = next(label for label in panel.findChildren(QLabel)
                                               if label.buddy() is panel.classification_button)
                                self.assertLess(panel.time_tabs.geometry().bottom(), caption.mapTo(panel, QPoint()).y())
                                if mode == 1:
                                    for button in (panel.clock_in_button, panel.clock_out_button, panel.break_button,
                                                   panel.discard_timer_button):
                                        self.assertTrue(panel.time_tabs.rect().contains(button.rect().translated(
                                            button.mapTo(panel.time_tabs, QPoint()))))
                                for field in (view.date_button, view.account_label, view.new_record_button,
                                              view.notes_button, view.settings_button, view.entry_panel.content_input,
                                              view.entry_panel.classification_button,
                                              view.entry_panel.save_button, view.records_scroll):
                                    bounds = field.rect().translated(field.mapTo(view, QPoint()))
                                    self.assertTrue(view.rect().contains(bounds), (language, dark, width, mode, field))
                                rendered = view._background_surface.grab().toImage()
                                self.assertNotEqual(rendered.pixelColor(2, 2).name(), ThemeEngine().palette("green", dark=dark).surface)
                                self.capture(view, f"minimal-{'dark' if dark else 'light'}-{width}-{mode}")
                        view.date_button.click()
                        self.app.processEvents()
                        popup = view.date_button.calendar.window()
                        self.assertTrue(popup.isVisible())
                        self.assertTrue(view.screen().availableGeometry().contains(popup.frameGeometry()))
                        self.assertEqual(view.date_button.calendar.locale().name(), language)
                        calendar = view.date_button.calendar
                        calendar.setCurrentPage(2026, 10)
                        self.app.processEvents()
                        self.capture(popup, f"minimal-calendar-{'dark' if dark else 'light'}")
                        calendar.findChild(QToolButton, "qt_calendar_yearbutton").click()
                        self.app.processEvents()
                        year_editor = calendar.findChild(QSpinBox, "qt_calendar_yearedit")
                        month_button = calendar.findChild(QToolButton, "qt_calendar_monthbutton")
                        self.assertTrue(year_editor.isVisible())
                        self.assertLessEqual(year_editor.width(), 90)
                        self.assertLessEqual(abs(year_editor.height() - month_button.height()), 2)
                        self.capture(popup, f"minimal-calendar-year-{'dark' if dark else 'light'}")
                        popup.hide()
                        dialog = workflow.create_dialog(view)
                        dialog.background_settings.bind(view.background_controller)
                        view.background_controller.reload()
                        dialog.show()
                        for category in dialog.page._category_pages:
                            dialog.category_nav.set_category(category)
                            self.app.processEvents()
                            self.assertEqual(dialog.category_stack.currentWidget().horizontalScrollBar().maximum(), 0)
                            close = dialog.close_button.rect().translated(dialog.close_button.mapTo(dialog, QPoint()))
                            self.assertLess(close.width(), dialog.width() / 3)
                            self.assertEqual(close.right(), dialog.width() - 25)
                            self.assertLess(dialog.page.geometry().bottom(), close.top())
                        self.capture(dialog, f"minimal-settings-{'dark' if dark else 'light'}")
                    finally:
                        if dialog is not None:
                            dialog.hide()
                            dialog.deleteLater()
                        view.close()
                        view.deleteLater()
                        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        finally:
            self.app.setPalette(original_palette)
            self.app.setStyleSheet(original_style)

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
                dialog.resize(880, 640)
                dialog.show()
                self.app.processEvents()
                self.assertEqual(dialog.hero_frame.width(), dialog.form_frame.width())
                self.assertFalse(dialog.hero_image_label.pixmap().isNull())
                for field in (dialog.username_input, dialog.password_input):
                    for button in field.findChildren(QToolButton):
                        self.assertTrue(field.rect().contains(button.geometry()), language)
                        self.assertLessEqual(abs(button.geometry().center().y() - field.rect().center().y()), 1)
                self.capture(dialog, "login")
                for width, height in ((600, 480), (420, 320)):
                    dialog.resize(width, height)
                    self.app.processEvents()
                    self.assertTrue(dialog.hero_frame.isHidden())
                    self.assertEqual(dialog.form_scroll.width(), dialog.width())
                    self.assertEqual(dialog.form_scroll.horizontalScrollBar().maximum(), 0)
                    for button in (dialog.login_button, dialog.microsoft_login_button, dialog.reset_password_button):
                        dialog.form_scroll.ensureWidgetVisible(button)
                        self.app.processEvents()
                        position = button.mapTo(dialog.form_scroll.viewport(), button.rect().center())
                        self.assertTrue(dialog.form_scroll.viewport().rect().contains(position), (language, width, button.text()))
                        self.assertGreaterEqual(button.width(), button.minimumSizeHint().width())
                    self.capture(dialog, f"login-{width}")
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
                sizes = ((880, 580), (1100, 700))
                for width, height in sizes:
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
                window.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == "__main__":
    unittest.main()
