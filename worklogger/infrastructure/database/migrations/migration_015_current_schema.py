"""Initialize the complete current schema without replaying development migrations."""

from worklogger.infrastructure.database.current_schema import (
    CURRENT_SCHEMA_VERSION,
    create_current_schema,
)

VERSION = CURRENT_SCHEMA_VERSION
DESCRIPTION = "current_schema"


def up(connection):
    create_current_schema(connection)
