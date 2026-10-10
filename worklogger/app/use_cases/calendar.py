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
from worklogger.domain.shared.errors import InfrastructureError, ValidationError
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
        try:
            return Result.success(self._repository.list_for_day(query.user_id, query.day))
        except Exception:
            return Result.failure(InfrastructureError("calendar_load_failed", "calendar_load_failed"))


class GetCalendarEventsForRangeHandler:
    def __init__(self, repository: CalendarEventRepository) -> None:
        self._repository = repository

    def handle(
        self,
        query: GetCalendarEventsForRangeQuery,
    ) -> Result[tuple[CalendarEvent, ...]]:
        if query.end_day < query.start_day:
            return Result.failure(ValidationError("date_range_invalid", "date_range_invalid"))
        try:
            return Result.success(self._repository.list_for_range(query.user_id, query.start_day, query.end_day))
        except Exception:
            return Result.failure(InfrastructureError("calendar_load_failed", "calendar_load_failed"))


class GetHolidaysForRangeHandler:
    def __init__(self, provider: HolidayProvider) -> None:
        self._provider = provider

    def handle(self, query: GetHolidaysForRangeQuery) -> Result[tuple[Holiday, ...]]:
        if query.end_day < query.start_day:
            return Result.failure(ValidationError("date_range_invalid", "date_range_invalid"))
        country = str(query.country or "").strip().upper()
        if not country:
            return Result.success(())
        try:
            options = {"subdivision": query.subdivision} if query.subdivision else {}
            return Result.success(self._provider.list_for_range(country, query.start_day, query.end_day, **options))
        except Exception:
            return Result.failure(InfrastructureError("holiday_load_failed", "holiday_load_failed"))


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
        try:
            operation = self._repository.replace_all if command.replace_existing else self._repository.add_many
            imported = operation(command.user_id, events.value)
        except Exception:
            return Result.failure(InfrastructureError("ics_import_failed", "ics_import_failed"))
        return Result.success(imported)
