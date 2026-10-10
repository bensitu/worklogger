# Troubleshooting

## Collect Basic Information

Run from the same shell/interpreter used to start the application:

```sh
python -c "import sys, PySide6; from PySide6.QtCore import qVersion; print(sys.executable); print(sys.version); print(PySide6.__version__); print(qVersion())"
python -m worklogger.main --smoke-import
```

Include the application version, OS, reproduction steps, and sanitized error text
when reporting a defect. Never attach your database, session files, recovery keys,
or credentials to a public issue.

## Startup and Dependencies

Closing the login, registration, or password-reset window without signing in is
a normal cancellation. WorkLogger exits with code `0` and prints no startup
failure. Closing the login window after logging out behaves the same way. Actual
startup failures still return code `1` and display a translated error message.

User-facing errors use translated descriptions rather than internal error codes
or raw exception text. Logs retain diagnostic codes for troubleshooting. Cancelling
an operation is not logged as an error and does not trigger an error dialog.

If a module is missing, install dependencies using the same interpreter, preferably
inside the documented virtual environment. `python -m pip` avoids selecting an
unrelated pip executable. A separately installed Qt SDK does not change the Qt
runtime bundled with PySide6.

If PyInstaller reports missing native libraries, rebuild from the intended
environment and inspect its warnings. Do not copy individual DLLs from unrelated
applications or mix PySide6 with another Qt binding's libraries.

The `llama-cpp-python` dependency may require a native toolchain. For desktop work
without connected inference, use the [desktop-only dependency setup](development.md).

## Fonts, Images, and Layout

Check that the bundled fonts, WebP login image, SVG icons, and platform icons exist
in the source or packaged resources. Run `python scripts/build.py --check` before
building. Do not reintroduce AVIF assets.

For font-size warnings or clipped text, record the Qt version, language, display
scaling, and affected control. Compare against the verified environment and run
the visual tests. Do not suppress Qt warnings instead of identifying their source.

Qt 6.11.0's Windows 11 style assumes point-sized fonts when drawing menu
indicators and combo-box popups. Pixel-sized QSS fonts can therefore produce
`QFont::setPointSize: Point size <= 0 (-1)` when a window or dropdown first
appears. The style caches some font calculations, so opening another dropdown
in the same process may not repeat the warning.

Application initialization replaces the Windows 11 base style with Qt's Fusion
style before applying QSS. This covers business controls and Qt-generated
dropdowns, including the non-native file dialog. Existing palettes, fonts, QSS,
and native file dialogs are retained; macOS/Linux and other Windows base styles
are unchanged. No Qt warning handler is installed by this compatibility logic.
When investigating a rendering problem, use the optional layout checks:

```sh
python -m unittest tests.visual.shell_checks -v
```

These checks use synthetic records and offscreen rendering. For a native font
warning, also reproduce the affected control on the target OS in a fresh process
with a temporary database and isolated preferences. Check startup, login, and the
affected popup while collecting Qt messages. Such diagnostic reproductions are
not part of routine test runs. See [testing](testing.md).

Remove `QT_QPA_PLATFORM=offscreen` from an interactive shell if the application
appears to run without a visible window. Check the system tray/menu bar when
residency is enabled.

## Language

Compile the catalogs with `python scripts/i18n/i18n_compile.py`. An absent `.mo`
file results in English fallback even when the source `.po` file is translated.
Review `WORKLOGGER_LANG`, the native pre-login preference, and the signed-in
account's language. Restart or log in again after changing the language.

The dropdown uses each language's native name. Holiday names come from the holiday
data library and are not necessarily in the application language.

## Console Encoding

Command-line output replaces characters that the terminal encoding cannot
represent. This does not change localized GUI text or operation results.
For diagnostic checks in PowerShell:

```powershell
$env:WORKLOGGER_LANG = "en_US"
python -m worklogger.main --smoke-startup
```

Desktop startup failures also display a translated dialog when a graphical
platform is available, including packaged applications without a console.
Starting a second instance displays an informational message and leaves the
running instance and its data unchanged.

## Missing Records or Login Failures

Confirm which database path is active. Source and packaged runs use different
locations; moving the working directory does not move the source database.
Check the selected account and date before importing data again.

Do not delete the database to resolve a schema error. Preserve it and any `.bak_*`
files. Older authentication storage is migrated at startup. Activity-name
conflicts deliberately stop migration rather than combining populated tables;
see [compatibility behavior](database.md).

Repeated invalid credentials cause a temporary lockout. Use the correct account
and wait for the lockout interval. Password recovery requires the saved recovery
key or an authorized administrator workflow, not manual editing of credential rows.

## Holidays and Calendar Imports

Check Settings > General > holiday display, the country/state selection, the system
timezone, the selected month, and the installed `holidays`/`tzlocal`/`tzdata` packages.
System region does not guess a country for unknown or country-neutral timezones.
iCalendar import converts UTC and named timezones, expands finite recurrence, and
rejects recurrence without a count or end date. Verify the original file before
treating missing occurrences as lost work records.

## Unavailable Services

External login remains disconnected. External rewriting requires explicit Use
external model, AI Assist, an HTTPS API base address, a model identifier, and a
securely saved API key. Test checks with sample text only. Disable external
processing to select local processing; there is no silent remote fallback.
Local rewriting
requires the optional native dependency, a verified selected model, Local Model,
and AI Assist. Check the service message under Settings > AI; a downloaded file
must be selected with Use model. After installing `requirements-ai.txt` into the
Python environment used to start WorkLogger, restart it. Packaged applications
must be built with native inference included. See [local models](local-models.md).

Loading is lazy, so the first rewrite takes longer. An out-of-memory/load failure
does not change the draft; select a smaller model. A native message that configured
context is lower than training context describes the intentional 8,192-token bound,
not a damaged model. Oversized content must be shortened; timeouts can be retried
with less text or a smaller model. Avatar upload rejects unsupported, invalid,
oversized, or excessively high-resolution images without changing the saved picture.

If proxy password entry is disabled, inspect system credential-store availability.
Do not work around it by storing passwords in a plain-text configuration. Saved
proxy preferences configure subsequent adapter requests. Use a host or HTTP proxy
address and port; unsupported proxy schemes/authentication must be handled by a
separate supported network service, not by disabling certificate checks.

When encrypted credentials cannot be read after moving a database to a new device,
re-enter the credential in Settings. Do not delete a damaged machine-key file to
make the warning disappear; preserve it and seek recovery first.

## Restore and Build Failures

Confirmed database corruption stops startup without replacing any files. With the
application closed, preserve the main database and its `-wal`/`-shm` sidecars
together. Validate and upgrade a known-good backup into a new destination using
`python scripts/upgrade_database.py <backup> <new-destination>`. Keep the original
files outside the active database directory, then use the validated copy at the
documented database location. Never copy a live main database without its WAL or
use automatic empty-database creation as a recovery substitute.

Restore requires administrator permission and a compatible SQLite file containing
the current username with the same account ID. Successful restore ends the current
session. A retained `.pre_restore` file blocks replacement until it is recovered;
never delete it without preserving its contents. Close other
application processes and keep an independent backup. CSV and PDF exports cannot
be restored as databases.

Before building, close any executable running from `dist/` and move user data out
of generated output directories. Build on the target OS; signing, installers, and
release upload are separate operations. See [packaging](packaging.md).
