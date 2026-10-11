# Database

## Structure and Semantics

The database is local SQLite. Canonical DDL lives in
`infrastructure/database/current_schema.py`.
SQL identifiers are storage contracts, not localized UI captions.

| Table | Purpose |
| --- | --- |
| `schema_migrations` | Applied versions and timestamps |
| `users` | Login IDs, display names, credentials, roles |
| `login_attempts` | Canonical account keys and lockout state |
| `settings` | Account/key string values and saved state |
| `worklog` | Individual time records with IDs and revisions |
| `daily_notes` | Independent account/date memos |
| `quick_logs` | Retained previous entries |
| `work_types` | Account-owned Work/Break/Leave catalog |
| `projects` | Account-owned project catalog |
| `work_items` | Project-specific work items |
| `entry_changes` | Reversible record snapshots |
| `reports` | Saved report content and generation references |
| `report_revisions` | Saved versions of each report |
| `report_templates` | Account/language/type templates |
| `calendar_events` | Imported events |
| `external_identities` | Provider subjects and issuer metadata |
| `activity_events` | Activity records with optional user association |
| `background_images` | Account image bytes, enablement, and opacity |

`users.username` is the login ID; `username_key` is its canonical lookup key.
`display_name` is an editable alias and never an ownership identifier.

`worklog.note` is record content; `daily_notes.content` is a separate memo.
`worklog.break` stores historical deducted hours, not a separate rest record.
Dates use ISO text, clocks use `HH:MM`, and durations use hours.
Captured `started_at`/`ended_at` contain offsets; clock-only rows have no inferred
timezone. Saved type/context labels preserve historical meaning.
Overlap checks compare UTC instants when both records have captured offsets.
If either lacks offsets, their stored date/clock intervals are compared without
inventing a timezone. This conservatively reserves ambiguous historical clock
ranges, while two captured occurrences of a repeated DST hour can remain distinct.

## Compatibility

Startup checks the stored structure and ledger against supported contracts.
Missing keys/columns, unknown layouts, executable schema objects, and unknown
future versions are rejected rather than reset.
Canonical source baselines are ledger versions 14, 15, and 16, with the full
required structure. Earlier ledger entries may remain as history but do not make
an incomplete or unsupported source eligible for conversion.

Released unversioned layouts compatible with v3.3.3 use the released import
adapter. Credentials, account IDs, work content, report identities, and historical
deductions are preserved. Import does not invent offsets, source references,
or break positions. Supported canonical predecessors upgrade transactionally.

A populated compatible database receives a complete private `.bak_upgrade_*`
snapshot before conversion. It includes committed WAL data. Schema changes,
copied rows, and the ledger commit together; failure rolls back.
Fresh/current databases do not need repeated upgrade snapshots.
There is no automatic downgrade.

To upgrade a copy explicitly, close the application and run from the repository:

```sh
python scripts/upgrade_database.py --source ./original.db --destination ./upgraded.db
```

The destination must not exist. The source remains read-only.
Optional template import requires an explicit existing account and language:

```sh
python scripts/upgrade_database.py --source ./original.db --destination ./upgraded.db --template-file ./template.json --template-user sample --template-language en_US
```

Retain the originals until the copied data is reviewed.

## Transactions

The connection factory enables foreign keys, WAL, a busy timeout, and short-lived
connections. Writes use `BEGIN IMMEDIATE` and the factory's lock. The desktop also
holds a database-specific process lock.

Read contexts use independent WAL snapshots and query-only connections; they do
not hold the writer lock. Use `transaction(write=True)` for mutations and close
a read context before starting a write. File replacement pauses new connections,
waits for existing contexts to close, and reinitializes the factory afterward.
Integrity verification remains mandatory during initial preparation and replacement.

Record writes recheck ownership, revisions, and overlaps inside the transaction.
Timer completion persists its record and timer state together. Note saves persist
sharing/draft changes atomically. Report saves and restoration create versions
without changing first-save identity.

Record undo retains up to 50 eligible changes for 30 days and checks expected
rows before restoring them. It does not restart timers or reverse CSV replacement
or whole-database restore. Reports retain up to 50 versions per report.

## Backup and Restore

Administrator backups contain all accounts and application tables, including
background images and history. New backups exclude proxy passwords.
OS credentials, remembered sessions, models, and device language preferences
require separate handling.

Restore validates integrity, supported structure, and the administrator's login
ID/account ID. It prepares an unpublished copy before replacing the target,
retains a `.bak_restore_*` copy, and ends the authenticated session.

Preserve a pending `.pre_restore` file and any database journals before recovering
an interrupted restore. Startup offers rollback or keeping the restored database
only when the selected copy validates. Cancel leaves files unchanged. Recovery
retains the previous copy; rollback also archives a replaced candidate separately.
The latest three automatically generated `.bak_restore_*` snapshots are retained;
manual backups and recovery-candidate archives are not rotated by this policy.
Do not rename/reset a database after a lock, permission,
or I/O error. Do not copy only the main file while committed data remains in WAL.

Databases and backups are unencrypted. Restrict access and keep independent
backups. Cross-device credentials may need re-entry.
See [security](security.md).
