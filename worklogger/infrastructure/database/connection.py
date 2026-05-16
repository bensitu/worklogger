"""SQLite connection factory and transaction helpers."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
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
        recover_corrupt: bool = True,
        corrupt_backup_retention: int = DB_CORRUPT_BACKUP_RETENTION,
    ) -> None:
        self.database_path = str(database_path)
        self.busy_timeout_ms = max(0, int(busy_timeout_ms))
        self.recover_corrupt = bool(recover_corrupt)
        self.corrupt_backup_retention = int(corrupt_backup_retention)
        self.write_lock = RLock()

    def open(self) -> sqlite3.Connection:
        try:
            return self._open_once(check_integrity=True)
        except sqlite3.DatabaseError:
            if not self.recover_corrupt or self.database_path == ":memory:":
                raise
            quarantine_corrupt_database(
                self.database_path,
                keep=self.corrupt_backup_retention,
            )
            return self._open_once(check_integrity=False)

    def _open_once(self, *, check_integrity: bool) -> sqlite3.Connection:
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
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
                if row and row[0] != "ok":
                    raise sqlite3.DatabaseError(f"Integrity check failed: {row[0]}")
            if self.database_path != ":memory:":
                secure_database_files(self.database_path)
            return connection
        except sqlite3.DatabaseError:
            connection.close()
            raise

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
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
        lock = self.write_lock if write else _NullLock()
        with lock:
            with self.connection() as connection:
                try:
                    connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                    yield connection
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise


class _NullLock:
    def __enter__(self) -> "_NullLock":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None
