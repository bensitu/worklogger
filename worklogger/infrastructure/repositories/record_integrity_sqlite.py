"""Preserve invalid record values before explicitly removing them."""

import base64
import hashlib
import json
import math
from pathlib import Path

from worklogger.app.use_cases.record_integrity import InvalidRecord, RecordInspection
from worklogger.domain.worklog.rules import normalize_work_log
from worklogger.infrastructure.database.current_schema import CURRENT_SCHEMA_VERSION
from worklogger.infrastructure.files import atomic_destination
from worklogger.infrastructure.repositories.worklog_mapping_sqlite import WorkLogStorage

_MAX_ARCHIVE_BYTES = 64 * 1024 * 1024


def _stored_value(value):
    if isinstance(value, bytes):
        return {"encoding": "base64", "value": base64.b64encode(value).decode("ascii")}
    if isinstance(value, float) and not math.isfinite(value):
        return {"encoding": "float", "value": str(value)}
    return value


class SQLiteRecordIntegrity:
    def __init__(self, factory):
        self._factory = factory

    def _scan(self, connection, user_id):
        records, issues, size = [], [], 0
        for row in connection.execute("SELECT * FROM worklog WHERE user_id=? ORDER BY id", (user_id,)):
            try:
                record = WorkLogStorage.from_row(row)
                if any(row[key] not in (None, "") for key in ("started_at", "ended_at")) and (
                        record.started_at is None or record.ended_at is None):
                    raise ValueError("stored_work_log_invalid")
                normalize_work_log(record)
            except (ValueError, TypeError, OverflowError):
                values = {key: _stored_value(row[key]) for key in row.keys()}
                size += len(json.dumps(values, ensure_ascii=True, allow_nan=False).encode("utf-8"))
                if size > _MAX_ARCHIVE_BYTES:
                    raise ValueError("record_archive_too_large")
                records.append(values)
                issues.append(InvalidRecord(row["id"], str(row["d"])[:80]))
        document = json.dumps({"format": 1, "schema": CURRENT_SCHEMA_VERSION, "user_id": user_id,
                               "records": records}, ensure_ascii=True, allow_nan=False, sort_keys=True).encode("utf-8")
        if len(document) > _MAX_ARCHIVE_BYTES:
            raise ValueError("record_archive_too_large")
        return RecordInspection(tuple(issues), hashlib.sha256(document).hexdigest()), document

    def inspect(self, user_id):
        with self._factory.transaction(write=False) as connection:
            return self._scan(connection, user_id)[0]

    def archive_invalid(self, user_id, expected, destination):
        destination = Path(destination)
        if destination.suffix.lower() != ".json":
            raise ValueError("record_archive_invalid")
        with self._factory.transaction(write=True) as connection:
            timer = connection.execute("SELECT value FROM settings WHERE user_id=? AND key='time_entry_timer'",
                                       (user_id,)).fetchone()
            if timer and timer[0]:
                raise ValueError("record_recovery_timer_active")
            current, document = self._scan(connection, user_id)
            if current != expected:
                raise ValueError("worklog_entry_conflict")
            if not current.records:
                return 0
            with atomic_destination(destination, overwrite=False) as temporary:
                temporary.write_bytes(document)
            connection.executemany("DELETE FROM worklog WHERE user_id=? AND id=?",
                                   ((user_id, row.record_id) for row in current.records))
            return len(current.records)
