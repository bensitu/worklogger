"""Preserve custom accounting classifications as immutable record snapshots."""

VERSION = 9
DESCRIPTION = "custom_work_types"


def up(connection):
    columns = {row[1] for row in connection.execute("PRAGMA table_info(worklog)")}
    for column in ("work_type_label", "work_type_category"):
        if column not in columns:
            connection.execute(f"ALTER TABLE worklog ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
    existing = {row[1] for row in connection.execute("PRAGMA table_info(work_types)")}
    if existing and not {"id", "user_id", "name", "normalized_name", "category", "revision", "archived"}.issubset(existing):
        raise ValueError("database_schema_unsupported")
    connection.execute("""CREATE TABLE IF NOT EXISTS work_types(
        id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name TEXT NOT NULL, normalized_name TEXT NOT NULL, category TEXT NOT NULL CHECK(category IN ('work','break','leave')),
        revision INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0)""")
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS work_types_active_name ON work_types(user_id,normalized_name) WHERE archived=0")
    connection.execute("CREATE INDEX IF NOT EXISTS work_types_account ON work_types(user_id,archived)")
    connection.execute("CREATE INDEX IF NOT EXISTS reports_account_period ON reports(user_id,type,period_start,created_at,id)")
