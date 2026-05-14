"""SQLite database backup and restore adapter."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
import os
import shutil
import sqlite3

from worklogger.domain.shared.errors import InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.database.connection import SQLiteConnectionFactory
from worklogger.infrastructure.database.paths import secure_database_files
from worklogger.infrastructure.database.migrations.runner import MigrationRunner


class SQLiteBackupService:
    def __init__(
        self,
        connection_factory: SQLiteConnectionFactory,
        *,
        expected_username: str | None = None,
    ) -> None:
        self._connection_factory = connection_factory
        self._expected_username = expected_username

    def backup_database(self, destination: Path) -> Result[Path]:
        source = Path(self._connection_factory.database_path)
        destination = Path(destination)
        if str(source) == ":memory:":
            return Result.failure(
                ValidationError("backup_memory_database", "backup_memory_database")
            )
        if source.resolve(strict=False) == destination.resolve(strict=False):
            return Result.failure(ValidationError("backup_same_path", "backup_same_path"))
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with self._connection_factory.connection() as source_connection:
                _ensure_integrity(source_connection, "backup_integrity_failed")
                with closing(sqlite3.connect(destination)) as destination_connection:
                    source_connection.backup(destination_connection)
            secure_database_files(destination)
            with closing(sqlite3.connect(destination)) as check_connection:
                _ensure_integrity(check_connection, "backup_integrity_failed")
        except Exception as exc:
            return Result.failure(
                InfrastructureError(
                    "backup_failed",
                    "backup_failed",
                    {"reason": str(exc)},
                )
            )
        return Result.success(destination)

    def validate_restore_database(self, source: Path) -> Result[None]:
        try:
            self._validate_restore_source(Path(source))
        except FileNotFoundError as exc:
            return Result.failure(
                InfrastructureError(
                    "restore_source_missing",
                    "restore_source_missing",
                    {"path": str(exc)},
                )
            )
        except ValueError as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        except Exception as exc:
            return Result.failure(
                InfrastructureError(
                    "restore_validation_failed",
                    "restore_validation_failed",
                    {"reason": str(exc)},
                )
            )
        return Result.success(None)

    def restore_database(self, source: Path) -> Result[None]:
        source = Path(source)
        validation = self.validate_restore_database(source)
        if not validation.ok:
            return validation

        target = Path(self._connection_factory.database_path)
        if str(target) == ":memory:":
            return Result.failure(
                ValidationError("restore_memory_database", "restore_memory_database")
            )
        if target.resolve(strict=False) == source.resolve(strict=False):
            return Result.success(None)

        temp = target.with_name(f"{target.name}.tmp_restore")
        previous = target.with_name(f"{target.name}.pre_restore")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            _remove_if_exists(temp)
            _remove_if_exists(previous)
            shutil.copy2(source, temp)
            _validate_sqlite_file(temp, expected_username=self._expected_username)
            _remove_sidecars(target)
            if target.exists():
                os.replace(target, previous)
            os.replace(temp, target)
            secure_database_files(target)
            try:
                MigrationRunner(self._connection_factory).run_pending()
            except Exception:
                if previous.exists():
                    os.replace(previous, target)
                raise
            _remove_if_exists(previous)
        except Exception as exc:
            _remove_if_exists(temp)
            if not target.exists() and previous.exists():
                os.replace(previous, target)
            return Result.failure(
                InfrastructureError(
                    "restore_failed",
                    "restore_failed",
                    {"reason": str(exc)},
                )
            )
        return Result.success(None)

    def _validate_restore_source(self, source: Path) -> None:
        _validate_sqlite_file(source, expected_username=self._expected_username)


def _validate_sqlite_file(path: Path, *, expected_username: str | None = None) -> None:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    with closing(sqlite3.connect(path)) as connection:
        _ensure_integrity(connection, "restore_integrity_failed")
        users_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
        ).fetchone()
        if users_exists is None:
            raise ValueError("restore_missing_users")
        if expected_username:
            row = connection.execute(
                "SELECT id FROM users WHERE username=?",
                (expected_username,),
            ).fetchone()
            if row is None:
                raise ValueError("restore_user_mismatch")


def _ensure_integrity(connection: sqlite3.Connection, error_code: str) -> None:
    row = connection.execute("PRAGMA integrity_check").fetchone()
    if not row or row[0] != "ok":
        raise ValueError(error_code)


def _remove_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _remove_sidecars(path: Path) -> None:
    for sidecar in (Path(str(path) + "-wal"), Path(str(path) + "-shm")):
        _remove_if_exists(sidecar)
