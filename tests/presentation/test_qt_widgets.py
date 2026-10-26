from __future__ import annotations

from datetime import date, timedelta
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtGui import QAccessible
from worklogger.presentation.widgets.switch_button import SwitchButton
from PySide6.QtWidgets import QApplication, QWidget

from worklogger.presentation.theme import ThemeEngine
from worklogger.presentation.viewmodels.calendar import CalendarDayCell, CalendarIndicatorSegment, CalendarMonthViewState
from worklogger.presentation.viewmodels.stats import StatsPanelState
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
                is_leave=False,
                worked_hours=10.0 if is_selected else 0.0,
                overtime_hours=2.0 if is_selected else 0.0,
                leave_hours=0.0,
                weekly_total_hours=10.0 if is_selected else 0.0,
                has_note_marker=is_selected,
                note_tooltip="Night shift",
                segments=(CalendarIndicatorSegment("normal", 10.0, engine.entry_type_color("normal")),) if is_selected else (),
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
    def test_switch_supports_keyboard_checked_state_and_accessible_name(self):
        parent = QWidget()
        switch = SwitchButton(parent=parent)
        switch.setAccessibleName("Public holidays")
        changes = []
        switch.toggled.connect(changes.append)
        QTest.keyClick(switch, Qt.Key.Key_Space)
        self.assertTrue(switch.is_checked())
        interface = QAccessible.queryAccessibleInterface(switch)
        self.assertEqual(interface.role(), QAccessible.Role.CheckBox)
        self.assertEqual(interface.text(QAccessible.Text.Name), "Public holidays")
        self.assertTrue(interface.state().checked)
        parent.setEnabled(False)
        self.assertFalse(switch.isEnabled())
        self.assertEqual(switch.cursor().shape(), Qt.CursorShape.ArrowCursor)
        QTest.keyClick(switch, Qt.Key.Key_Space)
        self.assertTrue(switch.is_checked())
        parent.setEnabled(True)
        self.assertEqual(switch.cursor().shape(), Qt.CursorShape.PointingHandCursor)
        switch.setEnabled(False)
        QTest.keyClick(switch, Qt.Key.Key_Space)
        self.assertTrue(switch.is_checked())
        switch.set_checked(False)
        self.assertEqual(changes, [True, False])
        parent.deleteLater()

    @classmethod
    def setUpClass(cls) -> None:
        cls._app = _app()

    def test_calendar_view_binds_cells_and_emits_selected_day(self) -> None:
        view = CalendarView()
        state = _calendar_state()
        selected_days: list[date] = []
        view.day_selected.connect(selected_days.append)

        view.set_state(state)

        self.assertEqual(view.month_title.text(), "2026/04")
        self.assertEqual(len(view.day_buttons()), 42)
        buttons = view.day_buttons()
        view.set_state(state)
        self.assertEqual(view.day_buttons(), buttons)
        self.assertEqual(view.week_total_labels()[3].text(), "10.0h")
        selected_button = next(
            button
            for button in view.day_buttons()
            if button.cell and button.cell.day == date(2026, 4, 20)
        )
        self.assertIn("20", selected_button.text())
        self.assertEqual(selected_button.property("style_key"), "selected")
        self.assertEqual(selected_button.toolTip(), "Overnight\nNight shift\n2 events")
        self.assertIn("2026", selected_button.accessibleName())
        self.assertEqual(selected_button.accessibleDescription(), selected_button.toolTip())

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
        segmented._buttons["monthly"].click()
        self.assertEqual(segmented.value, "monthly")
        self.assertTrue(segmented._buttons["monthly"].isChecked())
        self.assertFalse(segmented._buttons["annual"].isChecked())
        segmented._buttons["monthly"].click()
        self.assertTrue(segmented._buttons["monthly"].isChecked())
        self.assertEqual(values, ["annual", "monthly"])

        settings_nav = SettingsNav((("appearance", "Appearance"), ("about", "About")))
        categories: list[str] = []
        settings_nav.category_changed.connect(categories.append)

        settings_nav.set_category("about")

        self.assertEqual(categories, ["about"])
        self.assertEqual(settings_nav.category, "about")

if __name__ == "__main__":
    unittest.main()
