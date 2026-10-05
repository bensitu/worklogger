"""SQLite connection factory and transaction helpers."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
import os
from threading import RLock
from typing import Iterator

from worklogger.config.constants import DB_CORRUPT_BACKUP_RETENTION
from worklogger.infrastructure.database.paths import (
    quarantine_corrupt_database,
    secure_database_files,
)


class SQLiteConnectionFactory:
    """Creates configured SQLite connections and serializes writes."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        busy_timeout_ms: int = 5000,
        recover_corrupt: bool = False,
        corrupt_backup_retention: int = DB_CORRUPT_BACKUP_RETENTION,
    ) -> None:
        self.database_path = str(database_path)
        self.busy_timeout_ms = max(0, int(busy_timeout_ms))
        self.recover_corrupt = bool(recover_corrupt)
        self.corrupt_backup_retention = int(corrupt_backup_retention)
        self.write_lock = RLock()
        self._integrity_checked = False

    def open(self) -> sqlite3.Connection:
        with self.write_lock:
            try:
                connection = self._open_once(check_integrity=not self._integrity_checked)
            except sqlite3.DatabaseError as exc:
                code = getattr(exc, "sqlite_errorcode", 0) & 0xFF
                corrupt = isinstance(exc, DatabaseIntegrityError) or code in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB)
                if not corrupt or not self.recover_corrupt or self.database_path == ":memory:":
                    raise
                quarantine_corrupt_database(self.database_path, keep=self.corrupt_backup_retention)
                connection = self._open_once(check_integrity=True)
            self._integrity_checked = True
            return connection

    def _open_once(self, *, check_integrity: bool) -> sqlite3.Connection:
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                descriptor = os.open(self.database_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(descriptor)
        connection = sqlite3.connect(
            self.database_path,
            detect_types=sqlite3.PARSE_DECLTYPES,
            isolation_level=None,
            timeout=self.busy_timeout_ms / 1000,
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            if self.database_path != ":memory:":
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA synchronous=NORMAL")
                secure_database_files(self.database_path)
            if check_integrity and self.database_path != ":memory:":
                row = connection.execute("PRAGMA integrity_check").fetchone()
                if not row or row[0] != "ok":
                    raise DatabaseIntegrityError("Database integrity check failed")
            return connection
        except Exception:
            connection.close()
            raise

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        with self.write_lock:
            connection = self.open()
            try:
                yield connection
            finally:
                connection.close()

    @contextmanager
    def transaction(
        self,
        *,
        write: bool = True,
    ) -> Iterator[sqlite3.Connection]:
        with self.connection() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise


class DatabaseIntegrityError(sqlite3.DatabaseError):
    """An explicit integrity failure rather than an operational access failure."""
