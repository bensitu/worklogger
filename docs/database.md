# Database and Compatibility

Collection readers omit records with invalid dates or numeric fields and log only
the count, not their contents. Invalid optional timestamps are presented as absent.
The original rows remain unchanged so they can be recovered from a retained copy.
Single-record and storage-operation failures still propagate to the application.
Quick-log updates and deletions require an existing row belonging to the account;
missing records are not reported as successful changes.
Database backups exclude proxy passwords; re-enter them in the system credential
store after restoring on another machine. Encrypted fallback credentials require
their original private key, and Windows-protected keys require the same OS account.

## Ownership and Connections

The database is local SQLite. Most business tables include `user_id`, and their
repositories query by the authenticated account. User-owned foreign keys cascade
on account deletion. The activity table intentionally allows an absent user ID
and has no user foreign key.

`SQLiteConnectionFactory` enables foreign keys on each connection, uses a
5,000 ms busy timeout, and configures file databases with WAL and
`synchronous=NORMAL`. Write transactions use `BEGIN IMMEDIATE` and an instance
`RLock`. Connections are short-lived and operations using the same factory are
serialized. Integrity is checked once on the first successful open. The desktop
also holds a database-specific process lock throughout authentication and use;
external SQLite clients still require SQLite's own locking protections.

## Tables

| Table | Key and purpose |
| --- | --- |
| `schema_migrations` | `version` primary key; description and applied timestamp |
| `users` | Integer ID, unique username, password/recovery hashes and salts, administrator and password-change flags, remembered-token hash/expiry, timestamps |
| `login_attempts` | Username primary key, failure count, lock expiry, last failure |
| `worklog` | Integer entry ID; user/date, start/end, offset-aware timestamps, historical break deduction, independent content, work type, revision and capture identifier |
| `work_types` | Account-owned custom classification IDs, normalized unique active names, accounting category, revision and archived flag |
| `daily_notes` | Composite `(user_id, d)` primary key; independent daily note content |
| `quick_logs` | Integer ID; user/date, optional start/end, description, creation timestamp |
| `settings` | Composite `(user_id, key)` primary key; string value |
| `reports` | Integer ID; user, type, inclusive period bounds, Markdown content, creation timestamp |
| `report_templates` | Integer ID and unique `(user_id, language, type)`; content and update timestamp |
| `calendar_events` | Integer ID; user/date, optional times, summary, description, location, all-day flag, source filename |
| `external_identities` | Integer ID, user, provider/subject, email/display name, timestamps; unique `(provider, subject)` |
| `activity_events` | Integer ID, optional user, event type, JSON details, creation timestamp |

Initial tables are defined in
[the initial schema](../worklogger/infrastructure/database/migrations/migration_001_initial_schema.py);
the current work-log definition is in
[the entry migration](../worklogger/infrastructure/database/migrations/migration_007_worklog_entries.py).
Dates are ISO-formatted text; work times are normalized `HH:MM`; breaks are stored
in hours. Daily notes live in `daily_notes`; time-entry content is stored separately
in `worklog.note`. Multiple entries may belong to the same account and date.
Collection reads return daily summaries, while editing and exports use individual
entries. The compatibility daily-save API refuses to replace a multi-entry day.

Saving a new report inserts a row. Updating a saved report replaces its content
by ID, with account, type, and period checks. Its ID and creation timestamp are
preserved. A missing or mismatched ID is rejected rather than creating a new row.
Report deletion is scoped to the account and saved ID. Desktop requests also include
the previously loaded content, checked atomically with deletion to reject stale
requests without removing a report that another operation changed.

Indexes support per-account/date access, report period lookup, template language
lookup, remembered tokens, identity ownership, and activity time ordering.
The standard authentication composition does not currently write every action to
the activity repository; the table is not a complete history of user operations.

## Migrations

`MigrationRunner` imports an explicit ordered module list, identifies pending
versions, and records applied versions in `schema_migrations`. Re-running against an updated
database applies no additional versions. Do not infer schema compatibility from
the application version alone.

| Version | Operation |
| --- | --- |
| 1 | Create the application tables and indexes when absent |
| 2 | Normalize older authentication salt naming and add the required-password-change field |
| 3 | Normalize activity-event table/index names while preserving identifiers and content |
| 4 | Add a unique NFKC/casefold account key and explicit local-password availability |
| 5 | Copy existing notes to independent storage and remove note-only empty work rows |
| 6 | Add optional offset-aware start/end timestamps, leaving existing clock-only records unchanged |
| 7 | Replace the daily primary key with entry IDs, preserve historical content and break deductions, add date/capture indexes and optimistic revisions, and retain previous automatic drafts for conversion |
| 8 | Complete released account fields, map older preferences, retain password-change requirements and identity metadata, and index cross-account settings lookups |
| 9 | Add custom type name/category snapshots to work entries, an account-owned type catalog, and an indexed report-date range lookup |

Migration 9 leaves built-in classifications unchanged and initializes their
snapshot columns to empty strings. Custom records use a `custom:` UUID identifier
with a saved name and Work/Break/Leave category. Historical accounting uses these
columns, not a join to the editable catalog. Catalog edits use revision checks;
archiving hides a type from new entries without deleting its historical snapshots.

The runner creates one complete private SQLite snapshot before converting populated
tables, rather than a separate copy for each migration. Table replacement and settings-key conversion are transactional. Existing
timestamps and break deductions are copied without guessing when a break occurred.
Daily notes remain independent. The new timer service converts the previous account
draft on first use; malformed state remains available for deliberate recovery.

New manual and automatic entries use zero legacy break deduction. Breaks are
independent `break` entries and contribute no worked or leave hours. Entry updates
and deletions require the account, ID, and revision. Overlap checks include adjacent
dates and the active timer, inside the write transaction. Automatic completion and
the corresponding timer-state change commit together. Capture identifiers prevent
duplicate insertion of the same automatic period. Imported calendar-event deletion
checks account ownership and the complete expected row before removing it.
The fixed-duration break shortcut writes its complete period immediately and
checks the expected absence of an active timer in the same transaction. A timer
created by another application instance or a conflicting period rolls back the
write. It requires no schema or settings-format change.
Shortcut breaks use a `fixed-break:` capture-ID prefix. A confirmed early Start
updates that break with an expected revision and creates the timer in one
transaction. If the click coincides with the break's start, deletion and timer
creation commit together instead. Failures roll back both changes.

Migration 6 creates a private pre-change snapshot when existing work rows are
present. New desktop entries use the system's named timezone; automatic entries
retain their captured offsets. Duration is measured in UTC. Editing only a note or
break preserves timestamps. Changing start/end times resolves them in the current
system zone. Ambiguous manual times use the first occurrence; nonexistent local
times are rejected. Existing clock-only rows retain their prior wall-clock duration
because no original timezone can be reconstructed reliably.

The initial definition uses current names for new databases. Migration 3 handles
previous layouts, including a database without a migration ledger. Compatibility
identifiers are confined to migration code and fixtures that exercise old files.

### Activity Storage Compatibility

Before changing an older activity table, preparation uses SQLite's backup API to
create `worklog.db.bak_upgrade_<UTC timestamp>_<unique identifier>` beside the
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

Authentication compatibility uses the same `worklog.db.bak_upgrade_*` snapshot
before changing an older credential layout. Neither migration resets passwords or edits
working-hour records. New databases do not need these compatibility backups.

Account-key migration shares the private upgrade snapshot
before changing an existing account table. Display names and integer user IDs
remain unchanged. A canonical-name collision stops the entire transaction with
`username_normalization_conflict`; accounts are never merged or renamed automatically.
Resolve conflicting display names on a preserved copy before retrying. Login,
recovery lookup, account uniqueness, and failed-attempt records share the same key.
Existing linked accounts without a recovery credential are treated conservatively
as external-only accounts. An administrator can establish a temporary local
password when needed. Unversioned databases with current columns are also supported.

Deleting a user clears the user reference in retained activity records rather
than leaving a reference to a nonexistent account. Other account-owned data keeps
its existing cascade behavior.

Daily-note migration uses the same private upgrade snapshot when notes
exist, preserves their exact content, and leaves meaningful work/leave rows intact.
Saving a standalone note never creates a work row. Deleting work preserves its
note, and deleting an account still removes both. Editor writes compare the loaded
note content within the transaction; a conflicting edit rejects the save without
altering either note or work fields. Explicit CSV replacement remains an intentional
overwrite. CSV export includes note-only dates, which are imported without creating
empty work rows. Calendar queries include saved note markers. Report and AI
queries require explicit per-date permission before collecting a memo. Memos,
permissions, and draft removal commit together; content and sharing checks
reject conflicting saves. Drafts and sharing use account-scoped settings keys,
not work rows or a new schema.

## Backup and Restore

`SQLiteBackupService` uses the SQLite backup API and checks integrity. Desktop
backup and restore require a current administrator account. Backups are
whole-database copies, including all accounts and credential hashes. They exclude
model files, session files, operating-system keyring values, and native language
preferences.

Restore validates supported schema versions and table names, rejects triggers and
views, and requires the current account's username and ID to agree. It opens the
source read-only and uses the SQLite backup
API to create a temporary snapshot, including committed source WAL content but not
uncommitted transactions. The snapshot is converted to a standalone rollback-journal
database and validated before replacing the target; no source checkpoint is required.
Migrations run on the temporary snapshot before replacement. The previous database
is retained as a uniquely named `.bak_restore_*` file. Successful restore ends the
current session and requires authentication again. Restore is replacement, not a
per-user merge.

Connections and replacement share a process-local lock. Restore refuses a busy
target rather than discarding its WAL. An interrupted `.pre_restore` file is
preserved and blocks startup and further replacement until recovery is completed.
Keep independent backups and close other processes before restoring.

## Corruption and Permissions

The connection factory checks integrity once per factory initialization, not on
every query. Normal desktop startup never automatically replaces a damaged or
inaccessible database. Explicitly enabled maintenance recovery handles only
confirmed corruption, preserving the database and its WAL/SHM files together with
unique `.bak_corrupt_*` names. Its retention count defaults to three and does not
match migration or restore backups. Lock, permission, and I/O failures are raised
without renaming the original database.

Database and sidecar permissions are restricted on a best-effort basis. On
Windows, this is not a replacement for directory access-control configuration.
SQLite data and backups are not encrypted at rest by WorkLogger.

There is no automatic downgrade migration. Before returning to an older executable,
restore a compatible backup with all application processes closed.
