"""Daily memo presentation state, history references, and optional text editing."""

from datetime import date
from pathlib import Path

from worklogger.app.commands.ai_commands import RewriteTextCommand
from worklogger.app.use_cases.notes import DailyNotesService, NoteWorkspace
from worklogger.domain.notes.preferences import NoteSharing
from worklogger.domain.shared.result import Result
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.quicklog.rules import quick_log_reference


NoteEditorState = NoteWorkspace


class NoteEditorViewModel:
    def __init__(self, service: DailyNotesService, *, markdown_exporter, rewrite_handler, language="en_US"):
        self.service = service
        self._markdown_exporter, self._rewrite_handler, self._language = markdown_exporter, rewrite_handler, language

    @property
    def rewrite_available(self):
        return bool(getattr(self._rewrite_handler, "available", True))

    def load(self, day: date):
        return self.service.load(day)

    def save(self, state: NoteWorkspace, content: str, sharing: NoteSharing):
        return self.service.save(state.note.day, content, state.expected_content, sharing, state.expected_sharing)

    def save_draft(self, state: NoteWorkspace, content: str, sharing: NoteSharing):
        return self.service.save_draft(state.note.day, content, state.expected_content, sharing, state.expected_sharing)

    def discard_draft(self, day: date):
        return self.service.discard_draft(day)

    def reload(self, day: date):
        loaded = self.service.load(day, recover_draft=False)
        if not loaded.ok:
            return loaded
        cleared = self.service.discard_draft(day)
        return loaded if cleared.ok else Result.failure(cleared.error)

    def search(self, query: str):
        return self.service.search(query)

    def insert_previous_entries(self, state: NoteWorkspace, content: str) -> str:
        lines = []
        for entry in state.previous_entries:
            line = quick_log_reference(entry)
            if line not in content.splitlines():
                lines.append(line)
        return content.rstrip() + ("\n\n" if content.strip() else "") + "\n".join(lines) if lines else content

    def export_markdown(self, destination: Path, content: str):
        return self._markdown_exporter.export_markdown(destination, content)

    def rewrite(self, content: str):
        result = self._rewrite_handler.handle(RewriteTextCommand(self.service.user_id, content,
                                               context="daily_note", language=self._language))
        if not result.ok or result.value is None:
            return Result.failure(result.error or ValidationError("rewrite_failed", "rewrite_failed"))
        return Result.success(result.value.content)
