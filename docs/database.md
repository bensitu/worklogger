# Database and Compatibility

## Supported Structure

The current schema version is 15, independently of the application version.
New databases create the complete current structure directly. Development
migrations 1 through 14 are no longer replayed or bundled.

Supported inputs are an empty database, the released unversioned 3.x layout
verified against v3.3.3, and the complete latest structure carrying schema ledger
14 or 15. A complete current database without its ledger can receive a new ledger
without rewriting records. Earlier development-v4 ledgers, incomplete current
schemas, unknown tables, views, triggers and future versions are rejected before
opening the source for mutation. The original is not automatically repaired,
merged, reset or downgraded.

The canonical definition is [current_schema.py](../worklogger/infrastructure/database/current_schema.py).
Columns, declared types, primary keys and foreign-key declarations are checked
against that definition even when no conversion is pending. Existing optional
provider metadata and the archived `oauth_identities` table can remain. Routine
startup performs structural checks without rescanning all foreign-key rows.
Import, restore and post-conversion validation also check stored foreign-key
relationships. SQLite integrity checks remain part of connection preparation.

## Ownership and Naming

The database is local SQLite. Account-owned foreign keys cascade on account
deletion. Activity events deliberately permit an absent user reference; deleting
an account clears that reference. Authentication queries and current writes use
the account identifier, not the display alias.

| Table or column | Current meaning |
| --- | --- |
| `schema_migrations` | Applied schema versions, descriptions and timestamps |
| `users` | Account identities, display aliases, credential material and role/status fields |
| `login_attempts` | Canonical login ID, failed-attempt count and lockout timestamps |
| `users.username` / `username_key` | Login ID and canonical lookup key |
| `users.display_name` | Editable alias, independent of login and ownership |
| `worklog` | Independently editable time records with IDs and revisions |
| `worklog.d` / `start` / `end` | Record date and local clock boundaries |
| `worklog.note` | Time-record content, not the independent daily memo |
| `worklog.break` | Historical deducted hours, not a counted break record |
| `worklog.started_at` / `ended_at` | Captured offset-aware boundaries |
| `work_type_label` / `work_type_category` | Historical custom type and accounting snapshots |
| `daily_notes.content` | Independent account/date memo |
| `daily_notes` | Independent account/date memos |
| `quick_logs` | Retained historical quick entries, transferable into memos |
| `settings` | Account/key string values |
| `work_types` | Editable Work/Break/Leave classifications |
| `projects` | Optional account-owned projects |
| `work_items` | Project-specific account-owned work items |
| `entry_changes` | Reversible before/after/expected record snapshots |
| `reports` | Saved daily, weekly and monthly reports |
| `report_revisions` | Individual saved versions of each report |
| `report_templates` | Templates owned by account, language and report type |
| `calendar_events` | Imported calendar events, independently stored |
| `external_identities` | Account-owned provider identities and issuer metadata |
| `activity_events` | Optional activity records, not a complete action history |
| `background_images` | Optional raster bytes and opacity, disabled in the desktop configuration |

SQL names are stable storage contracts, not localized captions. Dates use ISO
text, clock fields use `HH:MM`, and durations are hours. Daily collection readers
aggregate individual entries; editors and exports retain each entry's identity.

## Released Database Import

The single released-import adapter renames `salt` to `password_salt`, establishes
canonical login keys and a separate display-name field, and converts daily work
rows into individual entries. User IDs, credentials, roles, records, report IDs,
calendar events, quick entries and provider metadata are preserved. Display names
start empty; no name is inferred from an identity provider.

Existing clock-only durations remain wall-clock durations because their original
timezone is unknown. Historical deducted breaks are preserved, not replaced with
invented break periods. Old daily note text is retained in independent memos;
meaningful work and leave rows remain. Note-only dates do not acquire empty time
records. Existing reports receive an initial recoverable version with unavailable
generation references rather than invented source history.

Known released setting names are mapped once, including language, mode, hours,
AI privacy, API address and model. A newer explicit value takes precedence.
Password-change requirements are retained. Local password availability follows
the released version's nonempty password-hash rule; a missing recovery key alone
does not disable login. Unknown archived settings remain stored.

The last complete development ledger (14) receives only the new current-schema
ledger entry after validation. Names, IDs, timestamps, revisions, record snapshots,
memos, custom types, contexts and background bytes are not rewritten. Earlier
development-v4 layouts and their automatic-recording draft conversion are not
supported upgrade inputs.

## Transactions and Recovery

`SQLiteConnectionFactory` enables foreign keys, uses a 5,000 ms busy timeout,
WAL and `synchronous=NORMAL`. Connections are short-lived; writes share the
factory's reentrant lock and use `BEGIN IMMEDIATE`. The desktop also holds a
database-specific process lock. External clients must still honor SQLite locking.

Before converting a populated supported source, the runner takes the writer lock
and creates one private complete `.bak_upgrade_*` snapshot through a separate
read-only connection. It includes committed WAL data and checks integrity before
any conversion. Schema changes and ledger updates commit together. Backup or
conversion failure preserves the original schema and data. Fresh and already
current databases do not accumulate compatibility backups.

Record creation, editing, deletion, splitting, merging, associations, historical
break placement and undo use atomic transactions with revision and overlap checks.
The latest 50 undo snapshots are retained for 30 days. Undo compares the expected
current rows; it does not restart a timer. CSV replacement and whole-database
restore are not covered by record undo. Single-record CSV imports do not create
or overwrite independent memos unless a note-only row is present.

Report updates compare the loaded revision, retain IDs and first-save timestamps,
and save a new version atomically. Recovery also creates a new version. The latest
50 versions per report are retained. Content is bounded to 1 MiB and provenance
to 8 MiB. Account/report deletion cascades to versions.

## Backup and Restore

Desktop backup and restore require a current administrator. A backup is a complete
database copy containing all accounts, credential hashes, background media and
record/report history. Proxy passwords are excluded; OS credentials, sessions,
model files and native language preferences are not copied.

Restore opens the source read-only, validates its supported shape and the current
account's login ID and integer ID, and snapshots committed WAL data. Conversion
and integrity checks run on an unpublished temporary copy. A complete result
replaces the target only when it is not busy; the previous database is retained as
a unique `.bak_restore_*` copy. Restore is replacement, not a per-user merge, and
ends the current authenticated session.

An interrupted `.pre_restore` file blocks startup and further replacement. Normal
startup never recreates a damaged or inaccessible database. Explicit maintenance
recovery preserves confirmed corruption and its sidecars, retaining three copies
by default; permission, lock and I/O failures do not rename the original.

Database data and backups are not encrypted at rest. File permissions are
restricted on a best-effort basis; Windows directory access controls remain
necessary. There is no automatic downgrade. Retain compatible independent
backups before returning to an older executable.
