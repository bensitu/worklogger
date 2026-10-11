"""Transactional current-schema initialization and released database import."""

import sqlite3
from contextlib import closing
from importlib import import_module
from pathlib import Path

from worklogger.infrastructure.database.current_schema import (
    CURRENT_SCHEMA_VERSION,
    PREVIOUS_CURRENT_VERSION,
    validate_current_schema,
)
from worklogger.infrastructure.database.migrations.snapshot import save_snapshot
from worklogger.infrastructure.database.released_import import (
    import_released_schema,
    validate_released_schema,
)

MIGRATION_MODULES = ("worklogger.infrastructure.database.migrations.migration_016_background_preferences",)
MIGRATION_VERSIONS = (CURRENT_SCHEMA_VERSION,)
SUPPORTED_VERSIONS = frozenset(range(1, CURRENT_SCHEMA_VERSION + 1))


def database_kind(connection, *, check_data=True):
    objects = connection.execute("SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
    if any(row[0] in {"view", "trigger"} for row in objects):
        raise ValueError("database_schema_unsupported")
    tables = {row[1] for row in objects if row[0] == "table"}
    if not tables:
        return "empty"
    if "schema_migrations" in tables:
        versions = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
        if versions - SUPPORTED_VERSIONS or not versions & set(range(PREVIOUS_CURRENT_VERSION, CURRENT_SCHEMA_VERSION + 1)):
            raise ValueError("database_version_unsupported")
        validate_current_schema(connection, check_data=check_data)
        return "current" if CURRENT_SCHEMA_VERSION in versions else "current_previous_ledger"
    try:
        validate_current_schema(connection, ledger_required=False, check_data=check_data)
    except ValueError:
        validate_released_schema(connection, tables)
        return "released"
    return "current_unversioned"


class MigrationRunner:
    def __init__(self, connection_factory):
        self._connection_factory = connection_factory

    def run_pending(self):
        with self._connection_factory.write_lock:
            path = Path(self._connection_factory.database_path)
            if path.is_file() and path.stat().st_size:
                try:
                    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as source:
                        kind = database_kind(source, check_data=False)
                    if kind == "current":
                        with self._connection_factory.connection() as connection:
                            if database_kind(connection, check_data=False) == "current":
                                return ()
                except sqlite3.DatabaseError:
                    if not self._connection_factory.recover_corrupt:
                        raise
            with self._connection_factory.transaction() as connection:
                kind = database_kind(connection, check_data=False)
                if kind == "current":
                    return ()
                if self._connection_factory.database_path != ":memory:" and kind != "empty" and any(connection.execute(f'SELECT 1 FROM "{row[0]}" LIMIT 1').fetchone()
                        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name<>'schema_migrations'")):
                    # The writer lock prevents changes while a separate reader snapshots committed data.
                    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as source:
                        save_snapshot(source, self._connection_factory.database_path, "upgrade")
                if kind == "released":
                    import_released_schema(connection)
                for module_name in MIGRATION_MODULES:
                    migration = import_module(module_name)
                    migration.up(connection)
                    connection.execute("INSERT INTO schema_migrations(version,description,applied_at) VALUES(?,?,datetime('now'))",
                                       (migration.VERSION, migration.DESCRIPTION))
                validate_current_schema(connection)
        return MIGRATION_VERSIONS
