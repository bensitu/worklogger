"""Account-scoped inspection and explicit recovery of invalid stored records."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from worklogger.app.use_cases._errors import infrastructure_failure
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result


@dataclass(frozen=True)
class InvalidRecord:
    record_id: int
    stored_date: str


@dataclass(frozen=True)
class RecordInspection:
    records: tuple[InvalidRecord, ...]
    digest: str


class RecordIntegrityRepository(Protocol):
    def inspect(self, user_id: int) -> RecordInspection: ...
    def archive_invalid(self, user_id: int, expected: RecordInspection, destination: Path) -> int: ...


class RecordIntegrityService:
    def __init__(self, user_id: int, repository: RecordIntegrityRepository):
        self._user_id, self._repository = user_id, repository

    def inspect(self) -> Result[RecordInspection]:
        try:
            return Result.success(self._repository.inspect(self._user_id))
        except Exception as error:
            return Result.failure(infrastructure_failure("record_check_failed", error, logger_name=__name__))

    def archive_invalid(self, expected: RecordInspection, destination: Path) -> Result[int]:
        try:
            return Result.success(self._repository.archive_invalid(self._user_id, expected, destination))
        except ValueError as error:
            if str(error) in {"worklog_entry_conflict", "record_recovery_timer_active"}:
                return Result.failure(ValidationError(str(error), str(error)))
            return Result.failure(infrastructure_failure("record_recovery_failed", error, logger_name=__name__))
        except Exception as error:
            return Result.failure(infrastructure_failure("record_recovery_failed", error, logger_name=__name__))
