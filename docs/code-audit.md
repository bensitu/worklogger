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
