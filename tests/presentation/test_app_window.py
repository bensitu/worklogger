from __future__ import annotations

from collections.abc import Callable
from datetime import date
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication

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

    def save(self, work_log: WorkLog) -> None:
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
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = _app()

    def test_app_window_refreshes_components_and_navigates_months(self) -> None:
        window = _window(MemoryWorkLogRepository())

        self.assertTrue(window.refresh())
        self.assertEqual(window.selected_day, date(2026, 4, 20))
        self.assertEqual(window.current_month, date(2026, 4, 1))
        self.assertEqual(window.calendar_view.month_title.text(), "2026/04")
        self.assertEqual(window.status_label.text(), "Ready")
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
        self.assertEqual(window.stats_panel.value_text("total_hours"), "8.0h")
        self.assertIn("8.0h", window.calendar_view.week_total_labels()[3].text())
        selected = next(
            button
            for button in window.calendar_view.day_buttons()
            if button.cell and button.cell.day == date(2026, 4, 20)
        )
        self.assertIn("8.0h", selected.text())

    def test_app_window_displays_handler_errors(self) -> None:
        window = _window(
            MemoryWorkLogRepository(),
            month_handler=FailingMonthRecordsHandler(),
        )

        self.assertFalse(window.refresh())

        self.assertIsNotNone(window.last_error)
        assert window.last_error is not None
        self.assertEqual(window.last_error.code, "month_failed")
        self.assertEqual(window.status_label.text(), "month_failed")

    def test_app_window_exposes_account_label_and_logout_signal(self) -> None:
        window = _window(MemoryWorkLogRepository(), account_name="alice")
        logouts: list[bool] = []
        window.logout_requested.connect(lambda: logouts.append(True))

        self.assertEqual(window.account_label.text(), "Signed in: alice")
        self.assertFalse(window.logout_button.isHidden())

        window.logout_button.click()

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
        self.assertEqual(window.status_label.text(), "Ready")

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

        self.assertFalse(window.quick_logs_button.isHidden())
        self.assertFalse(window.analytics_button.isHidden())
        self.assertFalse(window.ai_assist_button.isHidden())
        self.assertFalse(window.notes_button.isHidden())
        self.assertFalse(window.reports_button.isHidden())
        window.quick_logs_button.click()
        window.analytics_button.click()
        window.ai_assist_button.click()
        window.notes_button.click()
        window.reports_button.click()

        self.assertEqual(quick_logs.opened, [(date(2026, 4, 20), window)])
        self.assertEqual(analytics.opened, [(date(2026, 4, 20), window)])
        self.assertEqual(ai_assist.opened, [(date(2026, 4, 20), window)])
        self.assertEqual(notes.opened, [(date(2026, 4, 20), window)])
        self.assertEqual(reports.opened, [(date(2026, 4, 20), window)])

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
        window.logout_button.click()

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

    def test_app_window_and_minimal_view_render_offscreen(self) -> None:
        window = _window(MemoryWorkLogRepository(), account_name="alice")
        self.assertTrue(window.refresh())
        window.resize(1000, 700)
        window.show()
        self._app.processEvents()

        window_pixmap = window.grab()

        self.assertFalse(window_pixmap.isNull())
        self.assertGreaterEqual(window_pixmap.width(), 900)
        self.assertGreaterEqual(window_pixmap.height(), 580)
        window.close()

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
        )
        self.assertTrue(view.refresh())
        view.resize(420, 420)
        view.show()
        self._app.processEvents()

        view_pixmap = view.grab()

        self.assertFalse(view_pixmap.isNull())
        self.assertGreaterEqual(view_pixmap.width(), 400)
        self.assertGreaterEqual(view_pixmap.height(), 380)
        view.close()

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

        view.entry_panel.start_input.setText("0900")
        view.entry_panel.end_input.setText("1800")
        view.entry_panel.save_button.click()

        saved = repository.get_for_day(1, date(2026, 4, 20))
        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertEqual(saved.start_time, "09:00")
        self.assertEqual(view.status_label.text(), "Saved")

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
        self.assertEqual(view.status_label.text(), "Ready")

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
