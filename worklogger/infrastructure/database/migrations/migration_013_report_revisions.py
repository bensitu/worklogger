"""Retain saved report versions without changing existing content or identity."""

VERSION = 13
DESCRIPTION = "report_revisions"


def up(connection):
    columns = {row[1] for row in connection.execute("PRAGMA table_info(reports)")}
    for name, declaration in (("revision", "INTEGER NOT NULL DEFAULT 0"),
                               ("updated_at", "TEXT"), ("provenance", "TEXT NOT NULL DEFAULT '{}'")):
        if name not in columns:
            connection.execute(f"ALTER TABLE reports ADD COLUMN {name} {declaration}")
    connection.execute("""CREATE TABLE IF NOT EXISTS report_revisions(
        report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
        revision INTEGER NOT NULL, content TEXT NOT NULL, saved_at TEXT,
        provenance TEXT NOT NULL DEFAULT '{}', PRIMARY KEY(report_id,revision))""")
    connection.execute("""INSERT OR IGNORE INTO report_revisions(report_id,revision,content,saved_at,provenance)
        SELECT id,revision,content,COALESCE(updated_at,created_at),provenance FROM reports""")
