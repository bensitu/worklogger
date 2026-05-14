"""Database path resolution and file hygiene helpers."""

from __future__ import annotations

from pathlib import Path
import os
import shutil
import stat
import sys
import time

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
        f"{database_path.name}.bak_{int(time.time())}"
    )
    shutil.move(str(database_path), str(backup_path))
    for sidecar in (Path(str(database_path) + "-wal"), Path(str(database_path) + "-shm")):
        try:
            if sidecar.exists():
                sidecar.unlink()
        except OSError:
            pass
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
    prefix = f"{database_path.name}.bak_"
    try:
        backups = [
            candidate
            for candidate in directory.iterdir()
            if candidate.is_file() and candidate.name.startswith(prefix)
        ]
    except OSError:
        return
    backups.sort(key=lambda candidate: (candidate.stat().st_mtime, candidate.name), reverse=True)
    for old_backup in backups[keep:]:
        try:
            old_backup.unlink()
        except OSError:
            pass
