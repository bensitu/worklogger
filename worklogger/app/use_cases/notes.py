"""Daily note use cases."""

from __future__ import annotations

from worklogger.app.commands.note_commands import SaveDailyNoteCommand
from worklogger.app.queries.note_queries import GetDailyNoteQuery
from worklogger.domain.notes.models import DailyNote
from worklogger.domain.notes.repositories import DailyNoteRepository
from worklogger.domain.shared.errors import ConflictError, InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result


class GetDailyNoteHandler:
    def __init__(self, repository: DailyNoteRepository) -> None:
        self._repository = repository

    def handle(self, query: GetDailyNoteQuery) -> Result[DailyNote]:
        try:
            return Result.success(self._repository.get_for_day(query.user_id, query.day))
        except Exception:
            return Result.failure(InfrastructureError("note_load_failed", "note_load_failed"))

    def list_range(self, user_id, start, end) -> Result[tuple[DailyNote, ...]]:
        try:
            return Result.success(self._repository.list_range(user_id, start, end))
        except Exception:
            return Result.failure(InfrastructureError("note_load_failed", "note_load_failed"))


class SaveDailyNoteHandler:
    def __init__(self, repository: DailyNoteRepository) -> None:
        self._repository = repository

    def handle(self, command: SaveDailyNoteCommand) -> Result[DailyNote]:
        if not isinstance(command.content, str):
            return Result.failure(
                ValidationError("note_content_must_be_string", "note_content_must_be_string")
            )
        note = DailyNote(
            user_id=command.user_id,
            day=command.day,
            content=command.content,
        )
        try:
            if command.expected_content is None:
                self._repository.save(note)
            else:
                self._repository.save(note, expected_content=command.expected_content)
        except ValueError as exc:
            if str(exc) == "note_conflict":
                return Result.failure(ConflictError("note_conflict", "note_conflict"))
            return Result.failure(ValidationError(str(exc), str(exc)))
        except Exception:
            return Result.failure(InfrastructureError("note_save_failed", "note_save_failed"))
        return Result.success(note)
