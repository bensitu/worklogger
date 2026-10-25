"""Account-scoped logical snapshots and transactional replacement of portable data."""

import base64
from datetime import date
import hashlib
import json
import re
from uuid import uuid4

from worklogger.domain.notes.preferences import NoteSharing
from worklogger.domain.settings.preferences import SETTINGS_DEFAULTS
from worklogger.domain.settings.validation import normalize_setting
from worklogger.domain.reporting.periods import validate_report_period
from worklogger.domain.cloud_backup import MAX_DOCUMENT_BYTES, STATE_KEY
from worklogger.domain.worklog.models import CustomWorkMode
from worklogger.infrastructure.database.current_schema import CURRENT_SCHEMA_VERSION, schema_columns
from worklogger.infrastructure.repositories.worklog_mapping_sqlite import WorkLogStorage

_TABLES = ("projects", "work_items", "entry_types", "work_modes", "worklog", "daily_notes", "quick_logs",
           "calendar_events", "reports", "report_revisions", "report_templates", "settings", "background_images")
_PORTABLE_SETTINGS = frozenset(key for key in SETTINGS_DEFAULTS
    if not key.startswith(("network_", "external_", "local_model", "enable_tray", "enable_menu_bar"))
    and key not in {"last_backup_at", "minimal_mode"})
_AUTONUMBER = {"worklog", "quick_logs", "calendar_events", "reports", "report_templates"}
_ORDER_COLUMNS = {table: "id" for table in _TABLES} | {
    "daily_notes": "d", "settings": "key", "background_images": "user_id",
}


def _portable_key(key):
    return key in _PORTABLE_SETTINGS or bool(re.fullmatch(r"daily_note_sharing:\d{4}-\d{2}-\d{2}", key))


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def document_digest(document):
    return hashlib.sha256(document).hexdigest()


class SQLitePersonalData:
    def __init__(self, factory, user_id, *, expected_username=None):
        self.factory, self.user_id = factory, user_id
        self.expected_username = expected_username
        self._columns = {table: tuple(column[0] for column in schema_columns()[table][0] if column[0] != "user_id")
                         for table in _TABLES}

    def capture(self):
        with self.factory.transaction(write=False) as connection:
            return self._capture(connection)

    def _capture(self, connection):
        owner = connection.execute("SELECT username FROM users WHERE id=?", (self.user_id,)).fetchone()
        if owner is None or (self.expected_username is not None and owner[0] != self.expected_username):
            raise ValueError("cloud_account_missing")
        tables = {}
        for table in _TABLES:
            if table == "report_revisions":
                rows = connection.execute("SELECT v.* FROM report_revisions v JOIN reports r ON r.id=v.report_id "
                                          "WHERE r.user_id=? ORDER BY v.report_id,v.revision", (self.user_id,))
            else:
                rows = connection.execute(
                    f'SELECT * FROM "{table}" WHERE user_id=? ORDER BY "{_ORDER_COLUMNS[table]}"', (self.user_id,))
            values = []
            for row in rows:
                value = {key: row[key] for key in self._columns[table]}
                if table == "settings" and not _portable_key(value["key"]):
                    continue
                if table == "background_images" and value["data"] is not None:
                    value["data"] = base64.b64encode(value["data"]).decode("ascii")
                values.append(value)
            tables[table] = values
        document = _json({"format": 1, "schema": CURRENT_SCHEMA_VERSION, "tables": tables})
        if len(document) > MAX_DOCUMENT_BYTES:
            raise ValueError("cloud_backup_too_large")
        return document

    def restore(self, document, *, expected_digest, before_replace, sync_state=None):
        tables = self._parse(document)
        with self.factory.transaction(write=False) as connection:
            timer = connection.execute("SELECT value FROM settings WHERE user_id=? AND key='time_entry_timer'", (self.user_id,)).fetchone()
            if timer and timer[0]:
                raise ValueError("cloud_timer_active")
            previous = self._capture(connection)
        if document_digest(previous) != expected_digest:
            raise ValueError("cloud_local_changed")
        before_replace(previous)
        with self.factory.transaction(write=True) as connection:
            timer = connection.execute("SELECT value FROM settings WHERE user_id=? AND key='time_entry_timer'", (self.user_id,)).fetchone()
            if timer and timer[0]:
                raise ValueError("cloud_timer_active")
            if document_digest(self._capture(connection)) != expected_digest:
                raise ValueError("cloud_local_changed")
            connection.execute("DELETE FROM entry_changes WHERE user_id=?", (self.user_id,))
            for table in reversed(_TABLES):
                if table == "report_revisions":
                    continue
                if table == "settings":
                    keys = [row[0] for row in connection.execute("SELECT key FROM settings WHERE user_id=?", (self.user_id,))
                            if _portable_key(row[0])]
                    connection.executemany("DELETE FROM settings WHERE user_id=? AND key=?", ((self.user_id, key) for key in keys))
                else:
                    connection.execute(f'DELETE FROM "{table}" WHERE user_id=?', (self.user_id,))
            self._insert(connection, tables)
            digest = document_digest(self._capture(connection))
            if sync_state is not None:
                connection.execute("INSERT INTO settings(user_id,key,value) VALUES(?,?,?) "
                    "ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value",
                    (self.user_id, STATE_KEY, _json({**sync_state, "local_digest": digest}).decode()))
            return digest

    def _parse(self, document):
        if len(document) > MAX_DOCUMENT_BYTES:
            raise ValueError("cloud_backup_too_large")
        try:
            value = json.loads(document)
            if isinstance(value, dict) and value.get("schema") == 17 and isinstance(value.get("tables"), dict):
                if set(value["tables"]) != set(_TABLES) - {"work_modes"}:
                    raise ValueError("cloud_backup_invalid")
                value["schema"] = CURRENT_SCHEMA_VERSION
                value["tables"]["work_modes"] = []
                for row in value["tables"].get("worklog", []):
                    if not isinstance(row, dict) or "work_mode_label" in row:
                        raise ValueError("cloud_backup_invalid")
                    row["work_mode_label"] = ""
            if isinstance(value, dict) and value.get("schema") == 18:
                value["schema"] = CURRENT_SCHEMA_VERSION
            if (set(value) != {"format", "schema", "tables"} or value["format"] != 1
                    or value["schema"] != CURRENT_SCHEMA_VERSION or set(value["tables"]) != set(_TABLES)):
                raise ValueError("cloud_backup_invalid")
            tables = value["tables"]
            for table, rows in tables.items():
                if not isinstance(rows, list) or len(rows) > 500000:
                    raise ValueError("cloud_backup_invalid")
                for row in rows:
                    if not isinstance(row, dict) or set(row) != set(self._columns[table]):
                        raise ValueError("cloud_backup_invalid")
                    if any(item is not None and type(item) not in (str, int, float) for item in row.values()):
                        raise ValueError("cloud_backup_invalid")
                    _json(row)
                    if table == "settings" and isinstance(row["key"], str) and not _portable_key(row["key"]):
                        continue
                    self._validate_row(table, row)
                if table == "settings":
                    tables[table] = [row for row in rows if _portable_key(row["key"])]
            return tables
        except (KeyError, TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
            raise ValueError("cloud_backup_invalid") from None

    def _validate_row(self, table, row):
        if table == "work_modes":
            if row["category"] != "work" or type(row["archived"]) is not int or row["archived"] not in (0, 1):
                raise ValueError("cloud_backup_invalid")
            CustomWorkMode(row["id"], row["name"], row["revision"], bool(row["archived"]))
        elif table == "settings":
            if not _portable_key(row["key"]):
                raise ValueError("cloud_backup_invalid")
            if row["key"].startswith("daily_note_sharing:"):
                date.fromisoformat(row["key"].split(":", 1)[1])
                row["value"] = NoteSharing.decode(row["value"]).encode()
            else:
                row["value"] = normalize_setting(row["key"], row["value"])
        elif table == "worklog":
            WorkLogStorage.from_row({**row, "user_id": self.user_id})
        elif table == "reports":
            validate_report_period(row["type"], date.fromisoformat(row["period_start"]), date.fromisoformat(row["period_end"]))
        elif table in {"daily_notes", "quick_logs", "calendar_events"}:
            date.fromisoformat(row["d"] if table == "daily_notes" else row["date"])
        elif table == "background_images" and row["data"] is not None:
            row["data"] = base64.b64decode(row["data"], validate=True)
            if len(row["data"]) > 20 * 1024 * 1024:
                raise ValueError("cloud_backup_too_large")

    def _insert(self, connection, tables):
        identifiers = {table: {} for table in _TABLES}
        for table in ("projects", "work_items", "entry_types", "work_modes"):
            for row in tables[table]:
                identifiers[table][row["id"]] = ("custom:" if table in {"entry_types", "work_modes"} else "") + uuid4().hex
        for table in _TABLES:
            for original in tables[table]:
                row = dict(original)
                old_id = row.get("id")
                if table in {"projects", "work_items", "entry_types", "work_modes"}:
                    row["id"] = identifiers[table][old_id]
                if table in _AUTONUMBER:
                    row.pop("id")
                for field, referenced in (("project_id", "projects"), ("work_item_id", "work_items"), ("report_id", "reports")):
                    if row.get(field) is not None:
                        if row[field] not in identifiers[referenced]:
                            raise ValueError("cloud_backup_invalid")
                        row[field] = identifiers[referenced][row[field]]
                if table == "worklog":
                    row["entry_type"] = identifiers["entry_types"].get(row["entry_type"], row["entry_type"])
                    row["work_mode"] = identifiers["work_modes"].get(row["work_mode"], row["work_mode"])
                if table == "settings" and row["key"] == "last_used_work_mode":
                    row["value"] = identifiers["work_modes"].get(row["value"], row["value"])
                if table in {"reports", "report_revisions"}:
                    row["provenance"] = _remap_provenance(row["provenance"], identifiers)
                if table != "report_revisions":
                    row["user_id"] = self.user_id
                columns = ",".join('"' + name + '"' for name in row)
                cursor = connection.execute(f'INSERT INTO "{table}" ({columns}) VALUES ({",".join("?" for _ in row)})', tuple(row.values()))
                if table in _AUTONUMBER:
                    identifiers[table][old_id] = cursor.lastrowid
        violations = connection.execute("PRAGMA foreign_key_check").fetchone()
        if violations:
            raise ValueError("cloud_backup_invalid")
        mismatch = connection.execute("SELECT 1 FROM worklog w JOIN work_items i ON i.id=w.work_item_id "
            "WHERE w.user_id=? AND (i.user_id<>w.user_id OR w.project_id IS NULL OR w.project_id<>i.project_id) LIMIT 1",
            (self.user_id,)).fetchone()
        if mismatch:
            raise ValueError("cloud_backup_invalid")


def _remap_provenance(text, identifiers):
    from worklogger.infrastructure.repositories.report_provenance_sqlite import decode_provenance, encode_provenance
    from dataclasses import replace
    value = decode_provenance(text)
    tables = {"record": "worklog", "calendar": "calendar_events", "quick_log": "quick_logs"}
    sources = []
    for source in value.sources:
        mapping = identifiers.get(tables.get(source.kind), {})
        key = int(source.identifier) if source.identifier.isdigit() else None
        sources.append(replace(source, identifier=str(mapping[key])) if key in mapping else source)
    return encode_provenance(replace(value, sources=tuple(sources)))
