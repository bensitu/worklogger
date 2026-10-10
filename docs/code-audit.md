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

## Runtime Cleanup and Module Boundaries

Worklog and authentication repositories now assume the validated current schema.
Per-repository schema probing, daily-table fallback writes and optional-column
branches have been removed. Development automatic-recording draft conversion is
removed; an unsupported retained draft is reported for deliberate recovery or
discard rather than silently converted. Current timer serialization is unchanged.

The encryption adapter is named `FernetSecretBox`, matching its actual algorithm.
Released Fernet credential compatibility remains, including original machine-key
access; the early development custom stream-cipher reader and helpers are removed.
Invalid or unsupported ciphertext is retained rather than overwritten.

Settings-section state binding is separate from page composition. Recording
transitions/reminders and record transformation/undo prompts are separate from the
editor widget. Layout construction, signals, keyboard actions and translated UI
captions are preserved. Settings page executable lines decrease from 746 to 424;
the recording editor decreases from 769 to 578 without dropping functionality.

Owned callback wrapping prevents time-record and report jobs from touching a
deleted Qt widget. Boolean preference decoding is shared between UI and runtime.
Invalid stored numeric preferences use safe display defaults without modifying
their original values; new nonfinite values still cannot be saved. Invalid optional
offset timestamps no longer hide otherwise valid clock-only records and are not
rewritten on read.

Settings state reads request only known preference keys rather than loading
unrelated note drafts and history. Canonical repositories avoid repeated schema
queries. Unchanged global palettes/stylesheets are not reapplied; background
surface transitions explicitly force refresh of their descendant styling.

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

## Verification and Limits

The final complete suite passes 481 tests, including isolated runtime/import smoke
checks. Gettext consistency and undefined-name/unused-import checks pass. Opt-in
record-action and model-context layout checks pass across supported languages and
light/dark modes; background cover and opacity checks also pass.

Repeated native global stylesheet replacement caused an access violation during
the combined Qt suite. Applying an unchanged stylesheet is now skipped, while
explicit background-container transitions force the required refresh. A complete
rerun succeeds; this does not establish that every possible Qt/platform rendering
failure is eliminated.

No writable real-user database was used. Existing schema 14 is exercised through
isolated complete-schema fixtures. Earlier development files require their
compatible executable for manual export; the current application deliberately
does not convert them. No real paid AI requests, live provider authorization or
new packaged executable were used in this review. Existing original metadata and
unsupported encrypted values remain available for deliberate recovery.
