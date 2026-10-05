"""SQLite snapshots with validated, serialized database replacement."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
import os
import sqlite3
import tempfile
from uuid import uuid4

from worklogger.domain.shared.errors import InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.database.connection import SQLiteConnectionFactory
from worklogger.infrastructure.database.paths import secure_database_files
from worklogger.infrastructure.database.migrations.runner import MigrationRunner, MIGRATION_MODULES
from worklogger.infrastructure.database.migrations.migration_003_activity_events import _PREVIOUS_TABLE

_ALLOWED_TABLES = {
    "users", "login_attempts", "worklog", "quick_logs", "settings", "reports",
    "report_templates", "calendar_events", "external_identities", "activity_events",
    "schema_migrations", "daily_notes", _PREVIOUS_TABLE,
}


class SQLiteBackupService:
    def __init__(self, connection_factory: SQLiteConnectionFactory, *,
                 expected_username: str | None = None,
                 requesting_user_id: int | None = None) -> None:
        self._connection_factory = connection_factory
        self._expected_username = expected_username
        self._requesting_user_id = requesting_user_id

    def _authorize(self) -> None:
        if self._requesting_user_id is None:
            return
        with self._connection_factory.connection() as connection:
            user = connection.execute("SELECT username, is_admin FROM users WHERE id=?",
                                      (self._requesting_user_id,)).fetchone()
        if not user or not user["is_admin"] or user["username"] != self._expected_username:
            raise ValueError("admin_required")

    def backup_database(self, destination: Path) -> Result[Path]:
        source = Path(self._connection_factory.database_path)
        destination = Path(destination)
        if str(source) == ":memory:":
            return Result.failure(ValidationError("backup_memory_database", "backup_memory_database"))
        if source.resolve() == destination.resolve():
            return Result.failure(ValidationError("backup_same_path", "backup_same_path"))
        snapshot = None
        try:
            with self._connection_factory.write_lock:
                self._authorize()
                if any(Path(str(destination) + suffix).exists() for suffix in ("-wal", "-shm")):
                    raise ValueError("backup_destination_busy")
                with self._connection_factory.connection() as connection:
                    _ensure_integrity(connection, "backup_integrity_failed")
                    snapshot = create_database_snapshot(connection, destination)
                os.replace(snapshot, destination)
                secure_database_files(destination)
        except ValueError as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        except Exception as exc:
            return Result.failure(InfrastructureError("backup_failed", "backup_failed", {"reason": str(exc)}))
        finally:
            if snapshot:
                _remove_if_exists(snapshot)
        return Result.success(destination)

    def validate_restore_database(self, source: Path) -> Result[None]:
        try:
            with self._connection_factory.write_lock:
                self._authorize()
                self._validate_restore_source(Path(source))
        except FileNotFoundError:
            return Result.failure(InfrastructureError("restore_source_missing", "restore_source_missing"))
        except ValueError as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        except Exception as exc:
            return Result.failure(InfrastructureError("restore_validation_failed", "restore_validation_failed",
                                                       {"reason": str(exc)}))
        return Result.success(None)

    def restore_database(self, source: Path) -> Result[None]:
        with self._connection_factory.write_lock:
            return self._restore_database(source)

    def _restore_database(self, source: Path) -> Result[None]:
        source = Path(source)
        target = Path(self._connection_factory.database_path)
        if str(target) == ":memory:":
            return Result.failure(ValidationError("restore_memory_database", "restore_memory_database"))
        snapshot = None
        previous = target.with_name(target.name + ".pre_restore")
        replacement_started = False
        try:
            with self._connection_factory.write_lock:
                self._authorize()
                self._validate_restore_source(source)
                if previous.exists():
                    raise ValueError("restore_pending")
                if target.resolve() == source.resolve():
                    return Result.success(None)
                with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
                    snapshot = create_database_snapshot(connection, target)
                staged = SQLiteConnectionFactory(snapshot)
                MigrationRunner(staged).run_pending()
                with staged.connection() as connection:
                    _ensure_integrity(connection, "restore_integrity_failed")
                    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    connection.execute("PRAGMA journal_mode=DELETE")
                # Refuse replacement while another process has the live database open.
                with self._connection_factory.connection() as connection:
                    checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                    if checkpoint and checkpoint[0]:
                        raise ValueError("restore_database_busy")
                    connection.execute("PRAGMA journal_mode=DELETE")
                if target.exists():
                    os.replace(target, previous)
                replacement_started = True
                os.replace(snapshot, target)
                secure_database_files(target)
                if previous.exists():
                    retained = target.with_name(target.name + ".bak_restore_" + uuid4().hex)
                    os.replace(previous, retained)
                    secure_database_files(retained)
        except ValueError as exc:
            if replacement_started and previous.exists():
                os.replace(previous, target)
            return Result.failure(ValidationError(str(exc), str(exc)))
        except Exception as exc:
            if replacement_started and previous.exists():
                os.replace(previous, target)
            return Result.failure(InfrastructureError("restore_failed", "restore_failed", {"reason": str(exc)}))
        finally:
            if snapshot:
                _remove_if_exists(snapshot)
        return Result.success(None)

    def _validate_restore_source(self, source: Path) -> None:
        expected_id = None
        if self._expected_username:
            with self._connection_factory.connection() as connection:
                user = connection.execute("SELECT id FROM users WHERE username=?", (self._expected_username,)).fetchone()
                if not user:
                    raise ValueError("restore_user_mismatch")
                expected_id = user[0]
        _validate_sqlite_file(source, expected_username=self._expected_username, expected_user_id=expected_id)


def create_database_snapshot(source: sqlite3.Connection, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=destination.name + ".", suffix=".tmp", dir=destination.parent)
    os.close(descriptor)
    snapshot = Path(name)
    try:
        with closing(sqlite3.connect(snapshot)) as connection:
            source.backup(connection)
            connection.execute("PRAGMA journal_mode=DELETE")
            _ensure_integrity(connection, "backup_integrity_failed")
        secure_database_files(snapshot)
        return snapshot
    except Exception:
        _remove_if_exists(snapshot)
        raise


def _validate_sqlite_file(path: Path, *, expected_username: str | None = None,
                          expected_user_id: int | None = None) -> None:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        _ensure_integrity(connection, "restore_integrity_failed")
        objects = connection.execute("SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
        tables = {name for kind, name in objects if kind == "table"}
        if any(kind in ("trigger", "view") for kind, _name in objects) or tables - _ALLOWED_TABLES:
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


def _remove_if_exists(path: Path) -> None:
    path.unlink(missing_ok=True)
