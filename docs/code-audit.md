# Code Audit

## Scope and Verification

This review covers stored schema compatibility, account and time-record writes,
CSV portability, authentication, background jobs, naming and module boundaries.
All database checks use isolated fixtures, not writable copies of user data.

The initial complete test run contained 480 tests and one failure: a report-history
test expected only migration 13 after migration 14 had been introduced. Static
undefined-name and unused-import checks passed. This is a stale compatibility test,
not evidence that the migration itself loses report content.

## Corrected Behavior

Password login checks the verified hash and salt again inside the login transaction.
An upgrade cannot replace a password reset while verification was in progress.
Password changes and recovery-key resets similarly compare the verified credentials;
an already consumed credential cannot authorize a later write. Remembered-token
validation and the login timestamp update are performed in one transaction.

CSV time-record imports do not create or overwrite independent daily memos from a
single record's content. Explicit note-only rows still import memos. Replacing time
records without a memo row preserves an existing independent memo. The six-column
CSV contract is unchanged.

## Schema Compatibility

Current initialization builds the complete schema at version 15 rather than
replaying development migrations 1-14. Released unversioned 3.x import is confined
to one adapter verified against the v3.3.3 tag. Earlier development-v4 ledgers are
rejected without conversion; complete latest ledger-14 databases preserve their
data and receive only the current ledger entry. Read-only preflight rejects unknown
or inconsistent structures before opening them for mutation.

Structural validation checks columns, types, primary keys and foreign-key
declarations even for an already applied ledger. Restore and conversion also check
foreign-key rows. Conversion snapshots are taken while the writer lock is held,
so another writer cannot change the source between backup and conversion.
Released API address/model preferences are mapped, and local password availability
follows the released nonempty-hash behavior rather than inferred recovery-key state.

## Naming Semantics

SQL identifiers are storage contracts, not localized UI captions. Exact spelling
does not need to match Chinese, English or other UI labels. Relevant distinctions:

| Stored value | Current meaning |
| --- | --- |
| `users.username` / `username_key` | Login ID and its normalized lookup key |
| `users.display_name` | Editable account alias used for display, AI addressing and new reports |
| `worklog.d` / `start` / `end` | Record date and local clock boundaries |
| `worklog.note` | Individual time-record content, not the independent daily memo |
| `daily_notes.content` | Independent memo for an account and date |
| `worklog.break` | Historical deducted break hours, not independent break records |
| `work_type` / `work_type_category` | Classification ID and historical Work/Break/Leave accounting snapshot |
| `reports.type` | Daily, weekly or monthly report type |
| `reports.revision` / `report_revisions` | Current revision and saved versions of that report |
| `background_images.opacity` | Image opacity percentage; 0 is invisible and 100 is opaque |

Keep these distinctions explicit in adapters and documentation. Renaming SQL
columns merely to mirror a localized caption would require an additional data
conversion without correcting behavior, and would not improve multilingual UI
consistency.
