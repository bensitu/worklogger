from __future__ import annotations

from datetime import date, timedelta
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize
from PySide6.QtGui import QFont, QIcon, QPalette, QColor
from PySide6.QtWidgets import QApplication

from worklogger.presentation.theme import ThemeEngine
from worklogger.presentation.theme.fonts import _application_font
from worklogger.presentation.viewmodels.calendar import CalendarDayCell, CalendarMonthViewState
from worklogger.presentation.viewmodels.stats import StatsPanelState
from worklogger.presentation.widgets.assets import application_icon_path, asset_path
from worklogger.presentation.widgets.icons import ui_icon
from worklogger.presentation.widgets import (
    CalendarView,
    SegmentedControl,
    SettingsNav,
    SidebarWidget,
    StatsPanel,
)


def _app() -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        return existing
    return QApplication([])


def _calendar_state() -> CalendarMonthViewState:
    engine = ThemeEngine()
    start = date(2026, 3, 29)
    cells: list[CalendarDayCell] = []
    for index in range(42):
        day = start + timedelta(days=index)
        flags: set[str] = set()
        if day == date(2026, 4, 13):
            flags.add("today")
        if day == date(2026, 4, 20):
            flags.add("selected")
        if day.weekday() >= 5:
            flags.add("weekend")
        is_selected = day == date(2026, 4, 20)
        cells.append(
            CalendarDayCell(
                day=day,
                in_month=day.month == 4,
                text_lines=("20", "10.0h") if is_selected else (str(day.day),),
                style=engine.calendar_cell_style(flags),
                is_today=day == date(2026, 4, 13),
                is_selected=is_selected,
                is_weekend=day.weekday() >= 5,
                is_holiday=False,
                holiday_name="",
                work_type="normal",
                is_leave=False,
                worked_hours=10.0 if is_selected else 0.0,
                overtime_hours=2.0 if is_selected else 0.0,
                leave_hours=0.0,
                weekly_total_hours=10.0 if is_selected else 0.0,
                has_note_marker=is_selected,
                note_tooltip="Night shift",
                work_type_marker_color=None,
                show_overnight_marker=is_selected,
                event_count=2 if is_selected else 0,
            )
        )
    return CalendarMonthViewState(
        year=2026,
        month=4,
        week_headers=("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"),
        cells=tuple(cells),
        weekly_totals=(0.0, 0.0, 0.0, 10.0, 0.0, 0.0),
    )


class QtWidgetTests(unittest.TestCase):
    def test_icons_reuse_rendering_and_follow_palette_and_pixel_ratio(self) -> None:
        app = _app()
        original = app.palette()
        icon = ui_icon("clock")
        first = icon.pixmap(QSize(20, 20))
        self.assertFalse(first.isNull())
        self.assertEqual(first.cacheKey(), icon.pixmap(QSize(20, 20)).cacheKey())
        scaled = icon.pixmap(QSize(20, 20), 2.0)
        self.assertEqual(scaled.size(), QSize(40, 40))
        self.assertEqual(scaled.devicePixelRatio(), 2.0)
        changed = QPalette(original)
        changed.setColor(QPalette.ColorRole.ButtonText, QColor("#dc2626"))
        try:
            app.setPalette(changed)
            self.assertNotEqual(icon.pixmap(QSize(20, 20)).cacheKey(), first.cacheKey())
            self.assertFalse(icon.pixmap(QSize(20, 20), QIcon.Mode.Disabled).isNull())
        finally:
            app.setPalette(original)

    @classmethod
    def setUpClass(cls) -> None:
        cls._app = _app()

    def test_application_font_never_keeps_invalid_point_size(self) -> None:
        base_font = QFont("Sans Serif")
        base_font.setPixelSize(14)

        font = _application_font("Noto Sans", base_font)

        self.assertEqual(font.family(), "Noto Sans")
        self.assertGreater(font.pointSize(), 0)

    def test_calendar_view_binds_cells_and_emits_selected_day(self) -> None:
        view = CalendarView()
        state = _calendar_state()
        selected_days: list[date] = []
        view.day_selected.connect(selected_days.append)

        view.set_state(state)

        self.assertEqual(view.month_title.text(), "2026/04")
        self.assertEqual(len(view.day_buttons()), 42)
        self.assertEqual(view.week_total_labels()[3].text(), "10.0h")
        selected_button = next(
            button
            for button in view.day_buttons()
            if button.cell and button.cell.day == date(2026, 4, 20)
        )
        self.assertIn("20", selected_button.text())
        self.assertEqual(selected_button.property("style_key"), "selected")
        self.assertEqual(selected_button.toolTip(), "Night shift\n2 events")

        selected_button.click()

        self.assertEqual(selected_days, [date(2026, 4, 20)])

    def test_stats_panel_binds_values_and_progress(self) -> None:
        panel = StatsPanel()
        panel.set_state(
            StatsPanelState(
                total_hours=18.0,
                overtime_hours=2.0,
                work_days=2,
                leave_days=1,
                average_hours=9.0,
                monthly_target_hours=40.0,
                target_progress=0.45,
            )
        )

        self.assertEqual(panel.value_text("total_hours"), "18.0h")
        self.assertEqual(panel.value_text("overtime_hours"), "2.0h")
        self.assertEqual(panel.value_text("average_hours"), "9.0h")
        self.assertEqual(panel.value_text("work_days"), "2")
        self.assertEqual(panel.value_text("leave_days"), "1")
        self.assertEqual(panel.progress.value(), 45)

    def test_sidebar_segmented_control_and_settings_nav_track_active_state(self) -> None:
        sidebar = SidebarWidget(account_name="alice")
        routes: list[str] = []
        sidebar.route_changed.connect(routes.append)

        sidebar._buttons["analytics"].click()

        self.assertEqual(routes, ["analytics"])
        self.assertEqual(sidebar.active_route, "analytics")
        self.assertTrue(sidebar._buttons["analytics"].property("active"))

        segmented = SegmentedControl((("monthly", "Monthly"), ("annual", "Annual")))
        values: list[str] = []
        segmented.value_changed.connect(values.append)

        segmented.set_value("annual")

        self.assertEqual(values, ["annual"])
        self.assertEqual(segmented.value, "annual")

        settings_nav = SettingsNav((("appearance", "Appearance"), ("about", "About")))
        categories: list[str] = []
        settings_nav.category_changed.connect(categories.append)

        settings_nav.set_category("about")

        self.assertEqual(categories, ["about"])
        self.assertEqual(settings_nav.category, "about")

    def test_application_icon_path_uses_platform_specific_assets(self) -> None:
        windows_icon = application_icon_path("win32")
        macos_icon = application_icon_path("darwin")
        linux_icon = application_icon_path("linux")

        self.assertEqual(windows_icon.name, "worklogger.ico")
        self.assertEqual(macos_icon.name, "worklogger.icns")
        self.assertEqual(linux_icon.name, "worklogger.webp")
        self.assertTrue(windows_icon.exists())
        self.assertTrue(macos_icon.exists())
        self.assertTrue(linux_icon.exists())
        self.assertTrue(asset_path("icons/worklogger.webp").exists())
        self.assertTrue(asset_path("images/avatar.webp").exists())
        self.assertTrue(asset_path("images/avatar.webp").exists())
        self.assertTrue(asset_path("images/worklogger_login_image.webp").exists())
        self.assertTrue(asset_path("images/worklogger_login_image.webp").exists())


if __name__ == "__main__":
    unittest.main()
