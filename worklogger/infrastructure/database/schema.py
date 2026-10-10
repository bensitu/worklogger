"""Supported stored tables shared by upgrade and recovery adapters."""

from worklogger.infrastructure.database.current_schema import TABLE_STATEMENTS
from worklogger.infrastructure.database.released_import import RELEASED_TABLES

SUPPORTED_TABLES = frozenset(TABLE_STATEMENTS) | RELEASED_TABLES
