# Database and Compatibility

## Ownership and Connections

The database is local SQLite. Most business tables include `user_id`, and their
repositories query by the authenticated account. User-owned foreign keys cascade
on account deletion. The activity table intentionally allows an absent user ID
and has no user foreign key.

`SQLiteConnectionFactory` enables foreign keys on each connection, uses a
5,000 ms busy timeout, and configures file databases with WAL and
`synchronous=NORMAL`. Write transactions use `BEGIN IMMEDIATE` and an instance
`RLock`. Connections are short-lived. A second factory or process is not protected
by that Python lock; SQLite's locking remains relevant.

## Tables

| Table | Key and purpose |
| --- | --- |
| `schema_migrations` | `version` primary key; description and applied timestamp |
| `users` | Integer ID, unique username, password/recovery hashes and salts, administrator and password-change flags, remembered-token hash/expiry, timestamps |
| `login_attempts` | Username primary key, failure count, lock expiry, last failure |
| `worklog` | Composite `(user_id, d)` primary key; start/end, decimal-hour break, note, work type, overnight flag |
| `quick_logs` | Integer ID; user/date, optional start/end, description, creation timestamp |
| `settings` | Composite `(user_id, key)` primary key; string value |
| `reports` | Integer ID; user, type, inclusive period bounds, Markdown content, creation timestamp |
| `report_templates` | Integer ID and unique `(user_id, language, type)`; content and update timestamp |
| `calendar_events` | Integer ID; user/date, optional times, summary, description, location, all-day flag, source filename |
| `external_identities` | Integer ID, user, provider/subject, email/display name, timestamps; unique `(provider, subject)` |
| `activity_events` | Integer ID, optional user, event type, JSON details, creation timestamp |

The exact column declarations are in
[the initial schema](../worklogger/infrastructure/database/migrations/migration_001_initial_schema.py).
Dates are ISO-formatted text; work times are normalized `HH:MM`; breaks are stored
in hours. Daily notes live in `worklog.note`. No separate daily-note table exists.

Saving a new report inserts a row. Updating a saved report replaces its content
by ID, with account, type, and period checks. Its ID and creation timestamp are
preserved. A missing or mismatched ID is rejected rather than creating a new row.

Indexes support per-account/date access, report period lookup, template language
lookup, remembered tokens, identity ownership, and activity time ordering.
The standard authentication composition does not currently write every action to
the activity repository; the table is not a complete history of user operations.

## Migrations

`MigrationRunner` imports an explicit ordered module list, runs preparation hooks,
and records applied versions in `schema_migrations`. Re-running against an updated
database applies no additional versions. Do not infer schema compatibility from
the application version alone.

| Version | Operation |
| --- | --- |
| 1 | Create the application tables and indexes when absent |
| 2 | Normalize older authentication salt naming and add the required-password-change field |
| 3 | Normalize activity-event table/index names while preserving identifiers and content |

The initial definition uses current names for new databases. Migration 3 handles
previous layouts, including a database without a migration ledger. Compatibility
identifiers are confined to migration code and fixtures that exercise old files.

### Activity Storage Compatibility

Before changing an older activity table, preparation uses SQLite's backup API to
create `worklog.db.bak_activity_<UTC timestamp>_<unique identifier>` beside the
database. Committed WAL content is included. If backup creation fails, migration
does not proceed.

The migration renames the existing table and recreates the current index, retaining
row IDs, timestamps, JSON details, optional user references, and the automatic ID
sequence. An empty current table created during initialization can be replaced by
the existing populated table. An empty previous table can be removed when the
current table already contains data.

If both tables contain records, migration stops with
`activity_event_table_conflict`. It does not guess how to merge records or renumber
IDs. Preserve the original and backup, and resolve the duplicate storage on a copy.
Do not repeatedly retry against the only copy of important data.

Authentication compatibility similarly creates `worklog.db.bak_auth_*` before
changing an older credential layout. Neither migration resets passwords or edits
working-hour records. New databases do not need these compatibility backups.

## Backup and Restore

`SQLiteBackupService` uses the SQLite backup API and checks integrity. Backups are
whole-database copies, including all accounts and credential hashes. They exclude
model files, session files, operating-system keyring values, and native language
preferences.

Restore validates the source, requires the `users` table, and checks the expected
username when configured. It opens the source read-only and uses the SQLite backup
API to create a temporary snapshot, including committed source WAL content but not
uncommitted transactions. The snapshot is converted to a standalone rollback-journal
database and validated before replacing the target; no source checkpoint is required.
Restore keeps the previous database during replacement and runs migrations. A failed
migration attempts to restore the previous database. Restore is replacement, not a
per-user merge.

The implementation uses file replacement and removes SQLite sidecars; close
other processes using the database before restoring. Keep an independent backup
instead of treating temporary restore files as retention storage.

## Corruption and Permissions

The connection factory performs integrity checks when opening file databases.
With automatic recovery enabled, a database error may move the file to a timestamped
`.bak_*` path before a replacement is opened. The default retention count is three.
The generic retention pattern also matches compatibility backup names; copy
important backups outside this directory for long-term retention.

Database and sidecar permissions are restricted on a best-effort basis. On
Windows, this is not a replacement for directory access-control configuration.
SQLite data and backups are not encrypted at rest by WorkLogger.

There is no automatic downgrade migration. Before returning to an older executable,
restore a compatible backup with all application processes closed.
