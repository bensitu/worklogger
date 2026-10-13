"""Explicit recovery that retains both sides of an interrupted restore."""

import logging
import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from worklogger.domain.shared.recovery import RestoreRecoveryChoices
from worklogger.infrastructure.database.inspection import validate_database_file
from worklogger.infrastructure.database.paths import secure_database_files

LOGGER = logging.getLogger(__name__)
RESTORE_BACKUP_RETENTION = 3


def _valid_database(path):
    try:
        validate_database_file(path)
        return True
    except (OSError, ValueError, sqlite3.Error):
        return False


def inspect_pending_restore(path: Path) -> RestoreRecoveryChoices:
    path = Path(path)
    previous = Path(str(path) + ".pre_restore")
    if not previous.is_file():
        raise ValueError("restore_pending")
    return RestoreRecoveryChoices(_valid_database(previous), _valid_database(path))


def _retain_database_files(source, target, category):
    retained = target.with_name(target.name + category + uuid4().hex)
    moved = []
    try:
        for suffix in ("", "-wal", "-shm"):
            original, archived = Path(str(source) + suffix), Path(str(retained) + suffix)
            if original.exists():
                os.replace(original, archived)
                moved.append((original, archived))
        secure_database_files(retained)
    except OSError:
        for original, archived in reversed(moved):
            try:
                os.replace(archived, original)
            except OSError:
                LOGGER.error("restore_recovery_archive_failed")
        raise
    try:
        os.utime(retained, None)
    except OSError:
        LOGGER.warning("restore_backup_timestamp_failed")
    return retained


def recover_pending_restore(path: Path, choice: str) -> None:
    from worklogger.infrastructure.backup.sqlite_backup import create_database_snapshot

    path = Path(path)
    previous = Path(str(path) + ".pre_restore")
    options = inspect_pending_restore(path)
    if choice not in {"rollback", "keep"} or not getattr(options, "rollback_available" if choice == "rollback" else "restored_available"):
        raise ValueError("restore_recovery_unavailable")
    snapshot = None
    try:
        if choice == "rollback":
            with closing(sqlite3.connect(previous.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
                snapshot = create_database_snapshot(connection, path)
            if path.exists():
                _retain_database_files(path, path, ".bak_recovery_")
            os.replace(snapshot, path)
            secure_database_files(path)
        retained = _retain_database_files(previous, path, ".bak_restore_")
    finally:
        if snapshot is not None:
            snapshot.unlink(missing_ok=True)
    prune_restore_backups(path, preserve=retained)


def prune_restore_backups(path: Path, *, keep: int = RESTORE_BACKUP_RETENTION, preserve: Path | None = None) -> None:
    if keep < 1:
        return
    path = Path(path)
    pattern = re.compile(re.escape(path.name) + r"\.bak_(?:restore|recovery)_[0-9a-f]{32}$")
    try:
        backups = [candidate for candidate in path.parent.iterdir()
                   if candidate.is_file() and not candidate.is_symlink() and pattern.fullmatch(candidate.name)]
        backups.sort(key=lambda candidate: (candidate == preserve, candidate.stat().st_mtime_ns, candidate.name), reverse=True)
        for candidate in backups[keep:]:
            for suffix in ("-wal", "-shm", ""):
                Path(str(candidate) + suffix).unlink(missing_ok=True)
    except OSError:
        LOGGER.warning("restore_backup_cleanup_failed")
