"""SQLite calendar event repository."""

from __future__ import annotations

from datetime import date
import sqlite3

from worklogger.domain.calendar.models import CalendarEvent
from worklogger.infrastructure.database.connection import SQLiteConnectionFactory
from worklogger.infrastructure.repositories._mapping import parse_date


class SQLiteCalendarEventRepository:
    def __init__(self, connection_factory: SQLiteConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def list_for_day(self, user_id: int, day: date) -> tuple[CalendarEvent, ...]:
        with self._connection_factory.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM calendar_events
                WHERE user_id=? AND date=?
                ORDER BY all_day DESC, start_time, id
                """,
                (user_id, day.isoformat()),
            ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def list_for_range(
        self,
        user_id: int,
        start_day: date,
        end_day: date,
    ) -> tuple[CalendarEvent, ...]:
        with self._connection_factory.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM calendar_events
                WHERE user_id=? AND date BETWEEN ? AND ?
                ORDER BY date, all_day DESC, start_time, id
                """,
                (user_id, start_day.isoformat(), end_day.isoformat()),
            ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def replace_all(self, user_id: int, events: tuple[CalendarEvent, ...]) -> int:
        with self._connection_factory.transaction(write=True) as connection:
            connection.execute(
                "DELETE FROM calendar_events WHERE user_id=?",
                (user_id,),
            )
            count = self._insert_many(connection, user_id, events)
        return count

    def add_many(self, user_id: int, events: tuple[CalendarEvent, ...]) -> int:
        with self._connection_factory.transaction(write=True) as connection:
            count = self._insert_many(connection, user_id, events)
        return count

    def clear(self, user_id: int) -> None:
        with self._connection_factory.transaction(write=True) as connection:
            connection.execute(
                "DELETE FROM calendar_events WHERE user_id=?",
                (user_id,),
            )

    @staticmethod
    def _insert_many(
        connection: sqlite3.Connection,
        user_id: int,
        events: tuple[CalendarEvent, ...],
    ) -> int:
        count = 0
        for event in events:
            connection.execute(
                """
                INSERT INTO calendar_events(
                    user_id,
                    date,
                    start_time,
                    end_time,
                    summary,
                    description,
                    location,
                    all_day,
                    source_file
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    event.day.isoformat(),
                    event.start_time,
                    event.end_time,
                    event.summary,
                    event.description,
                    event.location,
                    1 if event.all_day else 0,
                    event.source_file,
                ),
            )
            count += 1
        return count

    @staticmethod
    def _from_row(row: sqlite3.Row) -> CalendarEvent:
        return CalendarEvent(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            day=parse_date(row["date"]),
            summary=str(row["summary"]),
            start_time=row["start_time"],
            end_time=row["end_time"],
            description=str(row["description"] or ""),
            location=str(row["location"] or ""),
            all_day=bool(int(row["all_day"] or 0)),
            source_file=str(row["source_file"] or ""),
        )
