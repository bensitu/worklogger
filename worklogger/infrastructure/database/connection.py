"""SQLite connection factory and transaction helpers."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from threading import Condition, RLock, get_ident

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
        if self.database_path == ":memory:":
            raise ValueError("A connection factory requires a persistent database path")
        self.busy_timeout_ms = max(0, int(busy_timeout_ms))
        self.recover_corrupt = bool(recover_corrupt)
        self.corrupt_backup_retention = int(corrupt_backup_retention)
        self.write_lock = RLock()
        self._initialization_lock = RLock()
        self._activity = Condition(RLock())
        self._readers: dict[int, int] = {}
        self._writers: dict[int, int] = {}
        self._maintenance_owner: int | None = None
        self._maintenance_depth = 0
        self._integrity_checked = False
        self._allow_create = True

    def open(self) -> sqlite3.Connection:
        with self._initialization_lock:
            try:
                connection = self._open_once(check_integrity=not self._integrity_checked)
            except sqlite3.DatabaseError as exc:
                code = getattr(exc, "sqlite_errorcode", 0) & 0xFF
                corrupt = isinstance(exc, DatabaseIntegrityError) or code in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB)
                if self._integrity_checked or not corrupt or not self.recover_corrupt or self.database_path == ":memory:":
                    raise
                quarantine_corrupt_database(self.database_path, keep=self.corrupt_backup_retention)
                connection = self._open_once(check_integrity=True)
            self._integrity_checked = True
            self._allow_create = False
            return connection

    def _open_once(self, *, check_integrity: bool) -> sqlite3.Connection:
        if self.database_path != ":memory:":
            if not self._allow_create and not Path(self.database_path).is_file():
                raise FileNotFoundError(self.database_path)
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
                if check_integrity:
                    connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA synchronous=NORMAL")
                if check_integrity:
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
    def _write_access(self):
        if not self.write_lock.acquire(timeout=self.busy_timeout_ms / 1000):
            raise sqlite3.OperationalError("database is busy")
        try:
            yield
        finally:
            self.write_lock.release()

    @contextmanager
    def connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        identity = get_ident()
        with self._activity:
            if write and self._readers.get(identity) and not self._writers.get(identity):
                raise RuntimeError("database_write_during_read")
        with self._write_access() if write else nullcontext():
            with self._activity:
                ready = lambda: (self._maintenance_owner in (None, identity)
                                 or self._readers.get(identity) or self._writers.get(identity))
                if not self._activity.wait_for(ready, timeout=self.busy_timeout_ms / 1000):
                    raise sqlite3.OperationalError("database is busy")
                active = self._writers if write else self._readers
                active[identity] = active.get(identity, 0) + 1
            connection = None
            try:
                connection = self.open()
                if not write:
                    connection.execute("PRAGMA query_only=ON")
                yield connection
            finally:
                if connection is not None:
                    connection.close()
                with self._activity:
                    active[identity] -= 1
                    if not active[identity]:
                        del active[identity]
                    self._activity.notify_all()

    @contextmanager
    def maintenance(self):
        identity = get_ident()
        with self._activity:
            if self._readers.get(identity) or self._writers.get(identity):
                raise RuntimeError("database_maintenance_during_connection")
        with self._write_access():
            with self._activity:
                if self._maintenance_owner == identity:
                    self._maintenance_depth += 1
                else:
                    self._maintenance_owner = identity
                    self._maintenance_depth = 1
                    self._activity.notify_all()
                    while self._readers or self._writers:
                        self._activity.wait()
            try:
                yield
            finally:
                with self._activity:
                    self._maintenance_depth -= 1
                    if not self._maintenance_depth:
                        self._maintenance_owner = None
                        self._activity.notify_all()

    def invalidate(self):
        if self._maintenance_owner != get_ident():
            raise RuntimeError("database_invalidation_requires_maintenance")
        with self._initialization_lock:
            self._integrity_checked = False

    @contextmanager
    def transaction(
        self,
        *,
        write: bool = True,
    ) -> Iterator[sqlite3.Connection]:
        with self.connection(write=write) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise


class DatabaseIntegrityError(sqlite3.DatabaseError):
    """An explicit integrity failure rather than an operational access failure."""
