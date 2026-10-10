"""Bounded reversible history of individual record operations."""

VERSION = 12
DESCRIPTION = "entry_changes"


def up(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS entry_changes(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        operation TEXT NOT NULL, before_json TEXT NOT NULL, after_json TEXT NOT NULL, expected_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        undone INTEGER NOT NULL DEFAULT 0)""")
    connection.execute("CREATE INDEX IF NOT EXISTS entry_changes_account_order ON entry_changes(user_id,id)")
