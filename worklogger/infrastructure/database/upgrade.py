"""Validated database copies and explicit upgrades without modifying their source."""

from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
import json
import os
import sqlite3

from worklogger.infrastructure.backup.sqlite_backup import create_database_snapshot
from worklogger.infrastructure.database.inspection import validate_database_file
from worklogger.infrastructure.database.connection import SQLiteConnectionFactory
from worklogger.infrastructure.database.migrations.runner import MigrationRunner
from worklogger.infrastructure.files import atomic_destination


@dataclass(frozen=True)
class UpgradeReport:
    applied_versions: tuple[int, ...]
    accounts: int
    time_records: int
    reports: int
    notes: int


def copy_database(source: Path, destination: Path) -> None:
    source, destination = source.resolve(), destination.resolve()
    if source == destination:
        raise ValueError("database_source_equals_destination")
    if destination.exists():
        raise ValueError("database_destination_exists")
    if Path(str(source) + ".pre_restore").exists():
        raise ValueError("restore_pending")
    validate_database_file(source)
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as connection:
        snapshot = create_database_snapshot(connection, destination)
    try:
        with atomic_destination(destination, overwrite=False) as temporary:
            os.replace(snapshot, temporary)
    finally:
        snapshot.unlink(missing_ok=True)


def upgrade_database(source: Path, destination: Path, *, template_file: Path | None = None,
                     template_user: str | None = None, template_language: str = "en_US") -> UpgradeReport:
    source, destination = source.resolve(), destination.resolve()
    if source == destination:
        raise ValueError("database_source_equals_destination")
    if destination.exists():
        raise ValueError("database_destination_exists")
    with atomic_destination(destination, overwrite=False) as temporary:
        temporary.unlink()
        copy_database(source, temporary)
        factory = SQLiteConnectionFactory(temporary)
        try:
            versions = MigrationRunner(factory).run_pending()
            if template_file is not None:
                _import_template(factory, template_file, template_user, template_language)
            with factory.connection() as connection:
                if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise ValueError("database_foreign_key_invalid")
                counts = tuple(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                               for table in ("users", "worklog", "reports", "daily_notes"))
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                connection.execute("PRAGMA journal_mode=DELETE")
                if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("database_integrity_invalid")
            return UpgradeReport(versions, *counts)
        finally:
            for snapshot in temporary.parent.glob(temporary.name + ".bak_upgrade_*"):
                snapshot.unlink(missing_ok=True)
            for suffix in ("-wal", "-shm"):
                Path(str(temporary)+suffix).unlink(missing_ok=True)


def _import_template(factory, path, username, language):
    from worklogger.domain.auth.policies import username_key
    from worklogger.domain.reporting.templates import normalize_template_language, normalize_template_type
    if not username or path.stat().st_size > 1024 * 1024:
        raise ValueError("template_import_invalid")
    data = json.loads(path.read_text(encoding="utf-8"))
    content = data.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("template_import_invalid")
    kind, language = normalize_template_type(data.get("type", "")), normalize_template_language(language)
    with factory.transaction() as connection:
        user = connection.execute("SELECT id FROM users WHERE username_key=?", (username_key(username),)).fetchone()
        if user is None:
            raise ValueError("template_import_user_missing")
        connection.execute("INSERT INTO report_templates(user_id,language,type,content,updated_at) VALUES(?,?,?,?,datetime('now'))",
                           (user[0], language, kind, content))
