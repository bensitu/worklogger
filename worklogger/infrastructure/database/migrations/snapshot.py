"""Private, complete database snapshots before compatible schema changes."""

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import logging
import re
import sqlite3
from uuid import uuid4

from worklogger.infrastructure.files import atomic_destination

UPGRADE_SNAPSHOT_RETENTION = 3
LOGGER = logging.getLogger(__name__)


def prune_upgrade_snapshots(database_path: str, *, keep: int = UPGRADE_SNAPSHOT_RETENTION,
                            preserve: Path | None = None) -> None:
    if database_path == ":memory:" or keep < 1:
        return
    path = Path(database_path)
    pattern = re.compile(re.escape(path.name) + r"\.bak_upgrade_\d{8}T\d{6}Z_[0-9a-f]{32}$")
    try:
        snapshots = [candidate for candidate in path.parent.iterdir()
                     if not candidate.is_symlink() and candidate.is_file() and pattern.fullmatch(candidate.name)]
        snapshots.sort(key=lambda candidate: (candidate == preserve, candidate.stat().st_mtime_ns, candidate.name), reverse=True)
        for candidate in snapshots[keep:]:
            candidate.unlink()
    except OSError:
        LOGGER.warning("upgrade_snapshot_cleanup_failed")


def save_snapshot(connection: sqlite3.Connection, database_path: str, category: str) -> Path | None:
    if database_path == ":memory:":
        return
    path = Path(database_path)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.name}.bak_{category}_{stamp}_{uuid4().hex}")
    with atomic_destination(backup) as temporary:
        with closing(sqlite3.connect(temporary)) as destination:
            connection.backup(destination)
            destination.execute("PRAGMA journal_mode=DELETE")
            if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("backup_integrity_failed")
    return backup
