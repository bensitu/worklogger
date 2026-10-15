"""Independent SQLite daily notes with optimistic content checks."""

from __future__ import annotations

from datetime import date

from worklogger.domain.notes.models import DailyNote, NoteHistoryFilter, NoteHistoryPage, NotePreview
from worklogger.domain.notes.preferences import NoteSharing, note_draft_key, note_sharing_key
from worklogger.domain.quicklog.models import QuickLog
from worklogger.domain.quicklog.rules import contains_quick_log_reference
from worklogger.infrastructure.database.connection import SQLiteConnectionFactory
from worklogger.infrastructure.repositories._mapping import parse_date, parse_datetime, map_rows


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

    def browse(self, user_id: int, filters: NoteHistoryFilter) -> NoteHistoryPage:
        text = filters.text.strip()[:256]
        term = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        note_match = " AND content LIKE ? ESCAPE '\\'" if text else ""
        entry_match = " AND description LIKE ? ESCAPE '\\'" if text else ""
        bounds = (user_id, filters.start.isoformat(), filters.end.isoformat())
        parameters = (*bounds, *((term,) if text else ()),
                      *bounds, *((term,) if text else ()))
        matching_dates = f"""WITH matched(d) AS (
            SELECT d FROM daily_notes WHERE user_id=? AND d BETWEEN ? AND ?
                AND content<>'' {note_match}
            UNION SELECT date FROM quick_logs WHERE user_id=? AND date BETWEEN ? AND ?
                AND description<>'' {entry_match}
        ) """
        cursor_clause = "WHERE m.d < ?" if filters.before else ""
        cursor = (filters.before.isoformat(),) if filters.before else ()
        with self._connection_factory.transaction(write=False) as connection:
            total = connection.execute(matching_dates + "SELECT COUNT(*) FROM matched", parameters).fetchone()[0]
            rows = connection.execute(matching_dates + f"""
                SELECT m.d, substr(COALESCE(NULLIF(n.content, ''),
                    (SELECT description FROM quick_logs WHERE user_id=? AND date=m.d
                     AND description<>'' ORDER BY id LIMIT 1), ''), 1, 512) AS preview
                FROM matched m LEFT JOIN daily_notes n ON n.user_id=? AND n.d=m.d
                {cursor_clause} ORDER BY m.d DESC LIMIT ?
                """, (*parameters, user_id, user_id, *cursor, filters.limit + 1)).fetchall()
        notes = map_rows(rows[:filters.limit], lambda row: NotePreview(
            parse_date(row["d"]), " ".join(str(row["preview"]).split())[:160]))
        return NoteHistoryPage(notes, total, notes[-1].day if len(rows) > filters.limit else None)

    def save(self, note: DailyNote, *, expected_content: str | None = None,
             sharing: NoteSharing | None = None, clear_draft: bool = False,
             expected_sharing: NoteSharing | None = None,
             previous_entries_to_remove: tuple[QuickLog, ...] = ()) -> None:
        with self._connection_factory.transaction(write=True) as connection:
            if expected_sharing is not None:
                row = connection.execute("SELECT value FROM settings WHERE user_id=? AND key=?",
                                         (note.user_id, note_sharing_key(note.day))).fetchone()
                if NoteSharing.decode(row[0] if row else None) != expected_sharing:
                    raise ValueError("note_conflict")
            save_note(connection, note.user_id, note.day, note.content, expected_content)
            if sharing is not None:
                connection.execute("INSERT INTO settings(user_id,key,value) VALUES(?,?,?) "
                    "ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value",
                    (note.user_id, note_sharing_key(note.day), sharing.encode()))
            if clear_draft:
                connection.execute("DELETE FROM settings WHERE user_id=? AND key=?", (note.user_id, note_draft_key(note.day)))
            for entry in previous_entries_to_remove:
                if (entry.id is None or entry.user_id != note.user_id or entry.day != note.day
                        or not contains_quick_log_reference(note.content, entry)):
                    raise ValueError("note_conflict")
                current = connection.execute("SELECT created_at FROM quick_logs WHERE id=? AND user_id=? AND date=?",
                                             (entry.id, note.user_id, note.day.isoformat())).fetchone()
                if current is None or parse_datetime(current["created_at"]) != entry.created_at:
                    raise ValueError("note_conflict")
                cursor = connection.execute("""DELETE FROM quick_logs
                    WHERE id=? AND user_id=? AND date=? AND description=?
                    AND COALESCE(time, '')=? AND COALESCE(end_time, '')=?""",
                    (entry.id, note.user_id, note.day.isoformat(), entry.description, entry.start_time, entry.end_time))
                if cursor.rowcount != 1:
                    raise ValueError("note_conflict")

    def delete(self, user_id: int, day: date, *, expected_content: str,
               expected_sharing: NoteSharing) -> None:
        with self._connection_factory.transaction(write=True) as connection:
            row = connection.execute("SELECT content FROM daily_notes WHERE user_id=? AND d=?",
                                     (user_id, day.isoformat())).fetchone()
            if (row[0] if row else "") != expected_content:
                raise ValueError("note_conflict")
            sharing = connection.execute("SELECT value FROM settings WHERE user_id=? AND key=?",
                                         (user_id, note_sharing_key(day))).fetchone()
            if NoteSharing.decode(sharing[0] if sharing else None) != expected_sharing:
                raise ValueError("note_conflict")
            connection.execute("DELETE FROM daily_notes WHERE user_id=? AND d=?", (user_id, day.isoformat()))
            connection.execute("DELETE FROM settings WHERE user_id=? AND key IN (?, ?)",
                               (user_id, note_draft_key(day), note_sharing_key(day)))
