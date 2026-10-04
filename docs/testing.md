# Testing

## Organization

The suite uses Python's `unittest`. Test modules use in-memory fake repositories,
temporary files/databases, injected clocks and HTTP clients, and Qt's offscreen
platform. No live AI account or downloaded model is required for the standard suite.

| Directory | Coverage |
| --- | --- |
| `tests/domain/` | Time, work types, credentials, reports, analytics rules |
| `tests/app/` | Handler behavior, authorization, imports, AI context, model selection |
| `tests/infrastructure/` | SQLite, schema compatibility, backups, credentials, files, adapters |
| `tests/presentation/` | View models, dialogs, controllers, jobs, layout, fonts, icons, workflows |
| `tests/architecture/` | Dependency boundaries, names, application contracts, documentation |
| `tests/i18n/` | Language normalization, gettext extraction and catalog consistency |

## Commands

Compile translations before tests that inspect localized text:

```sh
python scripts/i18n/i18n_compile.py
python scripts/i18n/i18n_check.py
python -m unittest tests.domain.test_worklog_rules -v
python -m unittest tests.infrastructure.test_activity_schema_migration -v
python -m unittest tests.presentation.test_auth_presentation -v
python -m unittest tests.presentation.test_native_fonts -v
python -m unittest tests.presentation.test_native_dropdowns -v
python -m unittest discover -s tests -t . -v
```

The native font check starts an isolated Windows subprocess with the `windows11`
style before application initialization. It signs in through the login dialog,
shows the main window, and opens Add Entry and export menus, input context menus,
nested menus, available tray menus, and every settings category. It checks login
languages and light/dark themes for Qt font warnings. It is skipped on other
platforms; headless widget
tests alone do not exercise Windows style drawing.

The native dropdown check starts each of the nine business combo boxes and both
Qt file-dialog dropdowns in independent processes to avoid the Windows style's
font-metric cache masking a failure. It opens and cancels each popup in five
languages and light/dark themes and verifies that cancellation preserves the
selection. Repeat with `QT_SCALE_FACTOR=1.5` to check additional display scaling;
the native platform scale is multiplied by this factor.
Run native GUI checks sequentially: competing native windows can dismiss each
other's popups through focus changes. `WORKLOGGER_SCREENSHOTS` also enables
dropdown popup captures.

For explicit headless execution on PowerShell:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -m unittest tests.presentation.test_ui_layout -v
```

For a POSIX shell:

```sh
QT_QPA_PLATFORM=offscreen python -m unittest tests.presentation.test_ui_layout -v
```

Qt state is process-global. Larger combined runs can become slower as widgets,
styles, and queued events accumulate. When diagnosing order dependence, run the
affected modules in separate processes as well as together. A failed or interrupted
run is not a successful verification.

## Visual Checks

Layout tests cover all five languages, light/dark palettes, multiple window sizes,
and important geometry relationships. To save screenshots at 150% scaling:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
$env:QT_SCALE_FACTOR = "1.5"
$env:WORKLOGGER_SCREENSHOTS = Join-Path $env:TEMP "worklogger-screenshots"
python -m unittest tests.presentation.test_ui_layout tests.presentation.test_calendar_layout -v
```

Inspect screenshots for text clipping, icon position, incorrect background fills,
calendar indicators, and horizontal scrolling. Repeat at normal scaling and on
real target systems. Offscreen rendering does not verify a native tray, OS color
management, platform dialogs, window decorations, or a packaged application's
interaction with the desktop.

The optional `WORKLOGGER_QA_DATABASE` calendar fixture opens a database read-only.
It is not required; ordinary tests generate synthetic records. Do not attach
screenshots from private records to public issues.

## Storage Compatibility Checks

The authentication and activity migration tests cover old names, preserved data,
backup content, repeat execution, backup failure, and interrupted changes.
Activity storage tests also check unversioned databases and conflicting populated
tables. Run the backup/restore tests when modifying migrations, since restore
invokes the migration runner.

Use temporary file databases for multi-connection SQLite tests. A fresh `:memory:`
connection is a different database; it does not emulate the connection factory's
file-backed persistence behavior.

## Documentation Checks

Documentation tests check local links, required guides, Python example syntax,
and the documented current table names. These complement manual review of behavior
and commands; they do not certify every English statement or external URL.

## Build Verification

```sh
python scripts/build.py --check
git diff --check
```

A release verification also requires a target-platform build and artifact startup
checks. See [packaging](packaging.md). Record skipped environments and known failures
explicitly; never imply that a Windows result verifies macOS or Linux.
