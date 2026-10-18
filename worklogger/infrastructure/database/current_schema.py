"""Canonical stored schema used by initialization and compatibility inspection."""

import sqlite3
from contextlib import closing
from functools import lru_cache

CURRENT_SCHEMA_VERSION = 19

TABLE_STATEMENTS = {
    "schema_migrations": """CREATE TABLE IF NOT EXISTS schema_migrations(
        version INTEGER PRIMARY KEY, description TEXT NOT NULL, applied_at TEXT NOT NULL)""",
    "users": """CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
        username_key TEXT NOT NULL DEFAULT '', display_name TEXT NOT NULL DEFAULT '',
        password_hash TEXT NOT NULL, password_salt TEXT NOT NULL, recovery_key_hash TEXT, recovery_salt TEXT,
        is_admin INTEGER NOT NULL DEFAULT 0, must_change_password INTEGER NOT NULL DEFAULT 0,
        local_password_enabled INTEGER NOT NULL DEFAULT 1, remember_token TEXT, remember_token_expires_at TEXT,
        created_at TEXT NOT NULL, password_changed_at TEXT NOT NULL, recovery_key_created_at TEXT, last_login_at TEXT)""",
    "login_attempts": """CREATE TABLE IF NOT EXISTS login_attempts(
        username TEXT PRIMARY KEY, failed_count INTEGER NOT NULL DEFAULT 0, locked_until TEXT, last_failed_at TEXT)""",
    "settings": """CREATE TABLE IF NOT EXISTS settings(
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, key TEXT NOT NULL, value TEXT, PRIMARY KEY(user_id,key))""",
    "projects": """CREATE TABLE IF NOT EXISTS projects(
        id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name TEXT NOT NULL, normalized_name TEXT NOT NULL, code TEXT NOT NULL DEFAULT '',
        revision INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0, UNIQUE(user_id,id))""",
    "work_items": """CREATE TABLE IF NOT EXISTS work_items(
        id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        project_id TEXT NOT NULL, title TEXT NOT NULL, normalized_title TEXT NOT NULL,
        source_url TEXT NOT NULL DEFAULT '', completed INTEGER NOT NULL DEFAULT 0,
        revision INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(user_id,project_id) REFERENCES projects(user_id,id))""",
    "entry_types": """CREATE TABLE IF NOT EXISTS entry_types(
        id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name TEXT NOT NULL, normalized_name TEXT NOT NULL, category TEXT NOT NULL CHECK(category IN ('work','break','leave')),
        revision INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0)""",
    "work_modes": """CREATE TABLE IF NOT EXISTS work_modes(
        id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name TEXT NOT NULL, normalized_name TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'work' CHECK(category='work'),
        revision INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0)""",
    "worklog": """CREATE TABLE IF NOT EXISTS worklog(
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        d TEXT NOT NULL, start TEXT, end TEXT, "break" REAL NOT NULL DEFAULT 0,
        note TEXT NOT NULL DEFAULT '', entry_type TEXT NOT NULL DEFAULT 'normal', overnight INTEGER NOT NULL DEFAULT 0,
        started_at TEXT, ended_at TEXT, revision INTEGER NOT NULL DEFAULT 0, capture_id TEXT,
        entry_type_label TEXT NOT NULL DEFAULT '', entry_type_category TEXT NOT NULL DEFAULT '',
        project_id TEXT REFERENCES projects(id), work_item_id TEXT REFERENCES work_items(id),
        project_label TEXT NOT NULL DEFAULT '', work_item_label TEXT NOT NULL DEFAULT '',
        work_mode TEXT, work_mode_label TEXT NOT NULL DEFAULT '',
        CHECK(work_mode IS NULL OR work_mode IN ('onsite','remote','business_trip','other')
            OR (work_mode GLOB 'custom:*' AND length(work_mode)=39 AND length(trim(work_mode_label)) BETWEEN 1 AND 80)),
        FOREIGN KEY(user_id,project_id) REFERENCES projects(user_id,id),
        FOREIGN KEY(user_id,project_id,work_item_id) REFERENCES work_items(user_id,project_id,id),
        CHECK(work_item_id IS NULL OR project_id IS NOT NULL))""",
    "daily_notes": """CREATE TABLE IF NOT EXISTS daily_notes(
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, d TEXT NOT NULL,
        content TEXT NOT NULL DEFAULT '', PRIMARY KEY(user_id,d))""",
    "quick_logs": """CREATE TABLE IF NOT EXISTS quick_logs(
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        date TEXT NOT NULL, time TEXT NOT NULL DEFAULT '', end_time TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL, created_at TEXT NOT NULL)""",
    "calendar_events": """CREATE TABLE IF NOT EXISTS calendar_events(
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        date TEXT NOT NULL, start_time TEXT, end_time TEXT, summary TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '', location TEXT NOT NULL DEFAULT '',
        all_day INTEGER NOT NULL DEFAULT 0, source_file TEXT NOT NULL DEFAULT '')""",
    "reports": """CREATE TABLE IF NOT EXISTS reports(
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        type TEXT NOT NULL, period_start TEXT NOT NULL, period_end TEXT NOT NULL, content TEXT NOT NULL,
        created_at TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0, updated_at TEXT, provenance TEXT NOT NULL DEFAULT '{}')""",
    "report_revisions": """CREATE TABLE IF NOT EXISTS report_revisions(
        report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
        revision INTEGER NOT NULL, content TEXT NOT NULL, saved_at TEXT,
        provenance TEXT NOT NULL DEFAULT '{}', PRIMARY KEY(report_id,revision))""",
    "report_templates": """CREATE TABLE IF NOT EXISTS report_templates(
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        language TEXT NOT NULL, type TEXT NOT NULL, content TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(user_id,language,type))""",
    "external_identities": """CREATE TABLE IF NOT EXISTS external_identities(
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        provider TEXT NOT NULL, subject TEXT NOT NULL, email TEXT, display_name TEXT, created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL, broker TEXT NOT NULL DEFAULT 'direct_oidc', issuer TEXT NOT NULL DEFAULT '', UNIQUE(provider,subject))""",
    "activity_events": """CREATE TABLE IF NOT EXISTS activity_events(
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, event_type TEXT NOT NULL,
        details TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL)""",
    "entry_changes": """CREATE TABLE IF NOT EXISTS entry_changes(
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        operation TEXT NOT NULL, before_json TEXT NOT NULL, after_json TEXT NOT NULL, expected_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')), undone INTEGER NOT NULL DEFAULT 0)""",
    "background_images": """CREATE TABLE IF NOT EXISTS background_images(
        user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        data BLOB, format TEXT, width INTEGER, height INTEGER, frames INTEGER,
        enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
        opacity INTEGER NOT NULL DEFAULT 50 CHECK(opacity BETWEEN 0 AND 100),
        CHECK((data IS NULL AND format IS NULL AND width IS NULL AND height IS NULL AND frames IS NULL)
            OR (data IS NOT NULL AND format IS NOT NULL AND width IS NOT NULL AND height IS NOT NULL AND frames IS NOT NULL
            AND length(data) BETWEEN 1 AND 20971520 AND format IN ('png','jpeg','webp','gif')
            AND width >= 720 AND height >= 720 AND (width >= 1280 OR height >= 1280)
            AND width*height <= 16000000 AND frames BETWEEN 1 AND 300 AND width*height*frames <= 128000000)))""",
}

INDEX_STATEMENTS = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_key ON users(username_key)",
    "CREATE INDEX IF NOT EXISTS idx_users_remember_token ON users(remember_token)",
    "CREATE INDEX IF NOT EXISTS settings_key_user ON settings(key,user_id)",
    "CREATE INDEX IF NOT EXISTS worklog_user_date ON worklog(user_id,d,start,id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS worklog_capture ON worklog(user_id,capture_id) WHERE capture_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS worklog_project_dates ON worklog(user_id,project_id,d,id)",
    "CREATE INDEX IF NOT EXISTS worklog_work_item_dates ON worklog(user_id,work_item_id,d,id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS projects_active_name ON projects(user_id,normalized_name) WHERE archived=0",
    "CREATE UNIQUE INDEX IF NOT EXISTS work_items_active_title ON work_items(user_id,project_id,normalized_title) WHERE archived=0",
    "CREATE UNIQUE INDEX IF NOT EXISTS work_items_owner_project ON work_items(user_id,project_id,id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS entry_types_active_name ON entry_types(user_id,normalized_name) WHERE archived=0",
    "CREATE INDEX IF NOT EXISTS entry_types_account ON entry_types(user_id,archived)",
    "CREATE UNIQUE INDEX IF NOT EXISTS work_modes_active_name ON work_modes(user_id,normalized_name) WHERE archived=0",
    "CREATE INDEX IF NOT EXISTS work_modes_account ON work_modes(user_id,archived)",
    "CREATE INDEX IF NOT EXISTS idx_quick_logs_user_date ON quick_logs(user_id,date)",
    "CREATE INDEX IF NOT EXISTS idx_calendar_events_user_date ON calendar_events(user_id,date)",
    "CREATE INDEX IF NOT EXISTS idx_reports_user_type_period ON reports(user_id,type,period_start,period_end)",
    "CREATE INDEX IF NOT EXISTS reports_account_period ON reports(user_id,type,period_start,created_at,id)",
    "CREATE INDEX IF NOT EXISTS idx_report_templates_user_language ON report_templates(user_id,language)",
    "CREATE INDEX IF NOT EXISTS idx_external_identities_user ON external_identities(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_activity_events_user_created ON activity_events(user_id,created_at)",
    "CREATE INDEX IF NOT EXISTS entry_changes_account_order ON entry_changes(user_id,id)",
)


def create_current_schema(connection):
    for statement in (*TABLE_STATEMENTS.values(), *INDEX_STATEMENTS):
        connection.execute(statement)


@lru_cache(maxsize=3)
def schema_columns(version=CURRENT_SCHEMA_VERSION):
    if version == 17:
        return {table: (tuple(column for column in values[0] if table != "worklog" or column[0] != "work_mode_label"),
                        values[1], values[2]) for table, values in schema_columns(18).items() if table != "work_modes"}
    if version not in (18, CURRENT_SCHEMA_VERSION):
        raise ValueError("database_version_unsupported")
    with closing(sqlite3.connect(":memory:")) as connection:
        if version == 18:
            for table, statement in TABLE_STATEMENTS.items():
                if table == "worklog":
                    statement = statement.split(",\n        FOREIGN KEY(user_id,project_id)")[0] + ")"
                connection.execute(statement)
            for statement in INDEX_STATEMENTS:
                if "work_items_owner_project" not in statement:
                    connection.execute(statement)
        else:
            create_current_schema(connection)
        tables = set(TABLE_STATEMENTS)
        return {table: (tuple((row[1], row[2], row[5]) for row in connection.execute(f'PRAGMA table_info("{table}")')),
                        foreign_key_contract(connection, table), index_contract(connection, table, include_unique=version >= 19))
                for table in tables}


def index_contract(connection, table, *, include_unique=True):
    indexes = {}
    for row in connection.execute(f'PRAGMA index_list("{table}")'):
        if row[3] != "c" and not (include_unique and row[3] == "u"):
            continue
        name = row[1]
        quoted = name.replace('"', '""')
        columns = tuple((value[2], value[3], value[4], value[5])
                        for value in connection.execute(f'PRAGMA index_xinfo("{quoted}")'))
        key = name if row[3] == "c" else ("unique", columns)
        indexes[key] = (row[2], row[3], row[4], columns)
    return indexes


def foreign_key_contract(connection, table):
    groups = {}
    for row in connection.execute(f'PRAGMA foreign_key_list("{table}")'):
        groups.setdefault((row[0], row[2], row[5], row[6]), []).append((row[1], row[3], row[4]))
    return frozenset((target, tuple((source, destination) for _sequence, source, destination in sorted(columns)), update, delete)
                     for (_identity, target, update, delete), columns in groups.items())


def validate_current_schema(connection, *, check_data=True, version=CURRENT_SCHEMA_VERSION):
    contract = schema_columns(version)
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    if tables - set(contract) - {"oauth_identities"}:
        raise ValueError("database_schema_unsupported")
    for table, (required, foreign_keys, indexes) in contract.items():
        actual = {row[1]: (row[2], row[5]) for row in connection.execute(f'PRAGMA table_info("{table}")')}
        if any(actual.get(name) != (declaration, primary_key) for name, declaration, primary_key in required):
            raise ValueError("database_schema_unsupported")
        if foreign_key_contract(connection, table) != foreign_keys:
            raise ValueError("database_schema_unsupported")
        actual_indexes = index_contract(connection, table, include_unique=version >= 19)
        if any(actual_indexes.get(name) != definition for name, definition in indexes.items()):
            raise ValueError("database_schema_unsupported")
    if check_data and connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("database_foreign_key_invalid")
