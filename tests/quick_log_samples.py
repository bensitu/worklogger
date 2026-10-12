"""Stored historical quick log fixtures for compatibility and note transfer checks."""

from dataclasses import replace
from datetime import datetime, timezone


def insert_previous_entry(factory, entry):
    created_at = (entry.created_at or datetime(2026, 1, 1, tzinfo=timezone.utc)).replace(microsecond=0)
    with factory.transaction(write=True) as connection:
        cursor = connection.execute(
            "INSERT INTO quick_logs(user_id,date,time,end_time,description,created_at) VALUES(?,?,?,?,?,?)",
            (entry.user_id, entry.day.isoformat(), entry.start_time, entry.end_time, entry.description,
             created_at.isoformat(timespec="seconds")),
        )
        identifier = cursor.lastrowid
    return replace(entry, id=identifier, created_at=created_at)
