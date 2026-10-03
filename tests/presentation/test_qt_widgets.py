from __future__ import annotations

from datetime import date, datetime, timedelta
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTime, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QToolButton

from worklogger.presentation.theme import ThemeEngine
from worklogger.presentation.theme.fonts import _application_font
from worklogger.presentation.viewmodels import AutoRecordViewModel
from worklogger.presentation.viewmodels.calendar import CalendarDayCell, CalendarMonthViewState
from worklogger.presentation.viewmodels.stats import StatsPanelState
from worklogger.presentation.viewmodels.worklog_entry import WorkLogEntryForm
from worklogger.presentation.widgets.assets import application_icon_path, asset_path
from worklogger.presentation.widgets import (
    CalendarView,
    SegmentedControl,
    SettingsNav,
    SidebarWidget,
    StatsPanel,
    WorkLogEntryDraft,
    WorkLogEntryPanel,
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
    def test_auto_record_failure_uses_dialog_and_idle_status_is_empty(self) -> None:
        panel = WorkLogEntryPanel(compact=True)
        panel._refresh_auto_state()
        self.assertEqual(panel.auto_status_label.text(), "")
        self.assertTrue(panel.auto_status_label.isHidden())
        with patch("worklogger.presentation.widgets.worklog_entry.QMessageBox.warning") as notification:
            panel._auto_clock_out()
        notification.assert_called_once()
        self.assertIs(notification.call_args.args[0], panel)
        self.assertEqual(notification.call_args.args[1], "Auto Record")
        self.assertEqual(panel.auto_status_label.text(), "")

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

    def test_worklog_entry_panel_binds_form_and_emits_draft(self) -> None:
        panel = WorkLogEntryPanel()
        emitted: list[WorkLogEntryDraft] = []
        panel.save_requested.connect(emitted.append)
        form = WorkLogEntryForm(
            user_id=1,
            day=date(2026, 4, 20),
            start_time="22:00",
            end_time="09:00",
            break_hours=1.0,
            note="Night shift",
            work_type="normal",
            worked_hours=10.0,
            is_overnight=True,
            is_leave=False,
            dirty=True,
        )

        panel.set_form(form)

        self.assertEqual(panel.start_input.text(), "22:00")
        self.assertEqual(panel.end_input.text(), "09:00")
        self.assertEqual(panel.break_input.value(), 1.0)
        self.assertEqual(panel.note_input.toPlainText(), "Night shift")
        self.assertIn("10.0h", panel.hours_label.text())
        self.assertEqual(panel.status_label.text(), "Overnight")
        self.assertTrue(panel.save_button.isEnabled())

        panel.save_button.click()

        self.assertEqual(
            emitted,
            [
                WorkLogEntryDraft(
                    day=date(2026, 4, 20),
                    start_time="22:00",
                    end_time="09:00",
                    break_hours=1.0,
                    note="Night shift",
                    work_type="normal",
                )
            ],
        )

    def test_worklog_entry_panel_disables_save_for_invalid_form(self) -> None:
        panel = WorkLogEntryPanel()
        form = WorkLogEntryForm(
            user_id=1,
            day=date(2026, 4, 20),
            start_time="09:00",
            end_time=None,
            break_hours=1.0,
            note="",
            work_type="normal",
            worked_hours=0.0,
            is_overnight=False,
            is_leave=False,
            dirty=True,
            errors=("time_range_incomplete",),
        )

        panel.set_form(form)

        self.assertFalse(panel.save_button.isEnabled())
        self.assertEqual(panel.error_label.text(), "time_range_incomplete")

    def test_manual_clock_buttons_select_times_or_cancel_without_changing_draft(self) -> None:
        for compact in (False, True):
            with self.subTest(compact=compact):
                panel = WorkLogEntryPanel(compact=compact)
                panel.set_form(WorkLogEntryForm(
                    user_id=1, day=date(2026, 4, 20), start_time="0930", end_time="1830",
                    break_hours=1.0, note="Keep note", work_type="normal", worked_hours=8.0,
                    is_overnight=False, is_leave=False, dirty=False,
                ))
                drafts = []
                panel.draft_changed.connect(drafts.append)
                panel.show()
                try:
                    for field, title, initial, selected in (
                        (panel.start_input, "Start", QTime(9, 30), QTime(0, 0)),
                        (panel.end_input, "End", QTime(18, 30), QTime(23, 59)),
                    ):
                        clock = field.findChild(QToolButton)
                        QTest.mouseClick(clock, Qt.MouseButton.LeftButton)
                        self._app.processEvents()
                        dialog = next(child for child in panel.findChildren(QDialog) if child.isVisible())
                        self.assertEqual(dialog.windowTitle(), title)
                        self.assertEqual(dialog.time_input.displayFormat(), "HH:mm")
                        self.assertEqual(dialog.time_input.time(), initial)
                        self.assertFalse(dialog.windowIcon().isNull())
                        dialog.time_input.setTime(selected)
                        before = field.text()
                        QTest.keyClick(dialog, Qt.Key.Key_Escape)
                        self._app.processEvents()
                        self.assertEqual(field.text(), before)
                        self.assertEqual(drafts, [])
                        QTest.mouseClick(clock, Qt.MouseButton.LeftButton)
                        self._app.processEvents()
                        dialog = next(child for child in panel.findChildren(QDialog) if child.isVisible())
                        dialog.time_input.setTime(selected)
                        QTest.mouseClick(dialog.select_button, Qt.MouseButton.LeftButton)
                        self._app.processEvents()
                        self.assertEqual(field.text(), selected.toString("HH:mm"))
                        self.assertEqual(len(drafts), 1)
                        self.assertEqual(drafts[-1].note, "Keep note")
                        drafts.clear()
                    panel.start_input.setText("invalid")
                    drafts.clear()
                    panel.start_time_action.trigger()
                    self._app.processEvents()
                    dialog = next(child for child in panel.findChildren(QDialog) if child.isVisible())
                    self.assertTrue(dialog.time_input.time().isValid())
                    QTest.mouseClick(dialog.close_button, Qt.MouseButton.LeftButton)
                    self.assertEqual(panel.start_input.text(), "invalid")
                    self.assertEqual(drafts, [])
                finally:
                    panel.close()

    def test_worklog_entry_panel_auto_record_tab_applies_timer_values(self) -> None:
        current = datetime(2026, 4, 20, 9, 0)

        def clock() -> datetime:
            return current

        panel = WorkLogEntryPanel(
            auto_record_view_model=AutoRecordViewModel(
                clock=clock,
                default_break_hours=0.0,
            )
        )
        drafts: list[WorkLogEntryDraft] = []
        panel.draft_changed.connect(drafts.append)
        panel.set_form(
            WorkLogEntryForm(
                user_id=1,
                day=date(2026, 4, 20),
                start_time=None,
                end_time=None,
                break_hours=0.0,
                note="",
                work_type="normal",
                worked_hours=0.0,
                is_overnight=False,
                is_leave=False,
                dirty=False,
            )
        )

        panel.clock_in_button.click()

        self.assertEqual(panel.start_input.text(), "09:00")
        self.assertIn("Started", panel.clock_in_button.text())
        self.assertTrue(panel.break_button.isEnabled())

        panel.break_button.click()
        self.assertTrue(panel.auto_timer.isActive())
        current = datetime(2026, 4, 20, 9, 30)
        panel._refresh_auto_state()
        self.assertIn("30m", panel.break_button.text())

        panel.break_button.click()
        self.assertFalse(panel.auto_timer.isActive())
        self.assertEqual(panel.break_input.value(), 0.5)

        current = datetime(2026, 4, 20, 18, 0)
        panel.clock_out_button.click()

        self.assertEqual(panel.end_input.text(), "18:00")
        self.assertEqual(drafts[-1].start_time, "09:00")
        self.assertEqual(drafts[-1].end_time, "18:00")
        self.assertEqual(drafts[-1].break_hours, 0.5)

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
