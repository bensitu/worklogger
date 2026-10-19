# Troubleshooting

## Saved Timer Recovery

An unreadable saved timer blocks time-record writes to avoid creating overlaps
with work that may still be in progress. Open automatic recording and choose
**Discard timer** only if the saved timer is no longer needed. Confirmation clears
the saved timer without creating or deleting time records. A temporary settings
read failure can be retried; a valid timer created by another window is protected
by the normal concurrent-change check. Saved records are not silently skipped
when invalid stored data prevents a range from loading; restore a verified backup
or retain a copy of the database before requesting recovery assistance.

## Startup

Uncaught application and background-thread failures are recorded in the rotating
diagnostic log. Exception records include types and source locations rather than
arbitrary exception messages. Review logs for private data before sharing them.

Run with the same Python interpreter used to install dependencies. Use
`python -m pip` rather than an unrelated pip executable. Compile translations for
source runs:

```sh
python scripts/i18n/i18n_compile.py
python -m worklogger.main --smoke-import
```

A separately installed Qt SDK does not replace PySide6's Qt runtime. Do not mix
Qt bindings or copy DLLs from other applications into a package.

Closing login without signing in is normal cancellation. A second desktop instance
does not replace the running instance. If no window appears, check tray/menu-bar
residency and remove `QT_QPA_PLATFORM=offscreen` from an interactive environment.

## Missing Data or Database Errors

Check the active account, selected date, and Settings > Data > Local data location.
Source and packaged applications use different locations.

Do not delete a database to fix a schema or integrity error. Close the application,
preserve the database and any journal files or backups, and inspect a copy.
Unsupported layouts are rejected without resetting data. See [database handling](database.md).

If database validation prevents startup, the recovery window groups the read-only,
copyable database path with **Open data directory**. Opening the directory does
not change files. Under **Choose one action**, select one of the following:

- **Restore from database backup**: choose **Choose backup...**, select a local
  SQLite backup, and confirm replacement. WorkLogger checks a separate copy,
  retains the existing files, and opens sign-in for an account from the backup.
- **Keep files and create a new database**: choose **Create new database...**
  and confirm. WorkLogger retains the existing files and opens new account setup.
  Previous records are not imported.
- **Exit without making changes**: choose **Exit** to close WorkLogger and seek
  help or use a compatible application version. This is the default selection.

Selecting an option alone does not change the database. Cancelling backup
selection or confirmation also leaves the database unchanged.

Restore accepts a compatible SQLite database backup, including a supported
v3.3.3 database. It validates and upgrades a separate copy before replacement,
including committed data in the backup's WAL. A personal cloud backup archive is
not a SQLite database and cannot be restored through this window. After recovery,
sign in with an account from the backup. Creating a new database opens account
setup instead; it does not import earlier records. Deployments that disable
self-registration also disable this creation action; contact the administrator.

Both actions retain the previous database, WAL/SHM files, and any interrupted
restore files together in a unique subdirectory of **database-recovery**, beside
the active database. These retained originals are not automatically rotated.
Keep this directory until the recovered data has been checked. Other backups,
models, and device credentials are not deleted. If replacement is interrupted,
`worklog.db.startup-recovery.json` blocks automatic database initialization; the
next launch returns to recovery. Preserve this marker and all retained files.
Do not delete the marker as a substitute for recovery.

Packaged applications use the OS user's application-local data directory, not
normally the executable directory. Changing or extracting the executable again
does not replace its active database. A prepared new database prevents automatic
reimport of a legacy database located beside the executable.

Restore requires administrator permission and the same login ID/account ID in
the backup. It replaces the whole database and ends the session.
A `.pre_restore` file means replacement needs recovery; preserve it before taking
any action. CSV and PDF exports are not database backups.

If an invalid saved timer prevents recording, review its state in Auto Record and
use Discard timer deliberately. The invalid state is retained until that action;
do not remove unrelated work records or settings to repair it.

## Sign-In and Credentials

Wait for a temporary lockout to expire or use an authorized administrator reset.
Recovery requires the saved recovery key; editing credential rows is not recovery.

For provider sign-in, check application registration, tenant/audience, consent,
and the network. Configure the provider from its settings icon.
See [browser sign-in](identity-signin.md).

After moving data to a different machine or directory, re-enter credentials that
cannot be decrypted or found in the new credential namespace.
Do not remove machine-key files to silence an error.
See [security](security.md).

## AI and Models

For local processing, check AI Assist, Local Model, the optional native dependency,
and a verified selected model. Downloading alone is insufficient.
Restart after installing native dependencies.

For external processing, check explicit enablement, HTTPS base address, model ID,
and the saved API key. Test sends sample text. Disable external processing when
you want local processing; failures do not silently fall back.

The first local request loads the model. For memory failures, reduce Runtime
context or select a smaller file. A context-capacity warning is not by itself a
failure. Oversized input must be shortened. See [local models](local-models.md).

## Network

An enabled proxy needs a host, port, and valid authentication if required.
Invalid settings are not bypassed. If password editing is disabled, check the OS
credential-store backend instead of using plaintext storage.

The browser and pre-login provider requests have network settings separate from
the authenticated account proxy. Keep TLS verification enabled.

## Appearance and Language

For background images, check the deployment flag and the account switch.
An enabled switch with no image keeps the normal theme. Upload must satisfy the
size, resolution, and format limits in [configuration](configuration.md).

For missing translations, compile the catalogs and review `WORKLOGGER_LANG` and
account language. Restart or sign in again. Holiday names come from the holiday
data source and may differ from the interface language.

For clipped text or rendering warnings, report the language, display scaling,
Qt/PySide6 versions, and affected control. Contributors should use the optional
checks in [testing](testing.md). Do not suppress warnings without finding their cause.

## Imports and Exports

Review the preview before importing. Duplicate or overlapping periods and
unsupported calendar recurrences are rejected. Imported events do not count as
worked time. Check the selected account/date range and [data formats](data-formats.md).

Choose a writable export destination. If export fails, existing files are retained.
Large tables or text may exceed format limits. Backup/restore uses SQLite files,
not report, analytics, or timesheet exports.

## Reporting a Problem

Include application/OS versions, steps, expected and actual behavior, and sanitized
error text. Source users can collect interpreter information:

```sh
python -c "import sys, PySide6; from PySide6.QtCore import qVersion; print(sys.version); print(PySide6.__version__); print(qVersion())"
```

Review logs before sharing them. Never publish databases, recovery keys, session
files, private images, or API/proxy credentials. Report sensitive issues through
[the security policy](../SECURITY.md).
