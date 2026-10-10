"""Shared stored-worklog schema and row mapping."""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime

from worklogger.domain.worklog.models import CustomWorkType, WorkLog
from worklogger.domain.projects.models import WorkContext
from worklogger.domain.worklog.rules import (
    decode_work_type,
    normalize_work_log,
    parse_time,
)
from worklogger.infrastructure.database.connection import SQLiteConnectionFactory
from worklogger.infrastructure.repositories._mapping import parse_date


class WorkLogStorage:
    def __init__(self, connection_factory: SQLiteConnectionFactory) -> None:
        self.connection_factory = connection_factory
        with connection_factory.connection() as connection:
            self.separate_notes = (
                connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='daily_notes'"
                ).fetchone()
                is not None
            )
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(worklog)")
            }
            self.timestamps = "started_at" in columns
            self.supports_entries = "id" in columns
            self.type_snapshots = "work_type_label" in columns
            self.work_context = "project_id" in columns
            self.change_history = connection.execute("SELECT 1 FROM sqlite_master WHERE name='entry_changes'").fetchone() is not None
        self.select = 'SELECT w.user_id, w.d, w.start, w.end, w."break", '
        self.select += (
            "COALESCE(n.content, w.note) AS note"
            if self.separate_notes and not self.supports_entries
            else "w.note"
        )
        self.select += ", w.work_type, w.overnight"
        if self.timestamps:
            self.select += ", w.started_at, w.ended_at"
        if self.supports_entries:
            self.select += ", w.id, w.revision, w.capture_id"
        if self.type_snapshots:
            self.select += ", w.work_type_label, w.work_type_category"
        if self.work_context:
            self.select += ", w.project_id, w.work_item_id, w.project_label, w.work_item_label"
        self.select += " FROM worklog AS w "
        if self.separate_notes and not self.supports_entries:
            self.select += (
                "LEFT JOIN daily_notes AS n ON n.user_id=w.user_id AND n.d=w.d "
            )

    @staticmethod
    def values(record: WorkLog) -> tuple:
        return (
            record.user_id,
            record.day.isoformat(),
            record.start_time,
            record.end_time,
            record.break_hours,
            record.note,
            record.work_type.value,
            int(record.is_overnight),
            record.started_at.isoformat() if record.started_at else None,
            record.ended_at.isoformat() if record.ended_at else None,
        )

    def entry_values(self, record: WorkLog) -> tuple:
        if isinstance(record.work_type, CustomWorkType) and not self.type_snapshots:
            raise ValueError("database_version_unsupported")
        if record.context != WorkContext() and not self.work_context:
            raise ValueError("database_version_unsupported")
        values = self.values(record)
        if self.type_snapshots:
            definition = record.work_type
            values += (
                (definition.label, definition.category)
                if isinstance(definition, CustomWorkType)
                else ("", "")
            )
        if self.work_context:
            context = record.context
            values += (context.project_id, context.work_item_id, context.project_label, context.work_item_label)
        return values

    @staticmethod
    def from_row(row: sqlite3.Row) -> WorkLog:
        break_hours = float(row["break"] or 0)
        if not math.isfinite(break_hours) or not 0 <= break_hours <= 24:
            raise ValueError("stored_work_log_invalid")
        record = WorkLog(
            user_id=int(row["user_id"]),
            day=parse_date(row["d"]),
            start_time=parse_time(row["start"]),
            end_time=parse_time(row["end"]),
            break_hours=break_hours,
            note=str(row["note"] or ""),
            work_type=decode_work_type(
                row["work_type"],
                label=row["work_type_label"] if "work_type_label" in row.keys() else "",
                category=row["work_type_category"]
                if "work_type_category" in row.keys()
                else "",
            ),
            overnight=bool(int(row["overnight"] or 0)),
            started_at=datetime.fromisoformat(row["started_at"])
            if "started_at" in row.keys() and row["started_at"]
            else None,
            ended_at=datetime.fromisoformat(row["ended_at"])
            if "ended_at" in row.keys() and row["ended_at"]
            else None,
            id=int(row["id"]) if "id" in row.keys() else None,
            revision=int(row["revision"]) if "revision" in row.keys() else 0,
            capture_id=row["capture_id"] if "capture_id" in row.keys() else None,
            context=WorkContext(row["project_id"], row["work_item_id"], row["project_label"], row["work_item_label"])
                    if "project_id" in row.keys() else WorkContext(),
        )
        return (
            normalize_work_log(record)
            if record.started_at is not None or record.ended_at is not None
            else record
        )
