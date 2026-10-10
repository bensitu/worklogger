"""Daily note use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from worklogger.app.commands.note_commands import SaveDailyNoteCommand
from worklogger.app.queries.note_queries import GetDailyNoteQuery
from worklogger.domain.notes.models import DailyNote
from worklogger.domain.notes.preferences import NoteSharing, note_draft_key, note_sharing_key
from worklogger.domain.notes.repositories import DailyNoteRepository
from worklogger.domain.quicklog.models import QuickLog
from worklogger.domain.quicklog.repositories import QuickLogRepository
from worklogger.domain.settings.repositories import SettingsRepository
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
        if len(command.content.encode("utf-8")) > 1024 * 1024:
            return Result.failure(ValidationError("note_save_failed", "note_save_failed"))
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


@dataclass(frozen=True)
class NoteWorkspace:
    note: DailyNote
    content: str
    expected_content: str
    sharing: NoteSharing
    previous_entries: tuple[QuickLog, ...] = ()
    recovered_draft: bool = False
    saved_sharing: NoteSharing = NoteSharing()
    expected_sharing: NoteSharing = NoteSharing()


class DailyNotesService:
    def __init__(self, *, user_id: int, notes: DailyNoteRepository, settings: SettingsRepository,
                 previous_entries: QuickLogRepository):
        self.user_id, self.notes, self.settings, self.previous_entries = user_id, notes, settings, previous_entries

    def _run(self, operation, *, error_code="note_save_failed"):
        try:
            return Result.success(operation())
        except ValueError as exc:
            if str(exc) == "note_conflict":
                return Result.failure(ConflictError("note_conflict", "note_conflict"))
            return Result.failure(ValidationError(error_code, error_code))
        except Exception:
            return Result.failure(InfrastructureError(error_code, error_code))

    def load(self, day: date, *, recover_draft: bool = True) -> Result[NoteWorkspace]:
        def load():
            note = self.notes.get_for_day(self.user_id, day)
            sharing = NoteSharing.decode(self.settings.get(self.user_id, note_sharing_key(day)))
            saved_sharing = sharing
            expected_sharing = sharing
            draft_raw = self.settings.get(self.user_id, note_draft_key(day)) if recover_draft else None
            content, expected, recovered = note.content, note.content, False
            if draft_raw:
                if len(draft_raw) > 4 * 1024 * 1024:
                    raise ValueError("note_load_failed")
                draft = json.loads(draft_raw)
                content, expected = draft["content"], draft["expected_content"]
                if not isinstance(content, str) or not isinstance(expected, str):
                    raise ValueError("note_load_failed")
                sharing = NoteSharing.decode(json.dumps(draft.get("sharing", {})))
                expected_sharing = NoteSharing.decode(json.dumps(draft.get("expected_sharing", {})))
                recovered = content != note.content or sharing != NoteSharing.decode(self.settings.get(self.user_id, note_sharing_key(day)))
            return NoteWorkspace(note, content, expected, sharing,
                                 self.previous_entries.list_for_day(self.user_id, day), recovered, saved_sharing, expected_sharing)
        return self._run(load, error_code="note_load_failed")

    def save(self, day: date, content: str, expected_content: str, sharing: NoteSharing,
             expected_sharing: NoteSharing | None = None, *, previous_entries_to_remove: tuple[QuickLog, ...] = ()):
        def save():
            if not isinstance(content, str) or len(content.encode("utf-8")) > 1024 * 1024:
                raise ValueError("note_save_failed")
            entries = self.previous_entries.list_for_day(self.user_id, day)
            note = DailyNote(self.user_id, day, content)
            self.notes.save(note, expected_content=expected_content, sharing=sharing, clear_draft=True,
                            expected_sharing=expected_sharing, previous_entries_to_remove=previous_entries_to_remove)
            removed_ids = {entry.id for entry in previous_entries_to_remove}
            entries = tuple(entry for entry in entries if entry.id not in removed_ids)
            return NoteWorkspace(note, content, content, sharing, entries, saved_sharing=sharing, expected_sharing=sharing)
        return self._run(save)

    def save_draft(self, day: date, content: str, expected_content: str, sharing: NoteSharing,
                   expected_sharing: NoteSharing = NoteSharing()):
        def save():
            if len(content.encode("utf-8")) > 1024 * 1024 or len(expected_content.encode("utf-8")) > 1024 * 1024:
                raise ValueError("note_load_failed")
            raw = json.dumps({"content": content, "expected_content": expected_content,
                              "sharing": {"reports": sharing.reports, "ai": sharing.ai},
                              "expected_sharing": {"reports": expected_sharing.reports, "ai": expected_sharing.ai}}, ensure_ascii=False)
            self.settings.set(self.user_id, note_draft_key(day), raw)
        return self._run(save)

    def discard_draft(self, day: date):
        return self._run(lambda: self.settings.delete(self.user_id, note_draft_key(day)))

    def search(self, query: str):
        return self._run(lambda: self.notes.search(self.user_id, query.strip()[:256]), error_code="note_load_failed")
