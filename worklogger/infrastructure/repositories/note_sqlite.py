"""SQLite daily note repository backed by the worklog note column."""

from __future__ import annotations

from datetime import date

from worklogger.domain.notes.models import DailyNote
from worklogger.infrastructure.database.connection import SQLiteConnectionFactory


class SQLiteDailyNoteRepository:
    def __init__(self, connection_factory: SQLiteConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def get_for_day(self, user_id: int, day: date) -> DailyNote:
        with self._connection_factory.connection() as connection:
            row = connection.execute(
                """
                SELECT note FROM worklog
                WHERE user_id=? AND d=?
                """,
                (user_id, day.isoformat()),
            ).fetchone()
        return DailyNote(
            user_id=user_id,
            day=day,
            content=str(row["note"] or "") if row else "",
        )

    def save(self, note: DailyNote) -> None:
        with self._connection_factory.transaction(write=True) as connection:
            connection.execute(
                """
                INSERT INTO worklog(user_id, d, start, end, "break", note, work_type, overnight)
                VALUES(?, ?, NULL, NULL, 0, ?, 'normal', 0)
                ON CONFLICT(user_id, d) DO UPDATE SET
                    note=excluded.note
                """,
                (note.user_id, note.day.isoformat(), note.content),
            )
