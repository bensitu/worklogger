# Desktop UI Acceptance

## Runtime Assets

The supplied avatar and login image have been converted to WebP because the
supported Qt image stack does not reliably decode AVIF. Per the project owner's
instruction, AVIF files are not retained in the repository or release bundle.

The application uses `worklogger.ico` on Windows, `worklogger.icns` on macOS,
and `worklogger.webp` on Linux. The About image uses WebP on every platform.
Bundled Lucide UI icons follow the application palette; their license is in
`worklogger/assets/icons/ui/LICENSE`. Noto fonts are bundled for all five languages.

## Build

Build on each target platform using that platform's Python and Qt installation:

```text
python -m pip install -r requirements.txt -r requirements-build.txt
python scripts/build.py --check
python scripts/build.py
```

`WorkLogger.spec` produces a one-folder distribution and a macOS app bundle.
It includes the Qt assets, QSS, compiled gettext catalogs, dynamic holidays and
keyring backends, timezone resources, and available local inference libraries.
Built-in Markdown templates are Python modules collected with the application.
Local databases, credentials, custom templates, downloaded models and local
configuration are not release resources.

Use `python scripts/build.py --console` for executable smoke checks. Generated
outputs are under `dist/WorkLogger` and are ignored by Git. On Windows:

```text
dist/WorkLogger/WorkLogger.exe --smoke-import
dist/WorkLogger/WorkLogger.exe --smoke-runtime
dist/WorkLogger/WorkLogger.exe --smoke-startup
```

The Windows build isolates its DLL search path from unrelated tools, such as
Poppler, to prevent incompatible ICU libraries from entering the Qt bundle.

## Verification

```text
python -m unittest discover
python -m pytest -q
python scripts/i18n/i18n_check.py
python worklogger/main.py --smoke-import
python -m worklogger.main --smoke-runtime
python worklogger/main.py --smoke-startup
```

Set `QT_QPA_PLATFORM=offscreen` for automated visual checks. To retain screenshots,
set `WORKLOGGER_SCREENSHOTS` to a test output directory before running
`python -m unittest tests.presentation.test_ui_layout`. Fixtures use in-memory
data, never the user's database. The test exercises all routes and settings
categories in five languages, two themes, and both supported window sizes.

Verified on Windows on 2026-10-03:

- `unittest`: 250 tests passed.
- `pytest`: 250 tests and 41 subtests passed.
- Catalog consistency, nonempty translations and format fields passed.
- Source and console-enabled Windows distribution passed all three smoke checks.
- Screenshot review covered login, shell routes and settings categories. Login
  field icons also have automated containment and vertical alignment assertions.

## Settings Refinement

All seven settings categories were compared with the supplied prototypes.
Appearance uses equally sized dropdowns and a live custom-color swatch. General
uses vertically stacked labels and controls. Data uses paired CSV and backup
actions, icons, and a reminder based on the actual last successful backup.
Network uses wider address fields, strict port validation, and an inline password
visibility icon. Account uses read-only fields and displays the login username
as Current ID, not the internal SQLite primary key. About uses a centered,
unframed layout with separators, the full repository link, and inline update
status. Disabled controls and icons use the disabled palette.

Logout exists only in Settings / Account, including the minimal-mode settings
dialog. Existing unsaved-change confirmation and the application's logout signal
are retained. The minimal-mode dialog disconnects its logout callback and releases
the dialog after closing; logout does not refresh the old session's window.

Download and import actions open the existing local-model workflow directly.
Inventory verification, selection and deletion run through the background job
runner; pending operations prevent unsafe dialog closure. Enabling local models
does not falsely report availability when no verified model has been selected.

Settings layout checks cover five languages, both themes, both supported window
sizes and 150% scaling. Long navigation labels wrap without clipping, and all
settings categories are checked for horizontal overflow and button-text fit.
Screenshots also cover a real runtime with a temporary administrator database
and an available Windows credential store. The user's business database is not
used by these settings checks.

### Stored Settings Migration

No database schema change is required. The optional `last_backup_at` setting is
written as a UTC ISO timestamp only after a successful backup. Older databases
without it display "No backup recorded" rather than an invented backup age.

Proxy passwords use an OS credential store through `keyring`, scoped by the
resolved database path and user ID. Only supported OS backends are accepted;
there is no plaintext fallback. Password whitespace is preserved. On settings
load, an old SQLite password is removed only after secure storage succeeds or
an existing secure credential is found. If secure storage or database cleanup
fails, the operation reports failure and retains the existing data for retry.
An unavailable credential store disables new password entry without preventing
other settings from loading. Empty passwords remove the secure credential.

OS credentials are not copied into database backups and do not automatically
follow a database moved to a different path or machine. Previous backup files
are not rewritten and may still contain legacy plaintext settings; protect
those files accordingly. Successful Windows credential save/read/delete and
failure-path regression checks were performed without modifying user credentials.

## Calendar Refinement

The calendar follows `Prototype-calendar.png` with a seven-column month grid,
blank adjacent-month positions, weekend headers, full-height work-type markers,
and a moon icon for overnight entries. Event counts and overnight markers have
separate positions. Weekly totals remain available in the view state and legacy
widget mode but do not add an eighth column to the shell.

The sidebar uses a circular avatar without a product label above it. The right
panel uses vertically stacked fields, a collapsible notes editor, and separately
scrollable schedule items. Notes, automatic recording, save and selected-day
refresh remain available. Hidden input tabs no longer impose their minimum width
on the active form.

Calendar layout checks cover five languages, two themes, both window sizes and
150% scaling. To check an imported May 2026 dataset, set `WORKLOGGER_QA_DATABASE`
to its database path and run `tests.presentation.test_calendar_layout`. This
opens SQLite in read-only mode and copies records into in-memory fixtures; the
test's save operations do not touch the original database. The imported test
database's file hash was unchanged after verification.

## Legacy Authentication Migration

Schema version 2 repairs legacy `users.salt` databases before authentication.
Before altering an existing authentication table, SQLite's backup API writes a
standalone `worklog.db.bak_auth_<UTC timestamp>_<unique ID>` beside the database,
including committed WAL data. Backup failure aborts the migration.

The migration renames `salt` to `password_salt` and adds
`must_change_password INTEGER NOT NULL DEFAULT 0` where missing. Existing hashes,
salts, user IDs, administrator flags, recovery keys, sessions and business records
are retained; passwords are not reset. Schema changes and the version record are
transactional, and repeated startup does not repeat the migration or backup.
Missing salt data fails migration instead of recreating credentials. Normal
password verification can still upgrade an old PBKDF2 hash after a correct login.

Regression checks cover migration, rollback, backup failure, committed WAL data,
legacy hash verification, registration, password changes, recovery-key reset and
an administrator login through the real login dialog into the desktop shell.
An isolated snapshot of the existing database passed credential and all-business-
table preservation, integrity, foreign-key and idempotency checks. The original
database remained unchanged; the next normal startup performs its migration.

The reported `QFont::setPointSize` warning was not reproduced in the login flow
with either the offscreen or native Windows Qt backend (Python 3.11.9, PySide6
6.11.0). No warning suppression or speculative font changes were introduced.

## Deliberate Limits

- External model credentials and testing remain disabled until secure storage
  and a configured backend are supplied. There is no fake connection success.
- AI chat and report rewrite do not submit requests without a configured backend.
  Pending chat, rewrite, backup and restore jobs protect their containing UI
  against unsafe navigation or closure.
- Proxy fields persist configuration only, as requested in this milestone.
- Calendar clearing is disabled with an explanatory tooltip.
- Language changes take effect after restart. Other appearance and calendar
  settings update the shell immediately without overwriting entry drafts.
- Platform-specific packaging is not equivalent to native acceptance testing;
  macOS and Linux releases still require testing on those operating systems.
