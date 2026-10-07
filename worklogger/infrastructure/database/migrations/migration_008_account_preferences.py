"""Preserve account constraints and preferences from older installations."""

import sqlite3

VERSION = 8
DESCRIPTION = "account_preference_compatibility"

SETTING_RENAMES = (
    ("lang", "language"), ("dark", "dark_mode"),
    ("work_hours", "standard_work_hours"), ("default_break", "default_break_hours"),
    ("default_lunch", "default_break_hours"), ("monthly_target", "monthly_target_hours"),
    ("ai_context_include_notes", "ai_privacy_include_notes"),
    ("ai_context_include_calendar_titles", "ai_privacy_include_calendar"),
    ("ai_context_include_quick_log_details", "ai_privacy_include_quick_logs"),
)


def up(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE INDEX IF NOT EXISTS settings_key_user ON settings(key,user_id)")
    columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
    if "last_login_at" not in columns:
        connection.execute("ALTER TABLE users ADD COLUMN last_login_at TEXT")
    connection.execute("UPDATE users SET must_change_password=1 WHERE EXISTS "
        "(SELECT 1 FROM settings s WHERE s.user_id=users.id AND s.key='force_password_change' "
        "AND lower(s.value) IN ('1','true','yes','on'))")
    connection.execute("DELETE FROM settings WHERE key='force_password_change'")
    for previous, current in SETTING_RENAMES:
        connection.execute("INSERT INTO settings(user_id,key,value) SELECT user_id,?,value FROM settings WHERE key=? "
                           "ON CONFLICT(user_id,key) DO NOTHING", (current, previous))
    identity_columns = {row[1] for row in connection.execute("PRAGMA table_info(external_identities)")}
    for name, default in (("broker", "direct_oidc"), ("issuer", "")):
        if name not in identity_columns:
            connection.execute(f"ALTER TABLE external_identities ADD COLUMN {name} TEXT NOT NULL DEFAULT '{default}'")
    if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='oauth_identities'").fetchone():
        connection.execute("INSERT INTO external_identities(user_id,provider,broker,issuer,subject,email,display_name,created_at,updated_at) "
            "SELECT o.user_id,o.provider,'direct_oidc',o.provider,o.subject,o.email,o.display_name,o.created_at,o.updated_at "
            "FROM oauth_identities o WHERE NOT EXISTS (SELECT 1 FROM external_identities e "
            "WHERE e.user_id=o.user_id AND e.provider=o.provider AND e.subject=o.subject)")
