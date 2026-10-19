# Database

Collection reads reject undecodable stored records instead of returning incomplete
totals or reports. A read failure does not delete or rewrite the affected rows.
Invalid optional timezone metadata is logged; valid clock boundaries remain
readable using historical wall-clock accounting rather than invented offsets.
Break and leave records cannot contain a work arrangement or project context;
this validation also applies to clock-only records and historical snapshots.
Restore and recovery snapshots share the same bounded retention policy.

## Structure and Semantics

The database is local SQLite. Canonical DDL lives in
`infrastructure/database/current_schema.py`.
SQL identifiers are storage contracts, not localized UI captions.

Connection factories require a file-backed database. Reads can nest on their
owning thread while maintenance waits for existing connections to finish.
New connections and writes respect the configured busy timeout; a busy failure
leaves the transaction unchanged and can be retried after the other operation.

| Table | Purpose |
| --- | --- |
| `schema_migrations` | Applied versions and timestamps |
| `users` | Login IDs, display names, credentials, roles |
| `login_attempts` | Canonical account keys and lockout state |
| `settings` | Account/key string values and saved state |
| `worklog` | Individual time records with IDs and revisions |
| `daily_notes` | Independent account/date memos |
| `quick_logs` | Retained previous entries |
| `entry_types` | Account-owned Work/Break/Leave catalog |
| `work_modes` | Account-owned custom work arrangements |
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

Historical quick logs are accessed through a read-only repository. Transferring
them into daily notes saves the note and removes the matching source entries in
one transaction, with account, date, and content conflict checks.

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

Database startup recovery validates replacements on a separate copy before any
active files are moved. Original file groups are retained in a unique
`database-recovery` subdirectory. A replacement marker prevents initialization
against partially moved files after interruption. Recovery retains the desktop
instance lock and requires manual account authentication afterward; it does not
bypass passwords or merge accounts. See [startup recovery](troubleshooting.md#missing-data-or-database-errors).

Startup checks the stored structure and ledger against supported contracts.
Missing keys/columns, unknown layouts, executable schema objects, and unknown
future versions are rejected rather than reset.
Required named indexes are checked for their columns, uniqueness and partial
index attributes; incomplete constraints are not silently repaired during startup.
The current contract is schema version 19, with its complete required structure
and a ledger containing only version 19. Versions 17 and 18 upgrade transactionally
after a complete backup. Composite foreign keys enforce record/project/work-item
account ownership and project membership. Identity bindings are normalized into
the same uniqueness contract as new databases; conflicting ownership aborts the
upgrade. Version 17 also gains custom work arrangements, `work_mode_label`, and
the `work_modes` account catalog.
Existing IDs, revisions, timers, and reversible snapshots are preserved. Unreleased development
versions, including 14, 15, and 16, and unversioned development layouts are rejected
before writable initialization. They are never reset, relabeled, or upgraded by
production startup. Preserve developer-local files and use fresh test data or a
separately reviewed, explicitly approved one-time conversion outside production.

Released unversioned layouts compatible with v3.3.3 use the released import
adapter. Credentials, account IDs, work content, report identities, and historical
deductions are preserved. Import does not invent offsets, source references,
or break positions. The released SQL column is `work_type`; import maps it to
`entry_type` and rejects unknown non-null codes rather than guessing regular work.
Historical `remote` and `business_trip` retain those classification identities and
also populate the matching optional `work_mode`. Other released types receive no
inferred arrangement. Historical untimed leave and deducted breaks remain intact.

`worklog.work_mode` stores `onsite`, `remote`, `business_trip`, `other`, a
`custom:<uuid>` identifier, or NULL. Custom arrangements retain their saved name
in `work_mode_label`; renaming or archiving a catalog item does not rewrite records.
It is independent of classification and is only applicable to work-category
entries. `entry_types` retains account-owned custom definitions; historical labels
and categories are stored in `entry_type_label` and `entry_type_category` snapshots.
Fresh databases and released imports initialize version 19 directly. Versions 17
and 18 are supported versioned predecessors; there is no unversioned-current fallback.

A populated compatible database receives a complete private `.bak_upgrade_*`
snapshot before conversion. It includes committed WAL data. Schema changes,
copied rows, and the ledger commit together; failure rolls back.
Converted record counts, dates, clock ranges, and deductions are validated through
the stored-record reader and domain rules before the released worklog is dropped.
Note-only rows become daily notes; empty historical regular rows are retained.
Invalid values abort conversion without committing an unreadable target.
Fresh/current databases do not need repeated upgrade snapshots.
After a successful conversion, the latest three automatic upgrade snapshots are
retained. A failed conversion does not prune snapshots. Files with other names,
manual backups, and symbolic links are not removed by this retention policy.
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
rows before restoring them. CSV replacements save reversible time-record changes
per affected date within the same limits; independent memo changes are excluded.
Undo does not restart timers or reverse whole-database restore. Reports retain
up to 50 versions per report.

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

Local databases and SQLite database backups are unencrypted. Personal cloud
backups are separate account documents with client-side encryption enabled by
default; they cannot be restored as SQLite files. Restrict local access and keep
independent backups. Cross-device credentials may need re-entry.
See [security](security.md).
