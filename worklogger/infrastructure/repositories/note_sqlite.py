"""Independent SQLite daily notes with optimistic content checks."""

from __future__ import annotations

from datetime import date

from worklogger.domain.notes.models import DailyNote
from worklogger.domain.notes.preferences import NoteSharing, note_draft_key, note_sharing_key
from worklogger.infrastructure.database.connection import SQLiteConnectionFactory
from worklogger.infrastructure.repositories._mapping import parse_date, map_rows


def save_note(connection, user_id: int, day: date, content: str, expected_content: str | None = None) -> None:
    row = connection.execute("SELECT content FROM daily_notes WHERE user_id=? AND d=?",
                             (user_id, day.isoformat())).fetchone()
    if expected_content is not None and (row[0] if row else "") != expected_content:
        raise ValueError("note_conflict")
    connection.execute(
        "INSERT INTO daily_notes(user_id, d, content) VALUES(?, ?, ?) "
        "ON CONFLICT(user_id, d) DO UPDATE SET content=excluded.content",
        (user_id, day.isoformat(), content),
    )


class SQLiteDailyNoteRepository:
    def __init__(self, connection_factory: SQLiteConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def get_for_day(self, user_id: int, day: date) -> DailyNote:
        with self._connection_factory.connection() as connection:
            row = connection.execute(
                """
                SELECT content FROM daily_notes
                WHERE user_id=? AND d=?
                """,
                (user_id, day.isoformat()),
            ).fetchone()
        return DailyNote(
            user_id=user_id,
            day=day,
            content=str(row["content"] or "") if row else "",
        )

    def list_range(self, user_id: int, start: date, end: date) -> tuple[DailyNote, ...]:
        with self._connection_factory.connection() as connection:
            rows = connection.execute("SELECT d, content FROM daily_notes WHERE user_id=? AND d BETWEEN ? AND ? ORDER BY d",
                                      (user_id, start.isoformat(), end.isoformat())).fetchall()
        return map_rows(rows, lambda row: DailyNote(user_id, parse_date(row["d"]), str(row["content"])))

    def search(self, user_id: int, query: str, *, limit: int = 50) -> tuple[DailyNote, ...]:
        term = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        with self._connection_factory.connection() as connection:
            rows = connection.execute("""SELECT d, content FROM daily_notes
                WHERE user_id=? AND content<>'' AND content LIKE ? ESCAPE '\\'
                UNION SELECT q.date AS d, COALESCE(n.content, '') AS content FROM quick_logs q
                LEFT JOIN daily_notes n ON n.user_id=q.user_id AND n.d=q.date
                WHERE q.user_id=? AND q.description LIKE ? ESCAPE '\\'
                ORDER BY d DESC LIMIT ?""", (user_id, term, user_id, term, max(1, min(limit, 100)))).fetchall()
        return map_rows(rows, lambda row: DailyNote(user_id, parse_date(row["d"]), str(row["content"])))

    def save(self, note: DailyNote, *, expected_content: str | None = None,
             sharing: NoteSharing | None = None, clear_draft: bool = False) -> None:
        with self._connection_factory.transaction(write=True) as connection:
            save_note(connection, note.user_id, note.day, note.content, expected_content)
            if sharing is not None:
                connection.execute("INSERT INTO settings(user_id,key,value) VALUES(?,?,?) "
                    "ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value",
                    (note.user_id, note_sharing_key(note.day), sharing.encode()))
            if clear_draft:
                connection.execute("DELETE FROM settings WHERE user_id=? AND key=?", (note.user_id, note_draft_key(note.day)))
