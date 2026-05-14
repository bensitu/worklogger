"""Calendar query use cases."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from worklogger.app.commands.calendar_commands import ImportCalendarEventsCommand
from worklogger.app.queries.calendar_queries import (
    GetCalendarEventsForDayQuery,
    GetCalendarEventsForRangeQuery,
    GetHolidaysForRangeQuery,
)
from worklogger.domain.calendar.models import CalendarEvent, Holiday
from worklogger.domain.calendar.repositories import (
    CalendarEventRepository,
    HolidayProvider,
)
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result


class CalendarEventImporter(Protocol):
    def read_events(
        self,
        source: Path,
        *,
        user_id: int,
    ) -> Result[tuple[CalendarEvent, ...]]:
        ...


class GetCalendarEventsForDayHandler:
    def __init__(self, repository: CalendarEventRepository) -> None:
        self._repository = repository

    def handle(
        self,
        query: GetCalendarEventsForDayQuery,
    ) -> Result[tuple[CalendarEvent, ...]]:
        return Result.success(self._repository.list_for_day(query.user_id, query.day))


class GetCalendarEventsForRangeHandler:
    def __init__(self, repository: CalendarEventRepository) -> None:
        self._repository = repository

    def handle(
        self,
        query: GetCalendarEventsForRangeQuery,
    ) -> Result[tuple[CalendarEvent, ...]]:
        if query.end_day < query.start_day:
            return Result.failure(ValidationError("date_range_invalid", "date_range_invalid"))
        return Result.success(
            self._repository.list_for_range(
                query.user_id,
                query.start_day,
                query.end_day,
            )
        )


class GetHolidaysForRangeHandler:
    def __init__(self, provider: HolidayProvider) -> None:
        self._provider = provider

    def handle(self, query: GetHolidaysForRangeQuery) -> Result[tuple[Holiday, ...]]:
        if query.end_day < query.start_day:
            return Result.failure(ValidationError("date_range_invalid", "date_range_invalid"))
        country = str(query.country or "US").strip().upper() or "US"
        return Result.success(
            self._provider.list_for_range(
                country,
                query.start_day,
                query.end_day,
            )
        )


class ImportCalendarEventsHandler:
    def __init__(
        self,
        repository: CalendarEventRepository,
        importer: CalendarEventImporter,
    ) -> None:
        self._repository = repository
        self._importer = importer

    def handle(self, command: ImportCalendarEventsCommand) -> Result[int]:
        events = self._importer.read_events(
            Path(command.source_path),
            user_id=command.user_id,
        )
        if not events.ok or events.value is None:
            return Result.failure(
                events.error or ValidationError("ics_import_failed", "ics_import_failed")
            )
        if command.replace_existing:
            self._repository.clear(command.user_id)
        imported = self._repository.add_many(command.user_id, events.value)
        return Result.success(imported)
