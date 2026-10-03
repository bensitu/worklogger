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

An English command-line check can succeed while a localized check raises
`UnicodeEncodeError` in a CP932 terminal. The current `_safe_stdout` implementation
does not catch encoding failures. For diagnostic checks in PowerShell:

```powershell
$env:WORKLOGGER_LANG = "en_US"
python -m worklogger.main --smoke-startup
```

The packaged console executable may ignore Python encoding environment overrides.
This known limitation is separate from GUI text rendering and should not be
reported as a failed database refresh when only the final output write failed.

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

Check Settings > General > holiday display, the system timezone, the selected
month, and the installed `holidays`/`tzlocal` packages. Unmapped timezones use US
holidays. iCalendar import does not expand recurrence rules or convert timezones;
verify the original file before treating missing occurrences as lost work records.

## Unavailable Services

Disabled external login and AI controls are intentional in the standard runtime.
Selecting a local model or filling an external base URL does not connect a
generation service. A model list may be empty when no runtime catalog has been
configured. See [integration availability](integrations.md).

If proxy password entry is disabled, inspect system credential-store availability.
Do not work around it by storing passwords in a plain-text configuration. Saved
proxy preferences do not currently configure outgoing adapter traffic.

## Restore and Build Failures

Restore requires a valid SQLite file containing the current username. Close other
application processes and keep an independent backup. CSV and PDF exports cannot
be restored as databases.

Before building, close any executable running from `dist/` and move user data out
of generated output directories. Build on the target OS; signing, installers, and
release upload are separate operations. See [packaging](packaging.md).
