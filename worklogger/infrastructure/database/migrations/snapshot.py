"""Private, complete database snapshots before compatible schema changes."""

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from uuid import uuid4

from worklogger.infrastructure.files import atomic_destination


def save_snapshot(connection: sqlite3.Connection, database_path: str, category: str) -> None:
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
