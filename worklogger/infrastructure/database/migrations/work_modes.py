"""Preserve records and reversible snapshots while extending work arrangements."""

import json

from worklogger.infrastructure.database.current_schema import TABLE_STATEMENTS, create_current_schema


def extend_work_modes(connection):
    sequence = connection.execute("SELECT seq FROM sqlite_sequence WHERE name='worklog'").fetchone()
    columns = [row[1] for row in connection.execute("PRAGMA table_info(worklog)")]
    quoted = ",".join('"' + column + '"' for column in columns)
    connection.execute("ALTER TABLE worklog RENAME TO previous_worklog")
    connection.execute(TABLE_STATEMENTS["worklog"])
    connection.execute(f"INSERT INTO worklog({quoted}) SELECT {quoted} FROM previous_worklog")
    connection.execute("DROP TABLE previous_worklog")
    if sequence is not None:
        connection.execute("UPDATE sqlite_sequence SET seq=max(seq,?) WHERE name='worklog'", (sequence[0],))
    create_current_schema(connection)
    rows = connection.execute("SELECT id,before_json,after_json,expected_json FROM entry_changes").fetchall()
    for row in rows:
        documents = []
        for raw in row[1:]:
            if not isinstance(raw, str) or len(raw) > 1024 * 1024:
                raise ValueError("record_change_invalid")
            snapshots = json.loads(raw)
            if not isinstance(snapshots, list) or any(not isinstance(item, dict) for item in snapshots):
                raise ValueError("record_change_invalid")
            for snapshot in snapshots:
                snapshot.setdefault("work_mode_label", "")
            documents.append(json.dumps(snapshots, ensure_ascii=False, allow_nan=False))
        connection.execute("UPDATE entry_changes SET before_json=?,after_json=?,expected_json=? WHERE id=?", (*documents, row[0]))
    connection.execute("DELETE FROM schema_migrations WHERE version=17")
