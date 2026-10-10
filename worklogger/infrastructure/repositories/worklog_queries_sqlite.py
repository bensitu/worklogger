"""SQLite worklog queries."""

from __future__ import annotations

from datetime import date

from worklogger.domain.worklog.models import WorkLog
from worklogger.domain.worklog.search import EntryCursor, EntryPage
from worklogger.domain.worklog.rules import aggregate_days
from worklogger.infrastructure.repositories._mapping import map_rows, parse_date
from worklogger.infrastructure.repositories.worklog_mapping_sqlite import WorkLogStorage


class SQLiteWorkLogQueries:
    def __init__(self, storage: WorkLogStorage):
        self._storage = storage

    def search_entries(self, user_id, criteria, *, cursor=None, limit=100):
        if type(limit) is not int or not 1 <= limit <= 250 or not self._storage.supports_entries:
            raise ValueError("record_search_invalid")
        conditions = ["w.user_id=?", "w.d BETWEEN ? AND ?", "date(w.d,'+0 days')=w.d"]
        parameters = [user_id, criteria.start.isoformat(), criteria.end.isoformat()]
        for column, value in (("work_type", criteria.work_type), ("project_id", criteria.project_id), ("work_item_id", criteria.work_item_id)):
            if value is not None:
                conditions.append(f"w.{column}=?")
                parameters.append(value)
        if criteria.unclassified:
            conditions.append("w.project_id IS NULL")
        if criteria.text:
            pattern = "%" + criteria.text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            conditions.append("(w.note LIKE ? ESCAPE '\\' OR w.project_label LIKE ? ESCAPE '\\' OR w.work_item_label LIKE ? ESCAPE '\\')")
            parameters.extend((pattern, pattern, pattern))
        if cursor is not None:
            conditions.append("(w.d,COALESCE(w.start,''),w.id)>(?,?,?)")
            parameters.extend((cursor.day, cursor.start, cursor.entry_id))
        with self._storage.connection_factory.connection() as connection:
            rows = connection.execute(self._storage.select + " WHERE " + " AND ".join(conditions)
                + " ORDER BY w.d,COALESCE(w.start,''),w.id LIMIT ?", (*parameters, limit + 1)).fetchall()
        next_cursor = EntryCursor(rows[limit - 1]["d"], rows[limit - 1]["start"] or "", rows[limit - 1]["id"]) if len(rows) > limit else None
        return EntryPage(map_rows(rows[:limit], self._storage.from_row), next_cursor)

    def get_for_day(self, user_id: int, day: date) -> WorkLog | None:
        if self._storage.supports_entries:
            summaries = aggregate_days(self.list_for_day(user_id, day))
            return summaries[0] if summaries else None
        with self._storage.connection_factory.connection() as connection:
            row = connection.execute(
                self._storage.select + "WHERE w.user_id=? AND w.d=?",
                (user_id, day.isoformat()),
            ).fetchone()
        return self._storage.from_row(row) if row else None

    def list_for_month(
        self, user_id: int, year: int, month: int
    ) -> tuple[WorkLog, ...]:
        prefix = f"{int(year):04d}-{int(month):02d}"
        with self._storage.connection_factory.connection() as connection:
            rows = connection.execute(
                self._storage.select
                + "WHERE w.user_id=? AND w.d BETWEEN ? AND ? ORDER BY w.d",
                (user_id, f"{prefix}-01", f"{prefix}-31"),
            ).fetchall()
        return aggregate_days(map_rows(rows, self._storage.from_row))

    def list_range(self, user_id: int, start: date, end: date) -> tuple[WorkLog, ...]:
        with self._storage.connection_factory.connection() as connection:
            rows = connection.execute(
                self._storage.select
                + "WHERE w.user_id=? AND w.d BETWEEN ? AND ? ORDER BY w.d",
                (user_id, start.isoformat(), end.isoformat()),
            ).fetchall()
        return aggregate_days(map_rows(rows, self._storage.from_row))

    def list_entries_range(self, user_id, start, end, *, limit=50001):
        if type(limit) is not int or not 1 <= limit <= 50001:
            raise ValueError("record_search_invalid")
        with self._storage.connection_factory.connection() as connection:
            rows = connection.execute(self._storage.select + " WHERE w.user_id=? AND w.d BETWEEN ? AND ? ORDER BY w.d,w.start,w.id LIMIT ?",
                                      (user_id, start.isoformat(), end.isoformat(), limit)).fetchall()
        return map_rows(rows, self._storage.from_row)

    def list_all(self, user_id: int) -> tuple[WorkLog, ...]:
        with self._storage.connection_factory.connection() as connection:
            rows = connection.execute(
                self._storage.select + "WHERE w.user_id=? ORDER BY w.d",
                (user_id,),
            ).fetchall()
        return aggregate_days(map_rows(rows, self._storage.from_row))

    def list_export_rows(self, user_id: int) -> tuple[WorkLog, ...]:
        with self._storage.connection_factory.transaction(write=False) as connection:
            records = map_rows(
                connection.execute(
                    self._storage.select + "WHERE w.user_id=? ORDER BY w.d,w.start",
                    (user_id,),
                ).fetchall(),
                self._storage.from_row,
            )
            if not self._storage.separate_notes:
                return records
            condition = (
                ""
                if self._storage.supports_entries
                else "AND NOT EXISTS (SELECT 1 FROM worklog WHERE worklog.user_id=daily_notes.user_id AND worklog.d=daily_notes.d)"
            )
            rows = connection.execute(
                "SELECT d, content FROM daily_notes WHERE user_id=? AND content<>'' "
                + condition,
                (user_id,),
            ).fetchall()
        notes = map_rows(
            rows,
            lambda row: WorkLog(user_id, parse_date(row["d"]), note=row["content"]),
        )
        return tuple(sorted((*records, *notes), key=lambda record: record.day))

    def list_for_day(self, user_id: int, day: date) -> tuple[WorkLog, ...]:
        with self._storage.connection_factory.connection() as connection:
            rows = connection.execute(
                self._storage.select
                + "WHERE w.user_id=? AND w.d=? ORDER BY w.start,w.id",
                (user_id, day.isoformat()),
            ).fetchall()
        return map_rows(rows, self._storage.from_row)

    def get_entry(self, user_id: int, entry_id: int) -> WorkLog | None:
        with self._storage.connection_factory.connection() as connection:
            row = connection.execute(
                self._storage.select + "WHERE w.user_id=? AND w.id=?",
                (user_id, entry_id),
            ).fetchone()
        return self._storage.from_row(row) if row else None

    def existing_dates(self, user_id: int, dates) -> set[date]:
        values = tuple(sorted(day.isoformat() for day in dates))
        existing = set()
        with self._storage.connection_factory.connection() as connection:
            for index in range(0, len(values), 256):
                chunk = values[index : index + 256]
                placeholders = ",".join("?" for _ in chunk)
                query = (
                    f"SELECT d FROM worklog WHERE user_id=? AND d IN ({placeholders})"
                )
                parameters = (user_id, *chunk)
                if self._storage.separate_notes:
                    query += f" UNION SELECT d FROM daily_notes WHERE user_id=? AND d IN ({placeholders}) AND content<>''"
                    parameters += (user_id, *chunk)
                existing.update(
                    parse_date(row[0]) for row in connection.execute(query, parameters)
                )
        return existing
