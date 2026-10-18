"""Shared stored-worklog schema and row mapping."""

from __future__ import annotations

import math
import sqlite3

from worklogger.domain.worklog.models import CustomEntryType, CustomWorkMode, EntryCategory, WorkLog, decode_work_mode
from worklogger.domain.projects.models import WorkContext
from worklogger.domain.worklog.rules import (
    decode_entry_type,
    normalize_work_log,
    calc_shift_span_hours,
    parse_time,
)
from worklogger.infrastructure.database.connection import SQLiteConnectionFactory
from worklogger.infrastructure.repositories._mapping import parse_date, parse_offset_datetime


class WorkLogStorage:
    def __init__(self, connection_factory: SQLiteConnectionFactory) -> None:
        self.connection_factory = connection_factory
        self.select = ('SELECT w.user_id,w.d,w.start,w.end,w."break",w.note,w.entry_type,w.overnight,'
                       'w.started_at,w.ended_at,w.id,w.revision,w.capture_id,w.entry_type_label,w.entry_type_category,'
                       'w.project_id,w.work_item_id,w.project_label,w.work_item_label,w.work_mode,w.work_mode_label FROM worklog AS w ')

    @staticmethod
    def values(record: WorkLog) -> tuple:
        return (
            record.user_id,
            record.day.isoformat(),
            record.start_time,
            record.end_time,
            record.break_hours,
            record.note,
            record.entry_type.value,
            int(record.is_overnight),
            record.started_at.isoformat() if record.started_at else None,
            record.ended_at.isoformat() if record.ended_at else None,
        )

    def entry_values(self, record: WorkLog) -> tuple:
        definition, context = record.entry_type, record.context
        snapshot = (definition.label, definition.category) if isinstance(definition, CustomEntryType) else ("", "")
        return self.values(record) + snapshot + (
            context.project_id, context.work_item_id, context.project_label, context.work_item_label,
            record.work_mode.value if record.work_mode is not None else None,
            record.work_mode.label if isinstance(record.work_mode, CustomWorkMode) else "",
        )

    @staticmethod
    def from_row(row: sqlite3.Row) -> WorkLog:
        break_hours = float(row["break"] or 0)
        if not math.isfinite(break_hours) or not 0 <= break_hours <= 24:
            raise ValueError("stored_work_log_invalid")
        start, end = parse_offset_datetime(row["started_at"]), parse_offset_datetime(row["ended_at"])
        if start is None or end is None:
            start = end = None
        record = WorkLog(
            user_id=int(row["user_id"]),
            day=parse_date(row["d"]),
            start_time=parse_time(row["start"]),
            end_time=parse_time(row["end"]),
            break_hours=break_hours,
            note=str(row["note"] or ""),
            entry_type=decode_entry_type(
                row["entry_type"],
                label=row["entry_type_label"], category=row["entry_type_category"], strict=True,
            ),
            overnight=bool(int(row["overnight"] or 0)),
            started_at=start, ended_at=end, id=int(row["id"]), revision=int(row["revision"]), capture_id=row["capture_id"],
            context=WorkContext(row["project_id"], row["work_item_id"], row["project_label"], row["work_item_label"]),
            work_mode=decode_work_mode(row["work_mode"], row["work_mode_label"]),
        )
        if record.entry_type.category != EntryCategory.WORK and (
                record.work_mode is not None or record.context != WorkContext()):
            raise ValueError("stored_work_log_invalid")
        if (row["start"] and not record.start_time) or (row["end"] and not record.end_time):
            raise ValueError("stored_work_log_invalid")
        if bool(record.start_time) != bool(record.end_time) or (
                record.has_times and record.started_at is None
                and calc_shift_span_hours(record.start_time, record.end_time) is None):
            raise ValueError("stored_work_log_invalid")
        return (
            normalize_work_log(record)
            if record.started_at is not None or record.ended_at is not None
            else record
        )
