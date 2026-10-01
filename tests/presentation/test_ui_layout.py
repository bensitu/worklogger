from __future__ import annotations

from dataclasses import replace
from datetime import date
import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, qInstallMessageHandler
from PySide6.QtWidgets import QApplication, QLabel

from worklogger.app.use_cases.analytics import GetAnalyticsBundleHandler, GetAnalyticsDashboardHandler
from worklogger.domain.worklog.models import WorkLog, WorkType
from worklogger.infrastructure.export import AnalyticsCsvExporter, AnalyticsPdfExporter
from worklogger.infrastructure.i18n import set_language
from worklogger.presentation.auth.dialogs import LoginDialog
from worklogger.presentation.settings import SettingsPage
from worklogger.presentation.viewmodels import AnalyticsViewModel
from worklogger.presentation.widgets.assets import ASSETS_ROOT, application_icon_path
from worklogger.presentation.widgets.icons import ui_icon
from tests.presentation.test_app_window import MemoryWorkLogRepository, _window
from tests.presentation.test_settings_presentation import MemorySettingsRepository, _view_model
from tests.presentation.test_shell_pages import ReportsViewModel


class NativeSettingsWorkflow:
    def create_page(self, parent=None):
        page = SettingsPage(_view_model(MemorySettingsRepository()), parent)
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
            self.assertTrue(widget.grab().save(str(target / f"{name}.png")))

    def test_login_assets_and_icons_render_without_invalid_fonts(self):
        warnings = []
        previous = qInstallMessageHandler(lambda kind, context, message: warnings.append(message))
        try:
            dialog = LoginDialog()
            dialog.show()
            self.app.processEvents()
            self.assertEqual(dialog.hero_frame.width(), dialog.form_frame.width())
            self.assertFalse(dialog.hero_image_label.pixmap().isNull())
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

    def test_shell_routes_fit_supported_window_sizes_and_themes(self):
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
                            for category in window.settings_page._category_pages:
                                window.settings_page.category_nav.set_category(category)
                                self.app.processEvents()
                                self.capture(window, f"settings-{category}-{'dark' if dark else 'light'}-{width}")
                        elif route == "analytics":
                            self.assertTrue(window.analytics_page.period_combo.currentText())
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
