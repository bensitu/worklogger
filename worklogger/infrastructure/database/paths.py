"""Database path resolution and file hygiene helpers."""

from __future__ import annotations

from pathlib import Path
import os
import stat
import sys
import time
import uuid

from worklogger.config.constants import DB_CORRUPT_BACKUP_RETENTION, DB_FILENAME


def package_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_database_path(
    *,
    frozen: bool | None = None,
    executable: str | None = None,
    package_root_path: Path | None = None,
) -> Path:
    is_frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if is_frozen:
        exe = Path(executable or sys.executable)
        return exe.resolve(strict=False).parent / DB_FILENAME
    return (package_root_path or package_root()) / DB_FILENAME


def secure_database_files(path: str | Path) -> None:
    database_path = Path(path)
    if str(database_path) == ":memory:":
        return
    for candidate in (
        database_path,
        Path(str(database_path) + "-wal"),
        Path(str(database_path) + "-shm"),
    ):
        try:
            if candidate.exists():
                os.chmod(candidate, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass


def quarantine_corrupt_database(
    path: str | Path,
    *,
    keep: int = DB_CORRUPT_BACKUP_RETENTION,
) -> Path | None:
    database_path = Path(path)
    if str(database_path) == ":memory:" or not database_path.exists():
        return None
    backup_path = database_path.with_name(
        f"{database_path.name}.bak_corrupt_{time.time_ns()}_{uuid.uuid4().hex}"
    )
    moved = []
    try:
        for suffix in ("", "-wal", "-shm"):
            source, target = Path(str(database_path) + suffix), Path(str(backup_path) + suffix)
            if source.exists():
                os.replace(source, target)
                moved.append((source, target))
        secure_database_files(backup_path)
    except OSError:
        for source, target in reversed(moved):
            os.replace(target, source)
        raise
    prune_corrupt_backups(database_path, keep=keep)
    return backup_path


def prune_corrupt_backups(
    path: str | Path,
    *,
    keep: int = DB_CORRUPT_BACKUP_RETENTION,
) -> None:
    if keep < 1:
        return
    database_path = Path(path)
    directory = database_path.resolve(strict=False).parent
    prefix = f"{database_path.name}.bak_corrupt_"
    try:
        backups = [
            candidate
            for candidate in directory.iterdir()
            if candidate.is_file() and candidate.name.startswith(prefix) and not candidate.name.endswith(("-wal", "-shm"))
        ]
    except OSError:
        return
    backups.sort(key=lambda candidate: (candidate.stat().st_mtime, candidate.name), reverse=True)
    for old_backup in backups[keep:]:
        try:
            for suffix in ("-wal", "-shm", ""):
                Path(str(old_backup) + suffix).unlink(missing_ok=True)
        except OSError:
            pass
