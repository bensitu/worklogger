"""Explicit offline repair of the verified schema-13 development test database."""

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from itertools import zip_longest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from worklogger.infrastructure.database.current_schema import (
    CURRENT_SCHEMA_VERSION,
    TABLE_STATEMENTS,
    create_current_schema,
    validate_current_schema,
)
from worklogger.infrastructure.database.migrations.runner import database_kind
from worklogger.infrastructure.database.migrations.snapshot import save_snapshot


def _validate_candidate(connection):
    if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise ValueError("database_integrity_failed")
    objects = connection.execute(
        "SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
    ).fetchall()
    tables = {name for kind, name in objects if kind == "table"}
    if "schema_migrations" not in tables:
        raise ValueError("test_database_schema_unsupported")
    versions = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
    if CURRENT_SCHEMA_VERSION in versions and database_kind(connection) == "current":
        return False
    if versions != set(range(1, 14)) or "background_images" in tables:
        raise ValueError("test_database_schema_unsupported")
    if any(kind in {"view", "trigger"} for kind, _name in objects):
        raise ValueError("test_database_schema_unsupported")
    # Probe the missing table inside a savepoint, without retaining any changes.
    connection.execute("SAVEPOINT test_schema_probe")
    try:
        connection.execute(TABLE_STATEMENTS["background_images"])
        validate_current_schema(connection)
    finally:
        connection.execute("ROLLBACK TO test_schema_probe")
        connection.execute("RELEASE test_schema_probe")
    return True


def migrate_test_database(path, *, apply=False):
    path = Path(path).resolve(strict=True)
    if Path(str(path) + ".pre_restore").exists():
        raise ValueError("restore_pending")
    uri = path.as_uri()
    with (closing(sqlite3.connect(uri + "?mode=ro", uri=True)) as source,
          closing(sqlite3.connect(":memory:")) as probe):
        source.backup(probe)
        pending = _validate_candidate(probe)
    if not pending or not apply:
        return {"status": "ready" if pending else "current", "applied": False}

    with closing(sqlite3.connect(uri + "?mode=rw", uri=True, isolation_level=None)) as target:
        target.execute("PRAGMA foreign_keys=ON")
        target.execute("BEGIN IMMEDIATE")
        try:
            if not _validate_candidate(target):
                target.rollback()
                return {"status": "current", "applied": False}
            # The reserved writer lock keeps the separate reader's snapshot stable.
            with closing(sqlite3.connect(uri + "?mode=ro", uri=True)) as source:
                backup = save_snapshot(source, str(path), "test_v13")
            create_current_schema(target)
            target.execute(
                "INSERT INTO schema_migrations VALUES(?, 'explicit_test_v13_upgrade', datetime('now'))",
                (CURRENT_SCHEMA_VERSION,),
            )
            validate_current_schema(target)
            counts = {}
            with closing(sqlite3.connect(backup.resolve().as_uri() + "?mode=ro", uri=True)) as original:
                tables = [row[0] for row in original.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name<>'schema_migrations'"
                )]
                for table in tables:
                    quoted = '"' + table.replace('"', '""') + '"'
                    query = f"SELECT * FROM {quoted} ORDER BY rowid"
                    count = 0
                    for before, after in zip_longest(original.execute(query), target.execute(query)):
                        if before != after:
                            raise ValueError("test_database_preservation_failed")
                        count += 1
                    counts[table] = count
                query = "SELECT * FROM schema_migrations WHERE version<15 ORDER BY version"
                if original.execute(query).fetchall() != target.execute(query).fetchall():
                    raise ValueError("test_database_ledger_preservation_failed")
            if target.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("database_integrity_failed")
            target.commit()
        except Exception:
            target.rollback()
            raise
    return {"status": "current", "applied": True, "version": CURRENT_SCHEMA_VERSION,
            "backup": str(backup), "preserved_rows": counts}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    lock = None
    try:
        if args.apply:
            from worklogger.main import _acquire_instance_lock

            lock = _acquire_instance_lock(args.database.resolve(strict=True))
        result = migrate_test_database(args.database, apply=args.apply)
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
        print(f"Test database repair failed ({type(exc).__name__}); no repair was committed.", file=sys.stderr)
        return 1
    finally:
        if lock is not None:
            lock.unlock()
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
