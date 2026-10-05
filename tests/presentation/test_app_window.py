from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTime, QTimer, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QTimeEdit, QWidget

from worklogger.app.queries.work_log_queries import GetMonthRecordsQuery
from worklogger.app.use_cases.calendar import GetCalendarEventsForRangeHandler
from worklogger.app.use_cases.work_logs import (
    GetMonthRecordsHandler,
    GetWorkLogHandler,
    SaveWorkLogHandler,
)
from worklogger.domain.calendar.models import CalendarEvent
from worklogger.domain.calendar.repositories import CalendarEventRepository
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkLog
from worklogger.presentation.shell import (
    AppWindow,
    AppWindowConfig,
    MinimalView,
    MinimalViewConfig,
)
from worklogger.presentation.viewmodels import (
    AutoRecordViewModel,
    CalendarDisplayOptions,
    CalendarViewModel,
    StatsPanelViewModel,
    WorkLogEntryViewModel,
)


def _app() -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        return existing
    return QApplication([])


class MemoryWorkLogRepository:
    def __init__(self) -> None:
        self.records: dict[tuple[int, date], WorkLog] = {}

    def get_for_day(self, user_id: int, day: date) -> WorkLog | None:
        return self.records.get((user_id, day))

    def list_for_month(self, user_id: int, year: int, month: int) -> tuple[WorkLog, ...]:
        return tuple(
            record
            for (record_user_id, record_day), record in sorted(self.records.items())
            if record_user_id == user_id
            and record_day.year == year
            and record_day.month == month
        )

    def list_all(self, user_id: int) -> tuple[WorkLog, ...]:
        return tuple(
            record
            for (record_user_id, _day), record in sorted(self.records.items())
            if record_user_id == user_id
        )

    def save(self, work_log: WorkLog, *, expected_note: str | None = None) -> None:
        self.records[(work_log.user_id, work_log.day)] = work_log

    def remove(self, user_id: int, day: date) -> None:
        self.records.pop((user_id, day), None)


class MemoryCalendarRepository(CalendarEventRepository):
    def __init__(self, events: tuple[CalendarEvent, ...] = ()) -> None:
        self.events = events

    def list_for_day(self, user_id: int, day: date) -> tuple[CalendarEvent, ...]:
        return tuple(
            event
            for event in self.events
            if event.user_id == user_id and event.day == day
        )

    def list_for_range(
        self,
        user_id: int,
        start_day: date,
        end_day: date,
    ) -> tuple[CalendarEvent, ...]:
        return tuple(
            event
            for event in self.events
            if event.user_id == user_id and start_day <= event.day <= end_day
        )

    def replace_all(self, user_id: int, events: tuple[CalendarEvent, ...]) -> int:
        self.events = tuple(event for event in events if event.user_id == user_id)
        return len(self.events)

    def clear(self, user_id: int) -> None:
        self.events = tuple(event for event in self.events if event.user_id != user_id)


class FailingMonthRecordsHandler:
    def handle(self, query: GetMonthRecordsQuery) -> Result[tuple[WorkLog, ...]]:
        return Result.failure(ValidationError("month_failed", "month_failed"))


def _window(
    repository: MemoryWorkLogRepository,
    *,
    account_name: str | None = None,
    confirm_discard_changes: Callable[[], bool] | None = None,
    month_handler: object | None = None,
    settings_workflow: object | None = None,
    quick_logs_workflow: object | None = None,
    analytics_workflow: object | None = None,
    ai_assist_workflow: object | None = None,
    notes_workflow: object | None = None,
    reports_workflow: object | None = None,
    residency_controller: object | None = None,
) -> AppWindow:
    month_records = month_handler or GetMonthRecordsHandler(repository)
    calendar_view_model = CalendarViewModel(
        user_id=1,
        month_records_handler=month_records,
        calendar_events_handler=GetCalendarEventsForRangeHandler(
            MemoryCalendarRepository(
                (
                    CalendarEvent(
                        id=1,
                        user_id=1,
                        day=date(2026, 4, 20),
                        summary="Planning",
                    ),
                )
            )
        ),
    )
    return AppWindow(
        calendar_view_model=calendar_view_model,
        worklog_entry_view_model=WorkLogEntryViewModel(
            user_id=1,
            get_handler=GetWorkLogHandler(repository),
            save_handler=SaveWorkLogHandler(repository),
            default_break_hours=1.0,
        ),
        stats_panel_view_model=StatsPanelViewModel(
            user_id=1,
            month_records_handler=month_records,
        ),
        config=AppWindowConfig(
            selected_day=date(2026, 4, 20),
            today=date(2026, 4, 13),
            account_name=account_name,
            confirm_discard_changes=confirm_discard_changes,
            monthly_target_hours=40.0,
            calendar_options=CalendarDisplayOptions(standard_work_hours=8.0),
            holidays={date(2026, 4, 29): "Holiday"},
        ),
        settings_workflow=settings_workflow,
        quick_logs_workflow=quick_logs_workflow,
        analytics_workflow=analytics_workflow,
        ai_assist_workflow=ai_assist_workflow,
        notes_workflow=notes_workflow,
        reports_workflow=reports_workflow,
        residency_controller=residency_controller,
    )


class AppWindowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.information = self.enterContext(patch("worklogger.presentation.shell.app_window.QMessageBox.information"))
        self.warning = self.enterContext(patch("worklogger.presentation.shell.app_window.QMessageBox.warning"))

    @classmethod
    def setUpClass(cls) -> None:
        cls._app = _app()

    def test_app_window_refreshes_components_and_navigates_months(self) -> None:
        window = _window(MemoryWorkLogRepository())

        self.assertTrue(window.refresh())
        self.assertEqual(window.selected_day, date(2026, 4, 20))
        self.assertEqual(window.current_month, date(2026, 4, 1))
        self.assertEqual(window.calendar_view.month_title.text(), "2026/04")
        self.assertEqual(window.status_label.text(), "")
        self.assertTrue(window.status_label.isHidden())
        self.assertEqual(window.entry_panel.start_input.text(), "")
        self.assertFalse(window.entry_panel.save_button.isEnabled())

        window.next_month_button.click()

        self.assertEqual(window.current_month, date(2026, 5, 1))
        self.assertEqual(window.calendar_view.month_title.text(), "2026/05")

        window.today_button.click()

        self.assertEqual(window.selected_day, date(2026, 4, 13))
        self.assertEqual(window.current_month, date(2026, 4, 1))

    def test_app_window_saves_entry_and_refreshes_calendar_and_stats(self) -> None:
        repository = MemoryWorkLogRepository()
        window = _window(repository)
        self.assertTrue(window.refresh())

        window.entry_panel.start_input.setText("0900")
        window.entry_panel.end_input.setText("1800")
        window.entry_panel.note_input.setPlainText("Focused work")

        self.assertTrue(window.entry_panel.save_button.isEnabled())
        window.entry_panel.save_button.click()

        saved = repository.get_for_day(1, date(2026, 4, 20))
        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertEqual(saved.start_time, "09:00")
        self.assertEqual(saved.end_time, "18:00")
        self.assertEqual(saved.note, "Focused work")
        self.assertEqual(window.status_label.text(), "Saved")
        self.assertTrue(window.status_label.isHidden())
        self.information.assert_not_called()
        self.assertEqual(window.stats_panel.value_text("total_hours"), "8.0h")
        self.assertIn("8.0h", window.calendar_view.week_total_labels()[3].text())
        selected = next(
            button
            for button in window.calendar_view.day_buttons()
            if button.cell and button.cell.day == date(2026, 4, 20)
        )
        self.assertIn("8.0h", selected.text())

    def test_manual_time_typing_preserves_text_and_saves_normalized_times(self) -> None:
        for minimal in (False, True):
            for start, end, expected_start, expected_end in (
                ("0930", "1830", "09:30", "18:30"),
                ("09:30", "18:30", "09:30", "18:30"),
                ("9", "18", "09:00", "18:00"),
                ("2200", "0730", "22:00", "07:30"),
            ):
                with self.subTest(minimal=minimal, start=start):
                    repository = MemoryWorkLogRepository()
                    if minimal:
                        window = MinimalView(
                            worklog_entry_view_model=WorkLogEntryViewModel(
                                user_id=1,
                                get_handler=GetWorkLogHandler(repository),
                                save_handler=SaveWorkLogHandler(repository),
                            ),
                            config=MinimalViewConfig(selected_day=date(2026, 4, 20)),
                        )
                    else:
                        window = _window(repository)
                    window.show()
                    try:
                        self.assertTrue(window.refresh())
                        panel = window.entry_panel
                        for field, text in ((panel.start_input, start), (panel.end_input, end)):
                            field.setFocus()
                            for index, character in enumerate(text, 1):
                                QTest.keyClicks(field, character)
                                self.assertEqual(field.text(), text[:index])
                                self.assertEqual(field.cursorPosition(), index)
                        panel.note_toggle_button.setChecked(True)
                        panel.note_input.setFocus()
                        QTest.keyClicks(panel.note_input, "Work note")
                        self.assertEqual(panel.note_input.toPlainText(), "Work note")
                        self.assertTrue(panel.save_button.isEnabled())
                        self.assertTrue(window.has_unsaved_changes)
                        panel.save_button.click()
                        saved = repository.get_for_day(1, date(2026, 4, 20))
                        self.assertEqual((saved.start_time, saved.end_time), (expected_start, expected_end))
                        self.assertEqual(saved.note, "Work note")
                        self.assertEqual((panel.start_input.text(), panel.end_input.text()), (expected_start, expected_end))
                        self.assertFalse(window.has_unsaved_changes)
                    finally:
                        window.close()

    def test_auto_record_keeps_break_timer_and_saves_elapsed_time(self) -> None:
        repository = MemoryWorkLogRepository()
        current = datetime(2026, 4, 20, 9, 0)
        window = _window(repository, confirm_discard_changes=lambda: True)
        panel = window.entry_panel
        panel._auto_record_view_model = AutoRecordViewModel(clock=lambda: current)
        try:
            self.assertTrue(window.refresh())
            panel.time_tabs.setCurrentIndex(1)
            panel.clock_in_button.click()
            current = datetime(2026, 4, 20, 10, 0)
            panel.break_button.click()
            self.assertTrue(panel._auto_record_view_model.state().break_active)
            self.assertTrue(panel.auto_timer.isActive())
            current = datetime(2026, 4, 20, 10, 30)
            panel._refresh_auto_state()
            self.assertIn("90m", panel.break_button.text())
            panel.break_button.click()
            self.assertFalse(panel.auto_timer.isActive())
            self.assertEqual(panel.break_input.value(), 1.5)
            panel.quick_break_button.click()
            self.assertEqual(panel.break_input.value(), 1.75)
            current = datetime(2026, 4, 20, 18, 0)
            panel.clock_out_button.click()
            self.assertTrue(panel.save_button.isEnabled())
            panel.save_button.click()
            record = repository.get_for_day(1, date(2026, 4, 20))
            self.assertEqual((record.start_time, record.end_time), ("09:00", "18:00"))
            self.assertEqual(record.break_hours, 1.75)
            self.assertEqual(record.worked_hours(), 7.25)
            self.information.assert_not_called()
        finally:
            window.close()

    def test_manual_clock_selection_updates_preview_and_saves_record(self) -> None:
        repository = MemoryWorkLogRepository()
        window = _window(repository, confirm_discard_changes=lambda: True)
        window.show()
        try:
            self.assertTrue(window.refresh())
            panel = window.entry_panel
            for action, time in ((panel.start_time_action, QTime(9, 15)), (panel.end_time_action, QTime(18, 30))):
                action.trigger()
                self._app.processEvents()
                dialog = next(child for child in panel.findChildren(QDialog) if child.isVisible())
                dialog.time_input.setTime(QTime(0, 0))
                dialog.time_input.setFocus()
                dialog.time_input.setSelectedSection(QTimeEdit.Section.HourSection)
                QTest.keyClicks(dialog.time_input, f"{time.hour():02d}")
                dialog.time_input.setSelectedSection(QTimeEdit.Section.MinuteSection)
                QTest.keyClicks(dialog.time_input, f"{time.minute():02d}")
                QTest.keyClick(dialog.time_input, Qt.Key.Key_Return)
                self._app.processEvents()
                self.assertFalse(any(child.isVisible() for child in panel.findChildren(QDialog)))
            self.assertEqual(panel.start_input.text(), "09:15")
            self.assertEqual(panel.end_input.text(), "18:30")
            self.assertAlmostEqual(panel._form.worked_hours, 8.25)
            self.assertTrue(panel.save_button.isEnabled())
            self.assertTrue(window.has_unsaved_changes)
            panel.save_button.click()
            record = repository.get_for_day(1, date(2026, 4, 20))
            self.assertEqual((record.start_time, record.end_time), ("09:15", "18:30"))
            self.assertFalse(window.has_unsaved_changes)
        finally:
            window.close()

    def test_manual_time_editing_keeps_cursor_and_invalid_drafts(self) -> None:
        repository = MemoryWorkLogRepository()
        repository.save(WorkLog(1, date(2026, 4, 20), "09:00", "18:00", 1.0))
        window = _window(repository, confirm_discard_changes=lambda: False)
        window.show()
        try:
            self.assertTrue(window.refresh())
            panel = window.entry_panel
            panel.start_input.setFocus()
            panel.start_input.setSelection(3, 2)
            QTest.keyClicks(panel.start_input, "30")
            self.assertEqual(panel.start_input.text(), "09:30")
            self.assertEqual(panel.start_input.cursorPosition(), 5)
            panel.start_input.setCursorPosition(2)
            QTest.keyClick(panel.start_input, Qt.Key.Key_Backspace)
            self.assertEqual(panel.start_input.text(), "0:30")
            self.assertEqual(panel.start_input.cursorPosition(), 1)
            QTest.keyClicks(panel.start_input, "9")
            self.assertEqual(panel.start_input.text(), "09:30")
            self.assertEqual(panel.start_input.cursorPosition(), 2)
            for field, text in ((panel.start_input, "25:00"), (panel.end_input, "26:00")):
                field.selectAll()
                QTest.keyClicks(field, text)
                self.assertEqual(field.text(), text)
            self.assertFalse(panel.save_button.isEnabled())
            self.assertTrue(window.has_unsaved_changes)
            self.assertFalse(window.select_day(date(2026, 4, 21)))
            panel._emit_save_requested()
            self.assertEqual(panel.start_input.text(), "25:00")
            self.assertEqual(panel.end_input.text(), "26:00")
            self.assertEqual(repository.get_for_day(1, date(2026, 4, 20)).start_time, "09:00")
            self.warning.assert_called_once()
            self.assertEqual(self.warning.call_args.args[2], "Enter valid start and end times in HH:mm format.")
            self.assertEqual(panel._form.errors, ("time_range_invalid",))
            panel.start_input.setText("09:30")
            panel.end_input.setText("18:30")
            self.assertTrue(panel.save_button.isEnabled())
            panel.save_button.click()
        finally:
            window.close()

    def test_app_window_displays_handler_errors(self) -> None:
        window = _window(
            MemoryWorkLogRepository(),
            month_handler=FailingMonthRecordsHandler(),
        )

        self.assertFalse(window.refresh())

        self.assertIsNotNone(window.last_error)
        assert window.last_error is not None
        self.assertEqual(window.last_error.code, "month_failed")
        self.assertEqual(window.status_label.text(), "The operation could not be completed. Please try again.")
        self.assertTrue(window.status_label.isHidden())
        self.warning.assert_called_once_with(window, "WorkLogger", "The operation could not be completed. Please try again.")

    def test_app_window_exposes_account_label_and_logout_signal(self) -> None:
        window = _window(MemoryWorkLogRepository(), account_name="alice")
        logouts: list[bool] = []
        window.logout_requested.connect(lambda: logouts.append(True))

        self.assertEqual(window.account_label.text(), "Signed in: alice")
        self.assertFalse(hasattr(window, "logout_button"))

        window._request_logout()

        self.assertEqual(logouts, [True])
        self.assertEqual(window.status_label.text(), "Logout requested")

    def test_app_window_opens_settings_workflow_when_available(self) -> None:
        class FakeSettingsWorkflow:
            def __init__(self) -> None:
                self.opened: list[object] = []

            def open(self, parent=None):
                self.opened.append(parent)
                return None

        workflow = FakeSettingsWorkflow()
        window = _window(
            MemoryWorkLogRepository(),
            account_name="alice",
            settings_workflow=workflow,
        )

        self.assertFalse(window.settings_button.isHidden())
        window.settings_button.click()

        self.assertEqual(workflow.opened, [window])
        self.assertEqual(window.status_label.text(), "")
        self.assertTrue(window.status_label.isHidden())


    def test_app_window_uses_native_settings_page_when_available(self) -> None:
        class FakeSettingsPage(QWidget):
            logout_requested = Signal()

            def __init__(self) -> None:
                super().__init__()
                self.refreshes = 0

            def refresh(self) -> bool:
                self.refreshes += 1
                return True

        class FakeSettingsWorkflow:
            def __init__(self) -> None:
                self.created: list[tuple[object, FakeSettingsPage]] = []
                self.opened: list[object] = []

            def create_page(self, parent=None):
                page = FakeSettingsPage()
                self.created.append((parent, page))
                return page

            def open(self, parent=None):
                self.opened.append(parent)
                return None

        workflow = FakeSettingsWorkflow()
        window = _window(
            MemoryWorkLogRepository(),
            account_name="alice",
            settings_workflow=workflow,
        )
        logouts: list[bool] = []
        window.logout_requested.connect(lambda: logouts.append(True))

        window.settings_button.click()
        workflow.created[0][1].logout_requested.emit()

        self.assertEqual(workflow.created[0][0], window)
        self.assertIs(window.page_stack.currentWidget(), workflow.created[0][1])
        self.assertEqual(workflow.opened, [])
        self.assertEqual(workflow.created[0][1].refreshes, 1)
        self.assertEqual(logouts, [True])

    def test_app_window_opens_secondary_workflows_when_available(self) -> None:
        class FakeDayWorkflow:
            def __init__(self) -> None:
                self.opened: list[tuple[date, object]] = []

            def open(self, day, parent=None):
                self.opened.append((day, parent))
                return None

        quick_logs = FakeDayWorkflow()
        analytics = FakeDayWorkflow()
        ai_assist = FakeDayWorkflow()
        notes = FakeDayWorkflow()
        reports = FakeDayWorkflow()
        window = _window(
            MemoryWorkLogRepository(),
            account_name="alice",
            quick_logs_workflow=quick_logs,
            analytics_workflow=analytics,
            ai_assist_workflow=ai_assist,
            notes_workflow=notes,
            reports_workflow=reports,
        )

        self.assertFalse(hasattr(window, "more_actions_button"))
        self.assertIsNone(window.findChild(QWidget, "calendar_more_actions_button"))
        self.assertTrue(window.calendar_page.add_entry_button.isEnabled())
        self.assertFalse(window.analytics_button.isHidden())
        self.assertFalse(window.reports_button.isHidden())
        menu = window.calendar_page.add_entry_button.menu()
        actions = menu.actions()
        self.assertEqual([action.text() for action in actions], ["Quick Log", "Notes", "AI Assist"])
        opened = []
        menu.aboutToShow.connect(lambda: opened.append(True))
        menu.aboutToShow.connect(lambda: QTimer.singleShot(0, menu.close))
        window.show()
        self._app.processEvents()
        QTest.mouseClick(window.calendar_page.add_entry_button, Qt.MouseButton.LeftButton)
        self._app.processEvents()
        self.assertEqual(opened, [True])
        self.assertEqual(quick_logs.opened + notes.opened + ai_assist.opened, [])
        actions[0].trigger()
        window.analytics_button.click()
        actions[2].trigger()
        actions[1].trigger()
        window.reports_button.click()

        self.assertEqual(quick_logs.opened, [(date(2026, 4, 20), window)])
        self.assertEqual(analytics.opened, [(date(2026, 4, 20), window)])
        self.assertEqual(ai_assist.opened, [(date(2026, 4, 20), window)])
        self.assertEqual(notes.opened, [(date(2026, 4, 20), window)])
        self.assertEqual(reports.opened, [(date(2026, 4, 20), window)])
        window.close()

    def test_add_entry_is_disabled_without_available_workflows(self) -> None:
        window = _window(MemoryWorkLogRepository())
        self.assertFalse(window.calendar_page.add_entry_button.isEnabled())
        self.assertTrue(window.calendar_page.add_entry_button.menu().isEmpty())
        window.close()

    def test_app_window_blocks_day_navigation_when_dirty_prompt_is_cancelled(self) -> None:
        window = _window(
            MemoryWorkLogRepository(),
            confirm_discard_changes=lambda: False,
        )
        self.assertTrue(window.refresh())

        window.entry_panel.start_input.setText("0900")
        changed = window.select_day(date(2026, 4, 21))

        self.assertFalse(changed)
        self.assertTrue(window.has_unsaved_changes)
        self.assertEqual(window.selected_day, date(2026, 4, 20))
        self.assertEqual(window.status_label.text(), "Unsaved changes")

    def test_app_window_discards_dirty_entry_when_prompt_is_confirmed(self) -> None:
        confirmations: list[bool] = []

        def confirm() -> bool:
            confirmations.append(True)
            return True

        window = _window(
            MemoryWorkLogRepository(),
            confirm_discard_changes=confirm,
        )
        self.assertTrue(window.refresh())

        window.entry_panel.start_input.setText("0900")
        changed = window.select_day(date(2026, 4, 21))

        self.assertTrue(changed)
        self.assertEqual(confirmations, [True])
        self.assertFalse(window.has_unsaved_changes)
        self.assertEqual(window.selected_day, date(2026, 4, 21))

    def test_app_window_blocks_logout_when_dirty_prompt_is_cancelled(self) -> None:
        window = _window(
            MemoryWorkLogRepository(),
            account_name="alice",
            confirm_discard_changes=lambda: False,
        )
        logouts: list[bool] = []
        window.logout_requested.connect(lambda: logouts.append(True))
        self.assertTrue(window.refresh())

        window.entry_panel.start_input.setText("0900")
        window._request_logout()

        self.assertEqual(logouts, [])
        self.assertTrue(window.has_unsaved_changes)
        self.assertEqual(window.status_label.text(), "Unsaved changes")

    def test_app_window_hides_on_close_when_residency_is_enabled(self) -> None:
        class FakeResidencyController:
            quit_requested = False

            def __init__(self) -> None:
                self.attached = False
                self.refreshed = 0

            def attach(self, parent, *, open_callback=None, quit_callback=None):
                self.attached = parent is not None

            def refresh(self):
                self.refreshed += 1
                return None

            def should_keep_resident(self) -> bool:
                return True

            def request_quit(self) -> None:
                self.quit_requested = True

        controller = FakeResidencyController()
        window = _window(
            MemoryWorkLogRepository(),
            account_name="alice",
            residency_controller=controller,
        )
        event = QCloseEvent()

        window.closeEvent(event)

        self.assertTrue(controller.attached)
        self.assertFalse(event.isAccepted())

    def test_minimal_view_saves_entry_and_navigates_days(self) -> None:
        repository = MemoryWorkLogRepository()
        view = MinimalView(
            worklog_entry_view_model=WorkLogEntryViewModel(
                user_id=1,
                get_handler=GetWorkLogHandler(repository),
                save_handler=SaveWorkLogHandler(repository),
            ),
            config=MinimalViewConfig(
                selected_day=date(2026, 4, 20),
                today=date(2026, 4, 13),
                account_name="alice",
            ),
        )

        self.assertTrue(view.refresh())
        self.assertEqual(view.date_label.text(), "2026-04-20")
        self.assertEqual(view.account_label.text(), "Signed in: alice")

        self.assertTrue(view.status_label.isHidden())
        view.entry_panel.start_input.setText("25:00")
        self.assertTrue(view.status_label.text())
        self.assertFalse(view.status_label.isHidden())
        view.entry_panel.start_input.setText("0900")
        view.entry_panel.end_input.setText("1800")
        self.assertEqual(view.status_label.text(), "")
        self.assertTrue(view.status_label.isHidden())
        view.entry_panel.save_button.click()

        saved = repository.get_for_day(1, date(2026, 4, 20))
        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertEqual(saved.start_time, "09:00")
        self.assertEqual(view.status_label.text(), "")
        self.assertTrue(view.status_label.isHidden())

        self.assertTrue(view.next_day())
        self.assertEqual(view.selected_day, date(2026, 4, 21))
        self.assertEqual(view.date_label.text(), "2026-04-21")

    def test_minimal_view_opens_settings_workflow_when_available(self) -> None:
        class FakeSettingsWorkflow:
            def __init__(self) -> None:
                self.opened: list[object] = []

            def open(self, parent=None):
                self.opened.append(parent)
                return None

        workflow = FakeSettingsWorkflow()
        view = MinimalView(
            worklog_entry_view_model=WorkLogEntryViewModel(
                user_id=1,
                get_handler=GetWorkLogHandler(MemoryWorkLogRepository()),
                save_handler=SaveWorkLogHandler(MemoryWorkLogRepository()),
            ),
            config=MinimalViewConfig(
                selected_day=date(2026, 4, 20),
                today=date(2026, 4, 13),
                account_name="alice",
            ),
            settings_workflow=workflow,
        )

        self.assertTrue(view.refresh())
        self.assertFalse(view.settings_button.isHidden())
        view.settings_button.click()

        self.assertEqual(workflow.opened, [view])
        self.assertEqual(view.status_label.text(), "")
        self.assertTrue(view.status_label.isHidden())

    def test_minimal_view_blocks_navigation_when_dirty_prompt_is_cancelled(self) -> None:
        view = MinimalView(
            worklog_entry_view_model=WorkLogEntryViewModel(
                user_id=1,
                get_handler=GetWorkLogHandler(MemoryWorkLogRepository()),
                save_handler=SaveWorkLogHandler(MemoryWorkLogRepository()),
            ),
            config=MinimalViewConfig(
                selected_day=date(2026, 4, 20),
                today=date(2026, 4, 13),
                confirm_discard_changes=lambda: False,
            ),
        )
        self.assertTrue(view.refresh())

        view.entry_panel.start_input.setText("0900")
        changed = view.next_day()

        self.assertFalse(changed)
        self.assertTrue(view.has_unsaved_changes)
        self.assertEqual(view.selected_day, date(2026, 4, 20))
        self.assertEqual(view.status_label.text(), "Unsaved changes")


if __name__ == "__main__":
    unittest.main()
