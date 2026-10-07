"""Read-only validation of stored schema versions and account ownership."""

from contextlib import closing
from pathlib import Path
import sqlite3
from worklogger.infrastructure.database.schema import SUPPORTED_TABLES
from worklogger.infrastructure.database.migrations.runner import MIGRATION_MODULES

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
        if "schema_migrations" in tables:
            from importlib import import_module
            supported = {import_module(name).VERSION for name in MIGRATION_MODULES}
            if {row[0] for row in connection.execute("SELECT version FROM schema_migrations")} - supported:
                raise ValueError("database_version_unsupported")
        if expected_username:
            row = connection.execute("SELECT id FROM users WHERE username=?", (expected_username,)).fetchone()
            if row is None or (expected_user_id is not None and row[0] != expected_user_id):
                raise ValueError("restore_user_mismatch")


def _ensure_integrity(connection: sqlite3.Connection, error_code: str) -> None:
    rows = connection.execute("PRAGMA integrity_check").fetchall()
    if len(rows) != 1 or rows[0][0] != "ok":
        raise ValueError(error_code)
