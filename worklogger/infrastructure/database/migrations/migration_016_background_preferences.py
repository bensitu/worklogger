"""Allow enabling a background preference before media is selected."""

from worklogger.infrastructure.database.current_schema import (
    CURRENT_SCHEMA_VERSION,
    TABLE_STATEMENTS,
    create_current_schema,
)

VERSION = CURRENT_SCHEMA_VERSION
DESCRIPTION = "background_preferences_without_media"
BACKGROUND_COLUMNS = ("user_id", "data", "format", "width", "height", "frames", "enabled", "opacity")


def up(connection):
    existing = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='background_images'").fetchone()
    if existing:
        actual = tuple(row[1] for row in connection.execute("PRAGMA table_info(background_images)"))
        if set(actual) != set(BACKGROUND_COLUMNS):
            raise ValueError("database_schema_unsupported")
        statement = TABLE_STATEMENTS["background_images"].replace(
            "IF NOT EXISTS background_images(", "background_images_next("
        )
        connection.execute(statement)
        columns = ",".join(BACKGROUND_COLUMNS)
        connection.execute(f"INSERT INTO background_images_next({columns}) SELECT {columns} FROM background_images")
        connection.execute("DROP TABLE background_images")
        connection.execute("ALTER TABLE background_images_next RENAME TO background_images")
    create_current_schema(connection)
