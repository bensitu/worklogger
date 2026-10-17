from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import unittest

from worklogger.app.commands.auth_commands import (
    ChangePasswordCommand,
    LoginCommand,
    RegisterUserCommand,
    ResetPasswordCommand,
)
from worklogger.app.commands.report_commands import SaveReportCommand
from worklogger.app.commands.settings_commands import (
    SetActiveLocalModelCommand,
    SetSettingCommand,
)
from worklogger.app.commands.work_log_commands import SaveWorkLogCommand
from worklogger.app.event_bus import EventBus, SettingsChanged, WorkLogSaved
from worklogger.app.queries.analytics_queries import GetAnalyticsBundleQuery
from worklogger.app.queries.quick_log_queries import GetQuickLogsForRangeQuery
from worklogger.app.queries.report_queries import GetReportForPeriodQuery
from worklogger.app.queries.settings_queries import GetSettingQuery
from worklogger.app.use_cases.analytics import GetAnalyticsBundleHandler
from worklogger.app.use_cases.auth import (
    ChangePasswordHandler,
    LoginHandler,
    LoginWithRememberTokenHandler,
    RegisterUserHandler,
    ResetPasswordHandler,
)
from worklogger.app.use_cases.quick_logs import GetQuickLogsForRangeHandler
from worklogger.app.use_cases.reports import GetReportForPeriodHandler, SaveReportHandler
from worklogger.app.use_cases.settings import (
    GetSettingHandler,
    SetActiveLocalModelHandler,
    SetSettingHandler,
)
from worklogger.app.use_cases.work_logs import SaveWorkLogHandler
from worklogger.config.constants import (
    LOCAL_MODEL_ACTIVE_ID_SETTING_KEY,
    REMEMBER_TOKEN_HASH_PREFIX,
)
from worklogger.domain.auth.models import User
from worklogger.domain.auth.policies import generate_recovery_key
from worklogger.domain.quicklog.models import QuickLog
from worklogger.domain.reporting.models import Report
from worklogger.domain.worklog.models import WorkLog, EntryType


class MemoryWorkLogRepository:
    def __init__(self) -> None:
        self.records: dict[tuple[int, date], WorkLog] = {}

    def get_for_day(self, user_id: int, day: date) -> WorkLog | None:
        return self.records.get((user_id, day))

    def list_for_month(self, user_id: int, year: int, month: int) -> tuple[WorkLog, ...]:
        return tuple(
            record
            for (record_user_id, day), record in sorted(self.records.items())
            if record_user_id == user_id and day.year == year and day.month == month
        )

    def list_all(self, user_id: int) -> tuple[WorkLog, ...]:
        return tuple(record for (record_user_id, _day), record in self.records.items() if record_user_id == user_id)

    def list_range(self, user_id: int, start: date, end: date) -> tuple[WorkLog, ...]:
        return tuple(record for record in self.list_all(user_id) if start <= record.day <= end)

    def save(self, work_log: WorkLog, *, expected_note: str | None = None) -> None:
        self.records[(work_log.user_id, work_log.day)] = work_log

    def remove(self, user_id: int, day: date) -> None:
        self.records.pop((user_id, day), None)


class MemoryQuickLogRepository:
    def __init__(self, logs=()) -> None:
        self.logs = logs

    def list_for_day(self, user_id: int, day: date) -> tuple[QuickLog, ...]:
        return tuple(log for log in self.logs if log.user_id == user_id and log.day == day)

    def list_for_range(self, user_id: int, start_day: date, end_day: date) -> tuple[QuickLog, ...]:
        return tuple(log for log in self.logs if log.user_id == user_id and start_day <= log.day <= end_day)


class MemorySettingsRepository:
    def __init__(self) -> None:
        self.values: dict[tuple[int, str], str] = {}

    def get(self, user_id: int, key: str, default: str | None = None) -> str | None:
        return self.values.get((user_id, key), default)

    def set(self, user_id: int, key: str, value: str) -> None:
        self.values[(user_id, key)] = value

    def delete(self, user_id: int, key: str) -> None:
        self.values.pop((user_id, key), None)


class MemoryReportRepository:
    def __init__(self) -> None:
        self.reports: dict[int, Report] = {}
        self.next_id = 1

    def save(self, report: Report) -> Report:
        stored = replace(report, id=self.next_id)
        self.reports[self.next_id] = stored
        self.next_id += 1
        return stored

    def get_for_period(
        self,
        user_id: int,
        report_type: str,
        period_start: date,
        period_end: date,
    ) -> Report | None:
        for report in self.reports.values():
            if (
                report.user_id == user_id
                and report.report_type == report_type
                and report.period_start == period_start
                and report.period_end == period_end
            ):
                return report
        return None

    def list_by_type(self, user_id: int, report_type: str) -> tuple[Report, ...]:
        return tuple(
            report
            for report in self.reports.values()
            if report.user_id == user_id and report.report_type == report_type
        )

    def remove(self, user_id: int, report_id: int) -> None:
        if self.reports.get(report_id) and self.reports[report_id].user_id == user_id:
            self.reports.pop(report_id)


class MemoryAuthRepository:
    def register_user(self, username, password, *, recovery_key):
        return self.create_user(username, password, recovery_key=recovery_key, is_admin=self.user_count() == 0)

    def __init__(self) -> None:
        self.users: dict[str, tuple[User, str, str]] = {}
        self.remember_tokens: dict[str, User] = {}
        self.cleared_tokens: list[int] = []

    def user_count(self) -> int:
        return len(self.users)

    def create_user(
        self,
        username: str,
        password: str,
        *,
        recovery_key: str | None,
        is_admin: bool,
        must_change_password: bool = False,
    ) -> User:
        user = User(
            id=len(self.users) + 1,
            username=username,
            is_admin=is_admin,
            must_change_password=must_change_password,
        )
        self.users[username] = (user, password, recovery_key or "")
        return user

    def verify_user(self, username: str, password: str) -> User | None:
        entry = self.users.get(username)
        if entry is None:
            return None
        user, stored_password, _recovery_key = entry
        return user if stored_password == password else None

    def change_password(
        self,
        user_id: int,
        current_password: str,
        new_password: str,
    ) -> str | None:
        for username, (user, stored_password, _recovery_key) in list(self.users.items()):
            if user.id == user_id and stored_password == current_password:
                new_recovery_key = generate_recovery_key()
                self.users[username] = (user, new_password, new_recovery_key)
                return new_recovery_key
        return None

    def reset_password_with_recovery(
        self,
        username: str,
        recovery_key: str,
        new_password: str,
    ) -> tuple[User, str] | None:
        entry = self.users.get(username)
        if entry is None:
            return None
        user, _stored_password, stored_recovery_key = entry
        if recovery_key != stored_recovery_key:
            return None
        new_recovery_key = generate_recovery_key()
        self.users[username] = (user, new_password, new_recovery_key)
        return user, new_recovery_key

    def set_remember_token(
        self,
        user_id: int,
        stored_token: str | None,
        expires_at: datetime | None,
    ) -> None:
        if stored_token is None:
            self.cleared_tokens.append(user_id)
            for token, user in list(self.remember_tokens.items()):
                if user.id == user_id:
                    self.remember_tokens.pop(token)
            return
        for user, _password, _recovery_key in self.users.values():
            if user.id == user_id:
                self.remember_tokens[stored_token] = user

    def get_user_by_remember_token(self, stored_token: str) -> User | None:
        return self.remember_tokens.get(stored_token)


class MemoryLoginFailures:
    def __init__(self) -> None:
        self.count = 0
        self.locked_until: datetime | None = None
        self.cleared = False

    def lockout_until(self, username: str) -> datetime | None:
        return self.locked_until

    def record_failure(self, username: str) -> tuple[int, datetime | None]:
        self.count += 1
        return self.count, self.locked_until

    def clear_failures(self, username: str) -> None:
        self.cleared = True


class ApplicationUseCaseTests(unittest.TestCase):
    def test_holiday_region_settings_use_injected_validation_before_storage(self):
        from functools import partial
        from worklogger.domain.calendar.regions import validate_holiday_region
        repository = MemorySettingsRepository()
        handler = SetSettingHandler(repository, holiday_region_validator=partial(
            validate_holiday_region, supported={"JP": (), "US": ("CA",)}))
        self.assertTrue(handler.handle(SetSettingCommand(1, "holiday_region", "us/ca")).ok)
        self.assertEqual(repository.get(1, "holiday_region"), "US/CA")
        for command in (SetSettingCommand(1, "holiday_region", "US/INVALID"),
                        SetSettingCommand(1, "holiday_region", "ZZ")):
            self.assertEqual(handler.handle(command).error.code, "holiday_region_invalid")
        self.assertEqual(repository.get(1, "holiday_region"), "US/CA")
        self.assertFalse(SetSettingHandler(repository).handle(SetSettingCommand(1, "holiday_region", "JP")).ok)
        self.assertTrue(handler.handle(SetSettingCommand(1, "holiday_region", "")).ok)

    def test_settings_reject_missing_values_instead_of_storing_none_as_text(self):
        repository = MemorySettingsRepository()
        result = SetSettingHandler(repository).handle(SetSettingCommand(1, "theme", None))
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "setting_value_invalid")
        self.assertIsNone(repository.get(1, "theme"))

    def test_event_delivery_isolates_subscriber_failures_and_supports_unsubscribe(self):
        bus = EventBus()
        delivered = []

        def failed(event):
            raise RuntimeError("subscriber_unavailable")

        bus.subscribe(WorkLogSaved, failed)
        unsubscribe = bus.subscribe(WorkLogSaved, delivered.append)
        event = WorkLogSaved(1, date(2026, 4, 20))
        with self.assertLogs("worklogger.app.event_bus", level="ERROR"):
            bus.publish(event)
        unsubscribe()
        unsubscribe()
        with self.assertLogs("worklogger.app.event_bus", level="ERROR"):
            bus.publish(event)
        self.assertEqual(delivered, [event])

    def test_work_log_save_normalizes_times_and_publishes_event(self) -> None:
        repository = MemoryWorkLogRepository()
        bus = EventBus()
        events: list[WorkLogSaved] = []
        bus.subscribe(WorkLogSaved, events.append)

        result = SaveWorkLogHandler(repository, bus).handle(
            SaveWorkLogCommand(
                user_id=1,
                day=date(2026, 4, 20),
                start_time="2200",
                end_time="0900",
                break_hours=1.0,
                note="Night shift",
                entry_type="normal",
            )
        )

        self.assertTrue(result.ok)
        assert result.value is not None
        self.assertEqual(result.value.start_time, "22:00")
        self.assertEqual(result.value.end_time, "09:00")
        self.assertTrue(result.value.overnight)
        self.assertEqual(events, [WorkLogSaved(user_id=1, day=date(2026, 4, 20))])

    def test_auth_register_login_remember_change_and_reset(self) -> None:
        credentials = MemoryAuthRepository()
        failures = MemoryLoginFailures()
        registered = RegisterUserHandler(credentials).handle(
            RegisterUserCommand(" alice ", "secret123")
        )
        self.assertTrue(registered.ok)
        assert registered.value is not None
        self.assertTrue(registered.value.user.is_admin)
        self.assertTrue(registered.value.recovery_key)

        login = LoginHandler(credentials, failures).handle(
            LoginCommand("alice", "secret123", remember=True)
        )
        self.assertTrue(login.ok)
        assert login.value is not None
        self.assertTrue(login.value.token)
        stored_tokens = tuple(credentials.remember_tokens)
        self.assertEqual(len(stored_tokens), 1)
        self.assertTrue(stored_tokens[0].startswith(REMEMBER_TOKEN_HASH_PREFIX))
        self.assertNotEqual(stored_tokens[0], login.value.token)
        self.assertTrue(failures.cleared)

        remembered = LoginWithRememberTokenHandler(credentials).handle(login.value.token or "")
        self.assertTrue(remembered.ok)
        assert remembered.value is not None
        self.assertEqual(remembered.value.username, "alice")

        changed = ChangePasswordHandler(credentials).handle(
            ChangePasswordCommand(1, "secret123", "secret456")
        )
        self.assertTrue(changed.ok)
        self.assertIn(1, credentials.cleared_tokens)

        reset = ResetPasswordHandler(credentials).handle(
            ResetPasswordCommand("alice", changed.value or "", "secret789")
        )
        self.assertTrue(reset.ok)

    def test_login_returns_auth_error_when_lockout_is_active(self) -> None:
        credentials = MemoryAuthRepository()
        RegisterUserHandler(credentials).handle(RegisterUserCommand("alice", "secret123"))
        failures = MemoryLoginFailures()
        failures.locked_until = datetime.now(timezone.utc) + timedelta(minutes=1)

        result = LoginHandler(credentials, failures).handle(
            LoginCommand("alice", "secret123")
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code if result.error else "", "invalid_credentials")

    def test_historical_quick_log_ranges_preserve_entries_and_isolate_accounts(self) -> None:
        entry = QuickLog(1, 1, date(2026, 4, 20), "Standup", "09:30", "10:00")
        repository = MemoryQuickLogRepository((
            entry,
            QuickLog(2, 2, entry.day, "Other account"),
            QuickLog(3, 1, date(2026, 3, 31), "Outside range"),
        ))
        handler = GetQuickLogsForRangeHandler(repository)
        listed = handler.handle(GetQuickLogsForRangeQuery(1, date(2026, 4, 1), date(2026, 4, 30)))
        self.assertTrue(listed.ok)
        self.assertEqual(listed.value, (entry,))
        invalid = handler.handle(GetQuickLogsForRangeQuery(1, date(2026, 4, 30), date(2026, 4, 1)))
        self.assertEqual(invalid.error.code, "date_range_invalid")
        self.assertEqual(len(repository.logs), 3)

    def test_settings_handlers_set_get_clear_and_publish_events(self) -> None:
        repository = MemorySettingsRepository()
        bus = EventBus()
        events: list[SettingsChanged] = []
        bus.subscribe(SettingsChanged, events.append)

        set_result = SetSettingHandler(repository, bus).handle(
            SetSettingCommand(user_id=1, key="theme", value="blue")
        )
        self.assertTrue(set_result.ok)
        got = GetSettingHandler(repository).handle(
            GetSettingQuery(user_id=1, key="theme")
        )
        self.assertEqual(got.value, "blue")

        for key, value in (("time_entry_timer", "{}"), ("unknown", "value"),
                           ("standard_work_hours", "nan"), ("standard_work_hours", "25"),
                           ("show_holidays", "maybe"), ("network_proxy_port", "65536")):
            self.assertFalse(SetSettingHandler(repository).handle(SetSettingCommand(1, key, value)).ok)
            self.assertIsNone(repository.get(1, key))
        self.assertTrue(SetSettingHandler(repository).handle(SetSettingCommand(1, "show_holidays", " true ")).ok)
        self.assertEqual(repository.get(1, "show_holidays"), "1")

        SetActiveLocalModelHandler(repository, bus).handle(
            SetActiveLocalModelCommand(user_id=1, model_id="model-a")
        )
        self.assertEqual(
            repository.get(1, LOCAL_MODEL_ACTIVE_ID_SETTING_KEY),
            "model-a",
        )
        SetActiveLocalModelHandler(repository, bus).handle(
            SetActiveLocalModelCommand(user_id=1, model_id=None)
        )
        self.assertIsNone(repository.get(1, LOCAL_MODEL_ACTIVE_ID_SETTING_KEY))
        self.assertGreaterEqual(len(events), 3)

    def test_report_and_analytics_handlers_stay_behind_repositories(self) -> None:
        reports = MemoryReportRepository()
        saved = SaveReportHandler(reports).handle(
            SaveReportCommand(
                user_id=1,
                report_type="weekly",
                period_start=date(2026, 4, 20),
                period_end=date(2026, 4, 26),
                content="content",
            )
        )
        self.assertTrue(saved.ok)

        found = GetReportForPeriodHandler(reports).handle(
            GetReportForPeriodQuery(
                user_id=1,
                report_type="weekly",
                period_start=date(2026, 4, 20),
                period_end=date(2026, 4, 26),
            )
        )
        self.assertEqual(found.value, saved.value)

        work_logs = MemoryWorkLogRepository()
        SaveWorkLogHandler(work_logs).handle(
            SaveWorkLogCommand(
                user_id=1,
                day=date(2026, 4, 7),
                start_time="09:00",
                end_time="18:00",
                break_hours=1.0,
                note="",
                entry_type="normal",
            )
        )
        SaveWorkLogHandler(work_logs).handle(
            SaveWorkLogCommand(
                user_id=1,
                day=date(2026, 4, 8),
                start_time=None,
                end_time=None,
                break_hours=0.0,
                note="",
                entry_type=EntryType.PAID_LEAVE.value,
            )
        )
        bundle = GetAnalyticsBundleHandler(work_logs).handle(
            GetAnalyticsBundleQuery(
                user_id=1,
                year=2026,
                month=4,
                metric="hours",
                include_leaves=True,
                scope="monthly",
            )
        )
        self.assertTrue(bundle.ok)
        assert bundle.value is not None
        self.assertEqual(bundle.value.bar_data[1], ("W2\n4/5-11", 8.0))
        self.assertEqual(bundle.value.leave_line_data[1], 8.0)


if __name__ == "__main__":
    unittest.main()
