# Testing

## Durable Coverage

Keep tests for business rules, authorization, data integrity, compatibility,
error recovery, and workflows across layers. Prefer observable behavior over
private painter calls or fixed pixel offsets. A regression test should protect a
general contract, not preserve a one-off diagnostic exercise.

Use synthetic accounts, injected clocks/transports, and temporary files.
Never mutate a personal database or send paid provider requests in the default suite.

| Directory | Coverage |
| --- | --- |
| `tests/domain/` | Calculation and validation rules |
| `tests/app/` | Use cases and service contracts |
| `tests/infrastructure/` | Persistence, credentials, files, networking |
| `tests/presentation/` | View models, signals, workflows, jobs |
| `tests/architecture/` | Layer boundaries and public documentation |
| `tests/i18n/` | Catalog extraction and localization |
| `tests/visual/` | Opt-in layout/rendering checks |

## Running Tests

Compile catalogs before checks that inspect localized text:

```sh
python scripts/i18n/i18n_compile.py
python -m unittest tests.domain.test_worklog_rules -v
python -m unittest tests.infrastructure.test_database_schema -v
```

For broader verification:

```sh
python -m unittest discover -s tests -t . -v
python scripts/i18n/i18n_check.py
python scripts/build.py --check
git diff --check
```

Default discovery includes functional Qt tests but excludes visual modules,
whose names do not begin with `test`. Run the smallest relevant scope first.

## Qt and Visual Checks

Qt application state is process-global. Dispose owned widgets, process deferred
deletion, and restore themes/language in fixtures. Keep native interactive checks
sequential. Use temporary file databases when multiple connections must share data.

Run optional visual checks for changes to layout, themes, fonts, images,
translations, or display scaling:

```sh
python -m unittest tests.visual.calendar_checks -v
python -m unittest tests.visual.report_settings_checks -v
python -m unittest tests.visual.background_images_checks -v
```

To retain screenshots:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
$env:QT_SCALE_FACTOR = "1.5"
$env:WORKLOGGER_SCREENSHOTS = Join-Path $env:TEMP "worklogger-screenshots"
python -m unittest tests.visual.shell_checks -v
```

Inspect text fit, focus, button states, scrolling, and imagery with representative
languages/themes/window sizes. Offscreen rendering does not establish native
dialog, tray, credential-store, or packaged behavior; check those on the target OS.

## Persistence and Distribution

Migration tests use realistic supported layouts and verify IDs, credentials,
content, rollback, and repeat startup. Backup tests include committed WAL data.
Integrity checks alone do not prove the newest records were copied.

Documentation checks cover local links, Python examples, table names, English
prose, and machine-path hygiene. Review procedures against code as well.

Executable import/startup/workflow checks use isolated data.
See [packaging](packaging.md). Record what a contribution tested and what it skipped
in its review, rather than adding a dated result log to the public guides.
