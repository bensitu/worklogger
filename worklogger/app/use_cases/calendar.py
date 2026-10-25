"""Calendar query use cases."""

from __future__ import annotations

from worklogger.app.failures import infrastructure_failure

from pathlib import Path
from datetime import date
from typing import Protocol
from collections.abc import Callable

from worklogger.app.commands.calendar_commands import ImportCalendarEventsCommand
from worklogger.app.failures import storage_boundary
from worklogger.app.queries.calendar_queries import (
    GetCalendarEventsForRangeQuery,
    GetHolidaysForRangeQuery,
)
from worklogger.domain.calendar.models import CalendarEvent, Holiday
from worklogger.domain.calendar.repositories import (
    CalendarEventRepository,
    HolidayProvider,
)
from worklogger.domain.shared.errors import CancellationError, ValidationError
from worklogger.domain.shared.result import Result


class CalendarEventImporter(Protocol):
    def read_events(
        self,
        source: Path,
        *,
        user_id: int,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Result[tuple[CalendarEvent, ...]]:
        ...


class GetCalendarEventsForRangeHandler:
    def __init__(self, repository: CalendarEventRepository) -> None:
        self._repository = repository

    @storage_boundary("calendar_event_count_failed")
    def count(self, user_id: int) -> Result[int]:
        return Result.success(self._repository.count(user_id))

    def handle(
        self,
        query: GetCalendarEventsForRangeQuery,
    ) -> Result[tuple[CalendarEvent, ...]]:
        if not isinstance(query.start_day, date) or not isinstance(query.end_day, date) or query.end_day < query.start_day:
            return Result.failure(ValidationError("date_range_invalid", "date_range_invalid"))
        try:
            return Result.success(self._repository.list_for_range(query.user_id, query.start_day, query.end_day))
        except Exception as error:
            return Result.failure(infrastructure_failure('calendar_load_failed', error, logger_name=__name__))


class GetHolidaysForRangeHandler:
    def __init__(self, provider: HolidayProvider) -> None:
        self._provider = provider

    def handle(self, query: GetHolidaysForRangeQuery) -> Result[tuple[Holiday, ...]]:
        if not isinstance(query.start_day, date) or not isinstance(query.end_day, date) or query.end_day < query.start_day:
            return Result.failure(ValidationError("date_range_invalid", "date_range_invalid"))
        country = str(query.country or "").strip().upper()
        if not country:
            return Result.success(())
        try:
            options = {"subdivision": query.subdivision} if query.subdivision else {}
            return Result.success(self._provider.list_for_range(country, query.start_day, query.end_day, **options))
        except Exception as error:
            return Result.failure(infrastructure_failure('holiday_load_failed', error, logger_name=__name__))


class ImportCalendarEventsHandler:
    def __init__(
        self,
        repository: CalendarEventRepository,
        importer: CalendarEventImporter,
    ) -> None:
        self._repository = repository
        self._importer = importer

    def handle(self, command: ImportCalendarEventsCommand) -> Result[int]:
        options = {"is_cancelled": command.cancellation.is_cancelled} if command.cancellation is not None else {}
        events = self._importer.read_events(
            Path(command.source_path),
            user_id=command.user_id,
            **options,
        )
        if not events.ok or events.value is None:
            return Result.failure(
                events.error or ValidationError("ics_import_failed", "ics_import_failed")
            )
        if command.cancellation is not None and command.cancellation.is_cancelled():
            return Result.failure(CancellationError("job_cancelled", "job_cancelled"))
        try:
            operation = self._repository.replace_all if command.replace_existing else self._repository.add_many
            imported = operation(command.user_id, events.value)
        except Exception as error:
            return Result.failure(infrastructure_failure('ics_import_failed', error, logger_name=__name__))
        return Result.success(imported)
