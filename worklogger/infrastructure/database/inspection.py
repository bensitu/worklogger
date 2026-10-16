"""Read-only validation of stored schema versions and account ownership."""

from contextlib import closing
from pathlib import Path
import sqlite3
from worklogger.infrastructure.database.schema import SUPPORTED_TABLES
from worklogger.infrastructure.database.migrations.runner import database_kind
from worklogger.domain.auth.policies import username_key

def validate_database_file(path: Path, *, expected_username: str | None = None,
                          expected_user_id: int | None = None) -> None:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        _ensure_integrity(connection, "restore_integrity_failed")
        objects = connection.execute("SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
        tables = {name for kind, name in objects if kind == "table"}
        if any(kind in ("trigger", "view") for kind, _name in objects) or tables - SUPPORTED_TABLES:
            raise ValueError("restore_schema_invalid")
        if "users" not in tables:
            raise ValueError("restore_missing_users")
        database_kind(connection)
        if expected_username:
            row = next((row for row in connection.execute("SELECT id,username FROM users")
                        if username_key(row[1]) == username_key(expected_username)), None)
            if row is None or (expected_user_id is not None and row[0] != expected_user_id):
                raise ValueError("restore_user_mismatch")


def _ensure_integrity(connection: sqlite3.Connection, error_code: str) -> None:
    rows = connection.execute("PRAGMA integrity_check").fetchall()
    if len(rows) != 1 or rows[0][0] != "ok":
        raise ValueError(error_code)
