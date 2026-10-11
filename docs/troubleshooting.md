# Troubleshooting

## Startup

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

Check the active account, selected date, and Settings > Data > Data location.
Source and packaged applications use different locations.

Do not delete a database to fix a schema or integrity error. Close the application,
preserve the database and any journal files or backups, and inspect a copy.
Unsupported layouts are rejected without resetting data. See [database handling](database.md).

Restore requires administrator permission and the same login ID/account ID in
the backup. It replaces the whole database and ends the session.
A `.pre_restore` file means replacement needs recovery; preserve it before taking
any action. CSV and PDF exports are not database backups.

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
