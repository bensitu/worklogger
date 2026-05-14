"""Idempotent SQLite migration runner."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from types import ModuleType
from typing import Any

from worklogger.infrastructure.database.connection import SQLiteConnectionFactory

MIGRATION_MODULES = (
    "worklogger.infrastructure.database.migrations.migration_001_initial_schema",
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
        return tuple(applied_now)

    def _discover_migrations(self) -> tuple[Migration, ...]:
        migrations: list[Migration] = []
        for module_name in self._migration_modules:
            module = import_module(module_name)
            version = int(getattr(module, "VERSION"))
            description = str(getattr(module, "DESCRIPTION", module_name.rsplit(".", 1)[-1]))
            migrations.append(Migration(version, description, module))
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
