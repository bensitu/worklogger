"""Preserve custom accounting classifications as immutable record snapshots."""

VERSION = 9
DESCRIPTION = "custom_work_types"


def up(connection):
    connection.execute("ALTER TABLE worklog ADD COLUMN work_type_label TEXT NOT NULL DEFAULT ''")
    connection.execute("ALTER TABLE worklog ADD COLUMN work_type_category TEXT NOT NULL DEFAULT ''")
    connection.execute("""CREATE TABLE work_types(
        id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name TEXT NOT NULL, normalized_name TEXT NOT NULL, category TEXT NOT NULL CHECK(category IN ('work','break','leave')),
        revision INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0)""")
    connection.execute("CREATE UNIQUE INDEX work_types_active_name ON work_types(user_id,normalized_name) WHERE archived=0")
    connection.execute("CREATE INDEX work_types_account ON work_types(user_id,archived)")
    connection.execute("CREATE INDEX reports_account_period ON reports(user_id,type,period_start,created_at,id)")
