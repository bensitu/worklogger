"""Validated startup replacement with retained originals and interruption detection."""

from contextlib import closing
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from uuid import uuid4

from worklogger.infrastructure.backup.sqlite_backup import _use_delete_journal
from worklogger.infrastructure.database.connection import SQLiteConnectionFactory
from worklogger.infrastructure.database.inspection import validate_database_file
from worklogger.infrastructure.database.migrations.runner import MigrationRunner
from worklogger.infrastructure.database.paths import secure_database_files
from worklogger.infrastructure.database.upgrade import upgrade_database
from worklogger.infrastructure.files import atomic_destination

LOGGER = logging.getLogger(__name__)
_DATABASE_SUFFIXES = ("", "-wal", "-shm", ".pre_restore", ".pre_restore-wal", ".pre_restore-shm")


def startup_recovery_marker(path: Path) -> Path:
    return Path(str(path) + ".startup-recovery.json")


class SQLiteStartupDatabase:
    """The desktop instance lock must remain held throughout replacement."""

    def __init__(self, path: Path):
        self.path = Path(path).absolute()

    def replace(self, backup: Path | None) -> Path:
        if self.path.is_symlink():
            raise ValueError("startup_database_invalid")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(prefix=".database-preparation-", dir=self.path.parent) as directory:
            candidate = Path(directory) / "worklog.db"
            if backup is not None:
                source = Path(backup).resolve()
                if source == self.path.resolve():
                    raise ValueError("startup_backup_invalid")
                try:
                    upgrade_database(source, candidate)
                except sqlite3.DatabaseError:
                    raise ValueError("startup_backup_invalid") from None
            else:
                factory = SQLiteConnectionFactory(candidate)
                MigrationRunner(factory).run_pending()
                with closing(sqlite3.connect(candidate)) as connection:
                    _use_delete_journal(connection)
            validate_database_file(candidate)
            return self._publish(candidate)

    def _publish(self, candidate: Path) -> Path:
        files = tuple(Path(str(self.path) + suffix) for suffix in _DATABASE_SUFFIXES)
        marker = startup_recovery_marker(self.path)
        if marker.is_symlink() or any(path.is_symlink() for path in files):
            raise ValueError("startup_database_invalid")
        root = self.path.parent / "database-recovery"
        if root.is_symlink():
            raise ValueError("startup_database_invalid")
        retained = root / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_") + uuid4().hex)
        retained.mkdir(parents=True, mode=0o700)
        previous_marker = retained / "previous-operation.json"
        if marker.exists():
            shutil.copyfile(marker, previous_marker)
        moved = []
        published = False
        try:
            with atomic_destination(marker) as temporary:
                temporary.write_text(json.dumps({"retained_directory": retained.relative_to(self.path.parent).as_posix()}) + "\n",
                                     encoding="utf-8")
            for original in files:
                if original.exists():
                    archived = retained / original.name
                    os.replace(original, archived)
                    moved.append((original, archived))
            os.replace(candidate, self.path)
            published = True
            secure_database_files(self.path)
            marker.unlink()
        except Exception:
            if not published:
                restored = True
                for original, archived in reversed(moved):
                    try:
                        os.replace(archived, original)
                    except OSError:
                        restored = False
                        LOGGER.error("startup_database_rollback_failed")
                if restored:
                    if previous_marker.exists():
                        os.replace(previous_marker, marker)
                    else:
                        marker.unlink(missing_ok=True)
            raise
        return retained
