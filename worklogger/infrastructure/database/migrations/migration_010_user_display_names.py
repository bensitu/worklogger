"""Separate user presentation names from stable login identifiers."""

VERSION = 10
DESCRIPTION = "user_display_names"


def up(connection):
    columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
    if "display_name" not in columns:
        connection.execute("ALTER TABLE users ADD COLUMN display_name TEXT NOT NULL DEFAULT ''")
