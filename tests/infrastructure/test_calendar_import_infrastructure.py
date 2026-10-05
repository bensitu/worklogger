from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from dataclasses import replace

from worklogger.app.commands.auth_commands import RegisterUserCommand
from worklogger.app.commands.calendar_commands import ImportCalendarEventsCommand
from worklogger.app.use_cases.auth import RegisterUserHandler
from worklogger.app.use_cases.calendar import ImportCalendarEventsHandler
from worklogger.domain.calendar.models import Holiday
from worklogger.infrastructure.calendar import IcsCalendarImporter, PythonHolidaysProvider
from worklogger.infrastructure.calendar.holidays_provider import detect_country, validate_holiday_region
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
    def test_holiday_country_detection_and_subdivision_selection(self) -> None:
        for zone, country in (("Asia/Manila", "PH"), ("Europe/Dublin", "IE"),
                              ("Asia/Ho_Chi_Minh", "VN"), ("America/Argentina/Buenos_Aires", "AR"), ("Etc/UTC", "")):
            with self.subTest(zone=zone), patch("tzlocal.get_localzone", return_value=zone):
                self.assertEqual(detect_country(), country)
        self.assertEqual(validate_holiday_region("us/ca"), "US/CA")
        with self.assertRaises(ValueError):
            validate_holiday_region("US/UNKNOWN")
        provider = PythonHolidaysProvider()
        national = provider.list_for_range("DE", date(2026, 1, 6), date(2026, 1, 6))
        regional = provider.list_for_range("DE", date(2026, 1, 6), date(2026, 1, 6), subdivision="BW")
        self.assertFalse(national)
        self.assertTrue(regional)

    def test_ics_timezones_recurrences_cancellations_and_multiday_events(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.ics"
            path.write_text("BEGIN:VCALENDAR\nVERSION:2.0\n"
                            "BEGIN:VEVENT\nUID:meeting\nDTSTART:20260501T000000Z\nDTEND:20260501T010000Z\n"
                            "RRULE:FREQ=DAILY;COUNT=3\nEXDATE:20260502T000000Z\nSUMMARY:Meeting\nDESCRIPTION:Event notes\n"
                            "BEGIN:VALARM\nACTION:DISPLAY\nTRIGGER:-PT15M\nDESCRIPTION:Reminder\nEND:VALARM\nEND:VEVENT\n"
                            "BEGIN:VEVENT\nUID:trip\nDTSTART;VALUE=DATE:20260504\nDTEND;VALUE=DATE:20260506\nSUMMARY:Trip\nEND:VEVENT\n"
                            "BEGIN:VEVENT\nUID:cancelled\nDTSTART:20260507T000000Z\nSUMMARY:Cancelled\nSTATUS:CANCELLED\nEND:VEVENT\n"
                            "END:VCALENDAR\n", encoding="utf-8")
            importer = IcsCalendarImporter(local_timezone=ZoneInfo("Asia/Tokyo"))
            result = importer.read_events(path, user_id=1)
            self.assertTrue(result.ok, result.error)
            events = result.value
            self.assertEqual([event.day for event in events], [date(2026, 5, n) for n in (1, 3, 4, 5)])
            self.assertEqual((events[0].start_time, events[0].end_time), ("09:00", "10:00"))
            self.assertEqual(events[0].description, "Event notes")
            self.assertTrue(all(event.source_file == "events.ics" for event in events))
            self.assertFalse(IcsCalendarImporter(max_events=2).read_events(path, user_id=1).ok)
            path.write_text(path.read_text().replace(";COUNT=3", ""), encoding="utf-8")
            self.assertEqual(importer.read_events(path, user_id=1).error.code, "ics_recurrence_unbounded")

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

            result = IcsCalendarImporter(local_timezone=ZoneInfo("Asia/Tokyo")).read_events(path, user_id=7)

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
            duplicate = handler.handle(ImportCalendarEventsCommand(user_id, path))
            self.assertEqual(duplicate.value, 0)
            original = repository.list_for_day(user_id, date(2026, 5, 1))
            with self.assertRaises(AttributeError):
                repository.replace_all(user_id, (replace(original[0], day=None),))
            self.assertEqual(repository.list_for_day(user_id, date(2026, 5, 1)), original)
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
