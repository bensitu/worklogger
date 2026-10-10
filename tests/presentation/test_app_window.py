from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timezone
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QWidget, QMessageBox

from worklogger.app.queries.work_log_queries import GetMonthRecordsQuery
from worklogger.app.use_cases.calendar import GetCalendarEventsForRangeHandler
from worklogger.app.use_cases.work_logs import (
    GetMonthRecordsHandler,
)
from worklogger.domain.calendar.models import CalendarEvent
from worklogger.domain.calendar.repositories import CalendarEventRepository
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkLog
from worklogger.domain.worklog.rules import aggregate_days, entries_overlap, normalize_work_log
from dataclasses import replace
from worklogger.app.use_cases.time_entries import TimeEntryService
from worklogger.presentation.viewmodels.time_entries import TimeEntryViewModel
from worklogger.presentation.job_runner import ImmediateJobRunner
from tests.presentation.qt_support import dispose_test_windows
from worklogger.presentation.shell import (
    AppWindow,
    AppWindowConfig,
    MinimalView,
    MinimalViewConfig,
)
from worklogger.presentation.viewmodels import (
    CalendarDisplayOptions,
    CalendarViewModel,
    StatsPanelViewModel,
)


def _app() -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        return existing
    return QApplication([])


class MemoryWorkLogRepository:
    def __init__(self):
        self.records = {}
        self._next_id = 1
        self.timers = {}

    def get_for_day(self, user_id, day):
        return self.records.get((user_id, day))

    def list_for_month(self, user_id, year, month):
        return tuple(record for (owner, day), record in sorted(self.records.items())
                     if owner == user_id and (day.year, day.month) == (year, month))

    def list_all(self, user_id):
        return tuple(record for (owner, _day), record in sorted(self.records.items()) if owner == user_id)

    def list_range(self, user_id, start, end):
        return tuple(record for record in self.list_all(user_id) if start <= record.day <= end)

    def save(self, record, *, expected_note=None):
        if record.id is None:
            record = replace(record, id=self._next_id)
            self._next_id += 1
        self.records[(record.user_id, record.day)] = record

    def remove(self, user_id, day):
        self.records.pop((user_id, day), None)

    def list_for_day(self, user_id, day):
        record = self.get_for_day(user_id, day)
        return (record.entries or (record,)) if record else ()

    def get_entry(self, user_id, entry_id):
        return next((entry for record in self.list_all(user_id)
                     for entry in record.entries or (record,) if entry.id == entry_id), None)

    def save_entry(self, record, *, timer_change=None):
        record = normalize_work_log(record)
        entries = list(self.list_for_day(record.user_id, record.day))
        if any(entry.id != record.id and entries_overlap(entry, record) for entry in entries):
            raise ValueError("worklog_entry_overlap")
        if timer_change is not None:
            self.change_timer(record.user_id, *timer_change)
        if record.id is None:
            record = replace(record, id=self._next_id)
            self._next_id += 1
        else:
            current = self.get_entry(record.user_id, record.id)
            if current is None or current.revision != record.revision:
                raise ValueError("worklog_entry_conflict")
            record = replace(record, revision=record.revision + 1)
        entries = [entry for entry in entries if entry.id != record.id] + [record]
        self.records[(record.user_id, record.day)] = aggregate_days(entries)[0]
        return record

    def delete_entry(self, user_id, entry_id, revision, *, timer_change=None):
        record = self.get_entry(user_id, entry_id)
        if record is None or record.revision != revision:
            raise ValueError("worklog_entry_conflict")
        if timer_change is not None:
            self.change_timer(user_id, *timer_change)
        entries = [entry for entry in self.list_for_day(user_id, record.day) if entry.id != entry_id]
        if entries:
            self.records[(user_id, record.day)] = aggregate_days(entries)[0]
        else:
            self.remove(user_id, record.day)

    def change_timer(self, user_id, expected, value):
        if self.timers.get(user_id) != expected:
            raise ValueError("time_entry_timer_conflict")
        self.timers[user_id] = value


class MemoryTimerSettings:
    def __init__(self, repository):
        self.repository = repository

    def get(self, user_id, key, default=None):
        return self.repository.timers.get(user_id, default) if key == "time_entry_timer" else default


def _entry_model(repository):
    return TimeEntryViewModel(TimeEntryService(user_id=1, repository=repository,
        settings=MemoryTimerSettings(repository), local_timezone=timezone.utc,
        clock=lambda: datetime(2026, 4, 20, 9, tzinfo=timezone.utc)))


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
    def list_range(self, user_id, start, end):
        return Result.failure(ValidationError("month_failed", "month_failed"))

    def handle(self, query: GetMonthRecordsQuery) -> Result[tuple[WorkLog, ...]]:
        return Result.failure(ValidationError("month_failed", "month_failed"))


def _window(
    repository: MemoryWorkLogRepository,
    *,
    account_name: str | None = None,
    confirm_discard_changes: Callable[[], bool] | None = None,
    month_handler: object | None = None,
    settings_workflow: object | None = None,
    analytics_workflow: object | None = None,
    notes_workflow: object | None = None,
    reports_workflow: object | None = None,
    residency_controller: object | None = None,
    calendar_events: tuple[CalendarEvent, ...] | None = None,
) -> AppWindow:
    month_records = month_handler or GetMonthRecordsHandler(repository)
    calendar_view_model = CalendarViewModel(
        user_id=1,
        month_records_handler=month_records,
        calendar_events_handler=GetCalendarEventsForRangeHandler(
            MemoryCalendarRepository(
                calendar_events if calendar_events is not None else (
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
        time_entry_view_model=_entry_model(repository),
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
        analytics_workflow=analytics_workflow,
        notes_workflow=notes_workflow,
        reports_workflow=reports_workflow,
        residency_controller=residency_controller,
        job_runner=ImmediateJobRunner(),
    )


class AppWindowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(dispose_test_windows)
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
        window.entry_panel.content_input.setPlainText("Focused work")

        self.assertTrue(window.entry_panel.save_button.isEnabled())
        window.entry_panel.save_button.click()

        saved = repository.get_for_day(1, date(2026, 4, 20))
        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertEqual(saved.start_time, "09:00")
        self.assertEqual(saved.end_time, "18:00")
        self.assertEqual(saved.note, "Focused work")
        self.assertEqual(window.status_label.text(), "")
        self.assertTrue(window.status_label.isHidden())
        self.information.assert_not_called()
        self.assertEqual(window.stats_panel.value_text("total_hours"), "9.0h")
        self.assertIn("9.0h", window.calendar_view.week_total_labels()[3].text())
        selected = next(
            button
            for button in window.calendar_view.day_buttons()
            if button.cell and button.cell.day == date(2026, 4, 20)
        )
        self.assertIn("9.0h", selected.text())

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

    def test_daily_notes_and_routes_have_direct_actions(self):
        class DayWorkflow:
            def __init__(self):
                self.opened = []
            def open(self, day, parent=None):
                self.opened.append((day, parent))
        notes = DayWorkflow()
        window = _window(MemoryWorkLogRepository(), notes_workflow=notes)
        self.assertTrue(window.refresh())
        window.entry_panel.start_input.setText("09:00")
        self.assertIsNone(window.calendar_page.add_entry_button.menu())
        self.assertTrue(window.calendar_page.add_entry_button.isEnabled())
        window.notes_button.click()
        self.assertEqual(notes.opened, [(date(2026, 4, 20), window)])
        self.assertEqual(window.entry_panel.start_input.text(), "09:00")
        self.assertTrue(window.has_unsaved_changes)
        self.assertFalse(hasattr(window, "quick_logs_button"))
        self.assertFalse(hasattr(window, "ai_assist_button"))

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
            time_entry_view_model=_entry_model(repository),
            job_runner=ImmediateJobRunner(),
            config=MinimalViewConfig(
                selected_day=date(2026, 4, 20),
                today=date(2026, 4, 13),
                account_name="alice",
            ),
        )

        self.assertTrue(view.refresh())
        from worklogger.presentation.date_labels import day_label
        self.assertEqual(view.date_label.text(), day_label(date(2026, 4, 20)))
        self.assertEqual(view.account_label.text(), "Signed in: alice")

        self.assertTrue(view.status_label.isHidden())
        view.entry_panel.start_input.setText("25:00")
        view.entry_panel.start_input.setText("0900")
        view.entry_panel.end_input.setText("1000")
        self.assertEqual(view.status_label.text(), "")
        self.assertTrue(view.status_label.isHidden())
        view.entry_panel.save_button.click()

        saved = repository.get_for_day(1, date(2026, 4, 20))
        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertEqual(saved.start_time, "09:00")
        view.entry_panel.end_input.setText("1200")
        view.entry_panel.work_type_combo.setCurrentIndex(view.entry_panel.work_type_combo.findData("meeting"))
        view.entry_panel.save_button.click()
        entries = repository.list_for_day(1, date(2026, 4, 20))
        self.assertEqual(len(entries), 2)
        view.history_widget.entry_buttons[entries[0].id].click()
        self.assertEqual(view.entry_panel.view_model.draft.original.id, entries[0].id)
        view.entry_panel.content_input.setPlainText("Updated")
        view.entry_panel.save_button.click()
        self.assertEqual(repository.get_entry(1, entries[0].id).note, "Updated")
        with patch("worklogger.presentation.widgets.time_entries.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            view.history_widget.entry_buttons[entries[1].id].delete_button.click()
        self.assertEqual(len(repository.list_for_day(1, date(2026, 4, 20))), 1)
        self.assertEqual(view.status_label.text(), "")
        self.assertTrue(view.status_label.isHidden())

        self.assertTrue(view.next_day())
        self.assertEqual(view.selected_day, date(2026, 4, 21))
        self.assertEqual(view.date_label.text(), day_label(date(2026, 4, 21)))

    def test_minimal_view_opens_settings_workflow_when_available(self) -> None:
        class FakeSettingsWorkflow:
            def __init__(self) -> None:
                self.opened: list[object] = []

            def open(self, parent=None):
                self.opened.append(parent)
                return None

        workflow = FakeSettingsWorkflow()
        view = MinimalView(
            time_entry_view_model=_entry_model(MemoryWorkLogRepository()),
            job_runner=ImmediateJobRunner(),
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
            time_entry_view_model=_entry_model(MemoryWorkLogRepository()),
            job_runner=ImmediateJobRunner(),
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
