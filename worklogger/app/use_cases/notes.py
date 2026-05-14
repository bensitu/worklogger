"""Daily note use cases."""

from __future__ import annotations

from worklogger.app.commands.note_commands import SaveDailyNoteCommand
from worklogger.app.queries.note_queries import GetDailyNoteQuery
from worklogger.domain.notes.models import DailyNote
from worklogger.domain.notes.repositories import DailyNoteRepository
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result


class GetDailyNoteHandler:
    def __init__(self, repository: DailyNoteRepository) -> None:
        self._repository = repository

    def handle(self, query: GetDailyNoteQuery) -> Result[DailyNote]:
        return Result.success(self._repository.get_for_day(query.user_id, query.day))


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
        self._repository.save(note)
        return Result.success(note)
