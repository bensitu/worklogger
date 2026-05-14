from __future__ import annotations

from datetime import date
from pathlib import Path
import unittest

from worklogger.app.commands.calendar_commands import ImportCalendarEventsCommand
from worklogger.app.queries.calendar_queries import GetHolidaysForRangeQuery
from worklogger.app.use_cases.calendar import (
    GetHolidaysForRangeHandler,
    ImportCalendarEventsHandler,
)
from worklogger.domain.calendar.models import CalendarEvent, Holiday
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result


class MemoryCalendarRepository:
    def __init__(self, events: tuple[CalendarEvent, ...] = ()) -> None:
        self.events = events
        self.cleared: list[int] = []

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
        self.clear(user_id)
        return self.add_many(user_id, events)

    def add_many(self, user_id: int, events: tuple[CalendarEvent, ...]) -> int:
        self.events = self.events + tuple(events)
        return len(events)

    def clear(self, user_id: int) -> None:
        self.cleared.append(user_id)
        self.events = tuple(event for event in self.events if event.user_id != user_id)


class FakeImporter:
    def __init__(self, result: Result[tuple[CalendarEvent, ...]]) -> None:
        self.result = result
        self.calls: list[tuple[Path, int]] = []

    def read_events(
        self,
        source: Path,
        *,
        user_id: int,
    ) -> Result[tuple[CalendarEvent, ...]]:
        self.calls.append((source, user_id))
        return self.result


class FakeHolidayProvider:
    def list_for_range(
        self,
        country: str,
        start_day: date,
        end_day: date,
    ) -> tuple[Holiday, ...]:
        return (
            Holiday(day=start_day, name=f"{country} first"),
            Holiday(day=end_day, name=f"{country} last"),
        )


class CalendarImportHolidayUseCaseTests(unittest.TestCase):
    def test_import_calendar_events_appends_or_replaces_existing_events(self) -> None:
        existing = CalendarEvent(
            id=1,
            user_id=1,
            day=date(2026, 5, 1),
            summary="Existing",
        )
        imported = CalendarEvent(
            id=None,
            user_id=1,
            day=date(2026, 5, 2),
            summary="Imported",
        )
        repository = MemoryCalendarRepository((existing,))
        importer = FakeImporter(Result.success((imported,)))
        handler = ImportCalendarEventsHandler(repository, importer)

        appended = handler.handle(
            ImportCalendarEventsCommand(
                user_id=1,
                source_path=Path("calendar.ics"),
                replace_existing=False,
            )
        )

        self.assertTrue(appended.ok, appended.error)
        self.assertEqual(appended.value, 1)
        self.assertEqual([event.summary for event in repository.events], ["Existing", "Imported"])
        self.assertEqual(importer.calls, [(Path("calendar.ics"), 1)])

        replaced = handler.handle(
            ImportCalendarEventsCommand(
                user_id=1,
                source_path=Path("calendar.ics"),
                replace_existing=True,
            )
        )

        self.assertTrue(replaced.ok, replaced.error)
        self.assertEqual(repository.cleared, [1])
        self.assertEqual([event.summary for event in repository.events], ["Imported"])

    def test_import_calendar_events_returns_importer_errors(self) -> None:
        repository = MemoryCalendarRepository()
        importer = FakeImporter(
            Result.failure(ValidationError("ics_file_too_large", "ics_file_too_large"))
        )
        result = ImportCalendarEventsHandler(repository, importer).handle(
            ImportCalendarEventsCommand(1, Path("large.ics"))
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code if result.error else "", "ics_file_too_large")
        self.assertEqual(repository.events, ())

    def test_holidays_handler_normalizes_country_and_validates_range(self) -> None:
        handler = GetHolidaysForRangeHandler(FakeHolidayProvider())

        holidays = handler.handle(
            GetHolidaysForRangeQuery(
                country=" jp ",
                start_day=date(2026, 1, 1),
                end_day=date(2026, 1, 2),
            )
        )

        self.assertTrue(holidays.ok, holidays.error)
        self.assertEqual(
            [holiday.name for holiday in holidays.value or ()],
            ["JP first", "JP last"],
        )

        invalid = handler.handle(
            GetHolidaysForRangeQuery(
                country="US",
                start_day=date(2026, 1, 2),
                end_day=date(2026, 1, 1),
            )
        )
        self.assertFalse(invalid.ok)
        self.assertEqual(invalid.error.code if invalid.error else "", "date_range_invalid")


if __name__ == "__main__":
    unittest.main()
