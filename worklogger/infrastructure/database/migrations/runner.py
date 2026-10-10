"""Idempotent SQLite migration runner."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from types import ModuleType
from typing import Any

from worklogger.infrastructure.database.connection import SQLiteConnectionFactory
from worklogger.infrastructure.database.migrations.snapshot import save_snapshot

MIGRATION_MODULES = (
    "worklogger.infrastructure.database.migrations.migration_001_initial_schema",
    "worklogger.infrastructure.database.migrations.migration_002_auth_columns",
    "worklogger.infrastructure.database.migrations.migration_003_activity_events",
    "worklogger.infrastructure.database.migrations.migration_004_usernames",
    "worklogger.infrastructure.database.migrations.migration_005_daily_notes",
    "worklogger.infrastructure.database.migrations.migration_006_worklog_timestamps",
    "worklogger.infrastructure.database.migrations.migration_007_worklog_entries",
    "worklogger.infrastructure.database.migrations.migration_008_account_preferences",
    "worklogger.infrastructure.database.migrations.migration_009_custom_work_types",
    "worklogger.infrastructure.database.migrations.migration_010_user_display_names",
    "worklogger.infrastructure.database.migrations.migration_011_work_context",
    "worklogger.infrastructure.database.migrations.migration_012_entry_changes",
)


@dataclass(frozen=True)
class Migration:
    version: int
    description: str
    module: ModuleType


class MigrationRunner:
    def __init__(
        self,
        connection_factory: SQLiteConnectionFactory,
        migration_modules: tuple[str, ...] = MIGRATION_MODULES,
    ) -> None:
        self._connection_factory = connection_factory
        self._migration_modules = migration_modules

    def run_pending(self) -> tuple[int, ...]:
        migrations = self._discover_migrations()
        applied_now: list[int] = []
        with self._connection_factory.write_lock:
            with self._connection_factory.connection() as connection:
                exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'").fetchone()
                applied = self._applied_versions(connection) if exists else set()
                if applied - {migration.version for migration in migrations}:
                    raise ValueError("database_version_unsupported")
                pending = tuple(migration for migration in migrations if migration.version not in applied)
                if not pending:
                    return ()
                objects = connection.execute("SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
                if any(row[0] in {"trigger", "view"} for row in objects):
                    raise ValueError("database_schema_unsupported")
                populated = any(connection.execute('SELECT 1 FROM "' + row[1].replace('"', '""') + '" LIMIT 1').fetchone()
                                for row in objects if row[0] == "table" and row[1] != "schema_migrations")
                if populated:
                    save_snapshot(connection, self._connection_factory.database_path, "upgrade")
            with self._connection_factory.transaction(write=True) as connection:
                self._ensure_schema_migrations(connection)
                applied = self._applied_versions(connection)
                for migration in migrations:
                    if migration.version in applied:
                        continue
                    migration.module.up(connection)
                    connection.execute(
                        "INSERT INTO schema_migrations(version, description, applied_at) "
                        "VALUES(?, ?, datetime('now'))",
                        (migration.version, migration.description),
                    )
                    applied_now.append(migration.version)
                if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise ValueError("database_foreign_key_invalid")
        return tuple(applied_now)

    def _discover_migrations(self) -> tuple[Migration, ...]:
        migrations: list[Migration] = []
        for module_name in self._migration_modules:
            module = import_module(module_name)
            version = int(getattr(module, "VERSION"))
            description = str(getattr(module, "DESCRIPTION", module_name.rsplit(".", 1)[-1]))
            migrations.append(Migration(version, description, module))
        if len({migration.version for migration in migrations}) != len(migrations):
            raise ValueError("database_migration_duplicate")
        return tuple(sorted(migrations, key=lambda migration: migration.version))

    @staticmethod
    def _ensure_schema_migrations(connection: Any) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations(
                version INTEGER PRIMARY KEY,
                description TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )

    @staticmethod
    def _applied_versions(connection: Any) -> set[int]:
        rows = connection.execute("SELECT version FROM schema_migrations").fetchall()
        return {int(row[0]) for row in rows}
