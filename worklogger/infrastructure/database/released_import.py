"""One-time conversion of released unversioned databases, not development schemas."""

from worklogger.domain.auth.policies import username_key
from worklogger.infrastructure.database.current_schema import (
    TABLE_STATEMENTS,
    create_current_schema,
)
from worklogger.infrastructure.database.migrations.ownership import normalize_identities

RELEASED_REQUIRED_COLUMNS = {
    "users": {"id", "username", "password_hash", "salt", "recovery_key_hash", "recovery_salt", "is_admin",
              "remember_token", "remember_token_expires_at", "created_at", "password_changed_at", "recovery_key_created_at"},
    "worklog": {"user_id", "d", "start", "end", "break", "note", "work_type", "overnight"},
    "settings": {"user_id", "key", "value"},
    "quick_logs": {"id", "user_id", "date", "time", "end_time", "description", "created_at"},
    "calendar_events": {"id", "user_id", "date", "start_time", "end_time", "summary", "description", "location", "all_day", "source_file"},
    "reports": {"id", "user_id", "type", "period_start", "period_end", "content", "created_at"},
}
RELEASED_TABLES = frozenset((*RELEASED_REQUIRED_COLUMNS, "login_attempts", "external_identities", "oauth_identities"))
RELEASED_ENTRY_TYPES = (
    "normal", "remote", "business_trip", "paid_leave", "comp_leave", "sick_leave",
    "meeting", "training", "break", "other",
)
SETTING_RENAMES = (
    ("lang", "language"), ("dark", "dark_mode"), ("work_hours", "standard_work_hours"),
    ("default_break", "default_break_hours"), ("default_lunch", "default_break_hours"),
    ("monthly_target", "monthly_target_hours"), ("ai_context_include_notes", "ai_privacy_include_notes"),
    ("ai_context_include_calendar_titles", "ai_privacy_include_calendar"),
    ("ai_context_include_quick_log_details", "ai_privacy_include_quick_logs"),
    ("ai_base_url", "external_model_base_url"), ("ai_model", "external_model_name"),
)


def validate_released_schema(connection, tables):
    if tables - RELEASED_TABLES:
        raise ValueError("database_schema_unsupported")
    for table, required in RELEASED_REQUIRED_COLUMNS.items():
        columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
        if not required.issubset(columns) or table == "worklog" and columns - required:
            raise ValueError("database_schema_unsupported")
    for table, expected in (("users", ("id",)), ("worklog", ("user_id", "d")), ("settings", ("user_id", "key"))):
        primary_key = tuple(row[1] for row in sorted(connection.execute(f'PRAGMA table_info("{table}")'), key=lambda row: row[5]) if row[5])
        if primary_key != expected:
            raise ValueError("database_schema_unsupported")
    if {row[1] for row in connection.execute("PRAGMA table_info(users)")} & {"username_key", "display_name", "local_password_enabled"}:
        raise ValueError("database_schema_unsupported")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("database_foreign_key_invalid")
    if connection.execute(
        f"SELECT 1 FROM worklog WHERE work_type IS NOT NULL AND work_type NOT IN ({','.join('?' for _ in RELEASED_ENTRY_TYPES)}) LIMIT 1",
        RELEASED_ENTRY_TYPES,
    ).fetchone() is not None:
        raise ValueError("database_entry_type_unsupported")


def import_released_schema(connection):
    names = [(username_key(row[1]), row[0]) for row in connection.execute("SELECT id,username FROM users")]
    if len({value[0] for value in names}) != len(names):
        raise ValueError("username_normalization_conflict")
    connection.execute("ALTER TABLE users RENAME COLUMN salt TO password_salt")
    for name, declaration in (("username_key", "TEXT NOT NULL DEFAULT ''"), ("display_name", "TEXT NOT NULL DEFAULT ''"),
                              ("local_password_enabled", "INTEGER NOT NULL DEFAULT 1"), ("must_change_password", "INTEGER NOT NULL DEFAULT 0")):
        connection.execute(f"ALTER TABLE users ADD COLUMN {name} {declaration}")
    if "last_login_at" not in {row[1] for row in connection.execute("PRAGMA table_info(users)")}:
        connection.execute("ALTER TABLE users ADD COLUMN last_login_at TEXT")
    connection.executemany("UPDATE users SET username_key=? WHERE id=?", names)
    for table, statement in TABLE_STATEMENTS.items():
        if table != "worklog":
            connection.execute(statement)
    normalize_identities(connection)
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS work_items_owner_project ON work_items(user_id,project_id,id)")
    connection.execute("UPDATE users SET local_password_enabled=CASE WHEN COALESCE(password_hash,'')='' THEN 0 ELSE 1 END")
    connection.execute("UPDATE users SET must_change_password=1 WHERE EXISTS (SELECT 1 FROM settings s "
                       "WHERE s.user_id=users.id AND s.key='force_password_change' AND lower(s.value) IN ('1','true','yes','on'))")
    connection.execute("DELETE FROM settings WHERE key='force_password_change'")
    for previous, current in SETTING_RENAMES:
        connection.execute("INSERT INTO settings(user_id,key,value) SELECT user_id,?,value FROM settings WHERE key=? "
                           "ON CONFLICT(user_id,key) DO NOTHING", (current, previous))
        connection.execute("DELETE FROM settings WHERE key=?", (previous,))
    _normalize_login_attempts(connection)
    connection.execute(TABLE_STATEMENTS["worklog"].replace("IF NOT EXISTS worklog(", "worklog_import(", 1))
    source_count = connection.execute("SELECT COUNT(*) FROM worklog").fetchone()[0]
    note_only_count = connection.execute('''SELECT COUNT(*) FROM worklog
        WHERE COALESCE(start,'')='' AND COALESCE(end,'')='' AND COALESCE("break",0)=0
            AND COALESCE(work_type,'normal')='normal' AND COALESCE(note,'')<>'' ''').fetchone()[0]
    connection.execute("INSERT INTO daily_notes(user_id,d,content) SELECT user_id,d,note FROM worklog WHERE COALESCE(note,'')<>''")
    connection.execute('''INSERT INTO worklog_import(user_id,d,start,end,"break",note,entry_type,overnight,work_mode)
        SELECT user_id,d,start,end,COALESCE("break",0),COALESCE(note,''),COALESCE(work_type,'normal'),COALESCE(overnight,0),
            CASE work_type WHEN 'remote' THEN 'remote' WHEN 'business_trip' THEN 'business_trip' ELSE NULL END
        FROM worklog WHERE NOT (COALESCE(start,'')='' AND COALESCE(end,'')='' AND COALESCE("break",0)=0
            AND COALESCE(work_type,'normal')='normal' AND COALESCE(note,'')<>'')''')
    _validate_imported_worklog(connection, expected_count=source_count - note_only_count)
    connection.execute("DROP TABLE worklog")
    connection.execute("ALTER TABLE worklog_import RENAME TO worklog")
    for name, declaration in (("revision", "INTEGER NOT NULL DEFAULT 0"), ("updated_at", "TEXT"),
                              ("provenance", "TEXT NOT NULL DEFAULT '{}'")):
        connection.execute(f"ALTER TABLE reports ADD COLUMN {name} {declaration}")
    connection.execute("INSERT INTO report_revisions(report_id,revision,content,saved_at,provenance) "
                       "SELECT id,revision,content,created_at,provenance FROM reports")
    create_current_schema(connection)


def _validate_imported_worklog(connection, *, expected_count):
    from datetime import date

    from worklogger.domain.worklog.rules import normalize_work_log
    from worklogger.infrastructure.repositories.worklog_mapping_sqlite import WorkLogStorage

    if connection.execute("SELECT COUNT(*) FROM worklog_import").fetchone()[0] != expected_count:
        raise ValueError("database_record_count_invalid")
    try:
        for row in connection.execute("SELECT * FROM worklog_import"):
            record = WorkLogStorage.from_row(row)
            # Validate deductions against the interval without rewriting historical values.
            normalize_work_log(record)
        for day, in connection.execute("SELECT d FROM daily_notes"):
            date.fromisoformat(day)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("database_record_invalid") from None


def _normalize_login_attempts(connection):
    merged = {}
    for name, count, locked, failed in connection.execute("SELECT username,failed_count,locked_until,last_failed_at FROM login_attempts"):
        key = username_key(name)
        previous = merged.get(key, (0, None, None))
        merged[key] = (min(20, previous[0] + int(count or 0)), max(previous[1] or "", locked or "") or None,
                       max(previous[2] or "", failed or "") or None)
    connection.execute("DELETE FROM login_attempts")
    connection.executemany("INSERT INTO login_attempts VALUES(?,?,?,?)", [(key, *value) for key, value in merged.items()])


