"""SQLite UnitOfWork boundary."""

from __future__ import annotations

from contextlib import AbstractContextManager
import sqlite3

from worklogger.infrastructure.database.connection import SQLiteConnectionFactory


class SQLiteUnitOfWork:
    """Small transaction boundary shared by infrastructure adapters."""

    def __init__(self, connection_factory: SQLiteConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def transaction(
        self,
        *,
        write: bool = True,
    ) -> AbstractContextManager[sqlite3.Connection]:
        return self._connection_factory.transaction(write=write)
