"""Optional account-owned projects and work items for individual records."""

VERSION = 11
DESCRIPTION = "work_context"


def up(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS projects(
        id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name TEXT NOT NULL, normalized_name TEXT NOT NULL, code TEXT NOT NULL DEFAULT '',
        revision INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0,
        UNIQUE(user_id,id))""")
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS projects_active_name ON projects(user_id,normalized_name) WHERE archived=0")
    connection.execute("""CREATE TABLE IF NOT EXISTS work_items(
        id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        project_id TEXT NOT NULL, title TEXT NOT NULL, normalized_title TEXT NOT NULL,
        source_url TEXT NOT NULL DEFAULT '', completed INTEGER NOT NULL DEFAULT 0,
        revision INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(user_id,project_id) REFERENCES projects(user_id,id))""")
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS work_items_active_title ON work_items(user_id,project_id,normalized_title) WHERE archived=0")
    columns = {row[1] for row in connection.execute("PRAGMA table_info(worklog)")}
    for name, definition in (("project_id", "TEXT REFERENCES projects(id)"),
                             ("work_item_id", "TEXT REFERENCES work_items(id)"),
                             ("project_label", "TEXT NOT NULL DEFAULT ''"),
                             ("work_item_label", "TEXT NOT NULL DEFAULT ''")):
        if name not in columns:
            connection.execute(f"ALTER TABLE worklog ADD COLUMN {name} {definition}")
    connection.execute("CREATE INDEX IF NOT EXISTS worklog_project_dates ON worklog(user_id,project_id,d,id)")
    connection.execute("CREATE INDEX IF NOT EXISTS worklog_work_item_dates ON worklog(user_id,work_item_id,d,id)")
