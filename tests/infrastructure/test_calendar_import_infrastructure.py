from __future__ import annotations

from datetime import date
from pathlib import Path
import tempfile
import unittest

from worklogger.app.commands.auth_commands import RegisterUserCommand
from worklogger.app.commands.calendar_commands import ImportCalendarEventsCommand
from worklogger.app.use_cases.auth import RegisterUserHandler
from worklogger.app.use_cases.calendar import ImportCalendarEventsHandler
from worklogger.domain.calendar.models import Holiday
from worklogger.infrastructure.calendar import IcsCalendarImporter, PythonHolidaysProvider
from worklogger.infrastructure.database import MigrationRunner, SQLiteConnectionFactory
from worklogger.infrastructure.repositories import (
    SQLiteAuthRepository,
    SQLiteCalendarEventRepository,
)
from worklogger.infrastructure.security import PBKDF2PasswordHasher


class FakeHolidaysModule:
    def country_holidays(self, country: str, *, years: tuple[int, ...]):
        self.country = country
        self.years = years
        return {
            date(2026, 1, 1): "New Year",
            date(2027, 1, 1): "Next New Year",
        }


class CalendarImportInfrastructureTests(unittest.TestCase):
    def test_ics_importer_parses_rich_events_and_folded_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calendar.ics"
            path.write_text(
                "\n".join(
                    [
                        "BEGIN:VCALENDAR",
                        "BEGIN:VEVENT",
                        "DTSTART;TZID=Asia/Tokyo:20260514T093000",
                        "DTEND;TZID=Asia/Tokyo:20260514T103000",
                        "SUMMARY:Planning\\, roadmap",
                        "DESCRIPTION:Line one\\nline ",
                        " two",
                        "LOCATION:Room\\; A",
                        "END:VEVENT",
                        "BEGIN:VEVENT",
                        "DTSTART;VALUE=DATE:20260515",
                        "SUMMARY:All day event",
                        "END:VEVENT",
                        "END:VCALENDAR",
                    ]
                ),
                encoding="utf-8",
            )

            result = IcsCalendarImporter().read_events(path, user_id=7)

        self.assertTrue(result.ok, result.error)
        events = result.value or ()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].day, date(2026, 5, 14))
        self.assertEqual(events[0].start_time, "09:30")
        self.assertEqual(events[0].end_time, "10:30")
        self.assertEqual(events[0].summary, "Planning, roadmap")
        self.assertEqual(events[0].description, "Line one\nline two")
        self.assertEqual(events[0].location, "Room; A")
        self.assertFalse(events[0].all_day)
        self.assertEqual(events[1].day, date(2026, 5, 15))
        self.assertIsNone(events[1].start_time)
        self.assertTrue(events[1].all_day)

    def test_ics_importer_rejects_files_over_size_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "large.ics"
            path.write_text("BEGIN:VCALENDAR\n", encoding="utf-8")
            result = IcsCalendarImporter(max_bytes=8).read_events(path, user_id=1)

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code if result.error else "", "ics_file_too_large")

    def test_sqlite_calendar_import_handler_appends_and_replaces(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            factory = SQLiteConnectionFactory(Path(directory) / "worklog.db")
            MigrationRunner(factory).run_pending()
            auth = SQLiteAuthRepository(
                factory,
                password_hasher=PBKDF2PasswordHasher(iterations=1_000),
            )
            registered = RegisterUserHandler(auth).handle(
                RegisterUserCommand("alice", "secret123")
            )
            assert registered.value is not None
            user_id = registered.value.user.id
            repository = SQLiteCalendarEventRepository(factory)
            repository.add_many(
                user_id,
                (
                    _event(user_id, date(2026, 5, 1), "Existing"),
                ),
            )
            path = Path(directory) / "calendar.ics"
            path.write_text(
                "BEGIN:VCALENDAR\n"
                "BEGIN:VEVENT\n"
                "DTSTART:20260502T090000\n"
                "SUMMARY:Imported\n"
                "END:VEVENT\n"
                "END:VCALENDAR\n",
                encoding="utf-8",
            )
            handler = ImportCalendarEventsHandler(repository, IcsCalendarImporter())

            appended = handler.handle(
                ImportCalendarEventsCommand(user_id, path, replace_existing=False)
            )
            replaced = handler.handle(
                ImportCalendarEventsCommand(user_id, path, replace_existing=True)
            )
            events = repository.list_for_range(
                user_id,
                date(2026, 5, 1),
                date(2026, 5, 31),
            )

        self.assertTrue(appended.ok, appended.error)
        self.assertTrue(replaced.ok, replaced.error)
        self.assertEqual([event.summary for event in events], ["Imported"])

    def test_python_holidays_provider_filters_range_with_injected_module(self) -> None:
        module = FakeHolidaysModule()
        provider = PythonHolidaysProvider(module)

        result = provider.list_for_range(
            "jp",
            date(2026, 1, 1),
            date(2026, 12, 31),
        )

        self.assertEqual(result, (Holiday(day=date(2026, 1, 1), name="New Year"),))
        self.assertEqual(module.country, "jp")
        self.assertEqual(module.years, (2026,))


def _event(user_id: int, day: date, summary: str):
    from worklogger.domain.calendar.models import CalendarEvent

    return CalendarEvent(
        id=None,
        user_id=user_id,
        day=day,
        summary=summary,
    )


if __name__ == "__main__":
    unittest.main()
