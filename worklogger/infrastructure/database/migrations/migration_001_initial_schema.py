"""Initial clean SQLite schema."""

from __future__ import annotations

import sqlite3

VERSION = 1
DESCRIPTION = "initial_schema"


def up(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            recovery_key_hash TEXT,
            recovery_salt TEXT,
            is_admin INTEGER NOT NULL DEFAULT 0,
            must_change_password INTEGER NOT NULL DEFAULT 0,
            remember_token TEXT,
            remember_token_expires_at TEXT,
            created_at TEXT NOT NULL,
            password_changed_at TEXT NOT NULL,
            recovery_key_created_at TEXT,
            last_login_at TEXT
        );

        CREATE TABLE IF NOT EXISTS login_attempts(
            username TEXT PRIMARY KEY,
            failed_count INTEGER NOT NULL DEFAULT 0,
            locked_until TEXT,
            last_failed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS worklog(
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            d TEXT NOT NULL,
            start TEXT,
            end TEXT,
            "break" REAL NOT NULL DEFAULT 0,
            note TEXT NOT NULL DEFAULT '',
            work_type TEXT NOT NULL DEFAULT 'normal',
            overnight INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(user_id, d)
        );

        CREATE TABLE IF NOT EXISTS quick_logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            date TEXT NOT NULL,
            time TEXT NOT NULL DEFAULT '',
            end_time TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS settings(
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            key TEXT NOT NULL,
            value TEXT,
            PRIMARY KEY(user_id, key)
        );

        CREATE TABLE IF NOT EXISTS reports(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            type TEXT NOT NULL,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS report_templates(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            language TEXT NOT NULL,
            type TEXT NOT NULL,
            content TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, language, type)
        );

        CREATE TABLE IF NOT EXISTS calendar_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            date TEXT NOT NULL,
            start_time TEXT,
            end_time TEXT,
            summary TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            location TEXT NOT NULL DEFAULT '',
            all_day INTEGER NOT NULL DEFAULT 0,
            source_file TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS external_identities(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            provider TEXT NOT NULL,
            subject TEXT NOT NULL,
            email TEXT,
            display_name TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(provider, subject)
        );

        CREATE TABLE IF NOT EXISTS audit_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            event_type TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_worklog_user_date ON worklog(user_id, d);
        CREATE INDEX IF NOT EXISTS idx_quick_logs_user_date ON quick_logs(user_id, date);
        CREATE INDEX IF NOT EXISTS idx_reports_user_type_period
            ON reports(user_id, type, period_start, period_end);
        CREATE INDEX IF NOT EXISTS idx_report_templates_user_language
            ON report_templates(user_id, language);
        CREATE INDEX IF NOT EXISTS idx_calendar_events_user_date
            ON calendar_events(user_id, date);
        CREATE INDEX IF NOT EXISTS idx_users_remember_token ON users(remember_token);
        CREATE INDEX IF NOT EXISTS idx_external_identities_user
            ON external_identities(user_id);
        CREATE INDEX IF NOT EXISTS idx_audit_events_user_created
            ON audit_events(user_id, created_at);
        """
    )
