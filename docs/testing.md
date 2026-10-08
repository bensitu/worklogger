# Testing

## Scope

Keep tests that protect durable behavior: business rules, authorization, data
integrity, compatibility, error recovery, and workflows across application layers.
Use representative inputs and boundaries, and prefer observable results over
private widget structure, exact painter calls, or fixed pixel offsets.

Do not retain temporary diagnostic reproductions or duplicate checks for a single
incident. A defect can justify a lasting regression test when it protects a
general contract, such as preserving committed SQLite transactions or unsaved
editor content. Consolidate that coverage into the relevant behavior tests.

Run the smallest relevant tests first. Broaden coverage for shared behavior,
persistent data, or platform compatibility changes. Do not repeat the complete
suite or visual checks for every small change.

## Organization

The suite uses Python's `unittest`, in-memory repositories, temporary files and
databases, injected clocks and HTTP clients, and Qt's offscreen platform. It does
not require a live AI account or downloaded model.

| Directory | Coverage |
| --- | --- |
| `tests/domain/` | Time, work types, credentials, reports, analytics rules |
| `tests/app/` | Handlers, authorization, imports, AI context, model selection |
| `tests/infrastructure/` | SQLite, migrations, backups, credentials, adapters |
| `tests/presentation/` | View models, signals, controllers, jobs, user workflows |
| `tests/architecture/` | Dependency boundaries, application contracts, documentation |
| `tests/i18n/` | Language normalization, gettext extraction, catalog consistency |
| `tests/visual/` | Optional rendering and layout checks |

Default discovery includes functional Qt tests but excludes the visual modules,
whose filenames do not start with `test`. Functional Qt tests may instantiate
widgets or process events; they do not perform screenshot or layout matrices.
Catalog completeness is checked centrally rather than by repeating every
workflow in every language.
Window and authentication fixtures dispose their owned top-level widgets and
process deferred deletion before another test reapplies application-wide styles.
This prevents obsolete widgets and event filters from accumulating across tests.

## Commands

Compile translations before tests that inspect localized text. Run the modules
relevant to the change, for example:

```sh
python scripts/i18n/i18n_compile.py
python -m unittest tests.domain.test_worklog_rules -v
python -m unittest tests.infrastructure.test_data_portability_infrastructure -v
python -m unittest tests.presentation.test_auth_presentation -v
```

When broader verification is needed:

```sh
python -m unittest discover -s tests -t . -v
```

Qt state is process-global. If a combined run has order-dependent behavior, run
the affected modules separately to diagnose it. Do not treat a failed or
interrupted run as successful verification.

## Optional Visual Checks

Run visual checks when changing layouts, themes, fonts, images, display scaling,
localized UI text, or the Qt runtime, and when needed for a target-platform
release. Use representative language, theme, and window-size combinations rather
than repeating the full Cartesian product.

```sh
python -m unittest tests.visual.shell_checks -v
python -m unittest tests.visual.calendar_checks -v
python -m unittest tests.visual.reporting_checks -v
python -m unittest tests.visual.notes_checks -v
python -m unittest tests.visual.user_management_checks -v
```

To retain screenshots at additional scaling in PowerShell:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
$env:QT_SCALE_FACTOR = "1.5"
$env:WORKLOGGER_SCREENSHOTS = Join-Path $env:TEMP "worklogger-screenshots"
python -m unittest tests.visual.shell_checks tests.visual.calendar_checks tests.visual.reporting_checks tests.visual.notes_checks tests.visual.user_management_checks -v
```

Inspect text clipping, icon positions, calendar indicators, summary charts,
backgrounds, and scrolling. Offscreen rendering does not verify native dialogs,
tray integration, desktop focus behavior, window decorations, or packaged startup.
Check relevant native behavior on the target OS only when the change requires it.
Run interactive checks sequentially to avoid competing windows affecting focus.

Calendar checks use synthetic records by default. Optional
`WORKLOGGER_QA_DATABASE` opens an existing database read-only. Do not publish
screenshots containing private records.

## Storage Compatibility

Keep coverage for old schema names, preserved data, repeat migrations, failures,
and interrupted changes. Backup and restore tests must preserve committed data
that remains in SQLite's WAL; an integrity check alone cannot establish that the
latest records were copied. Run these tests when changing storage or migrations.

Use temporary file databases for multi-connection SQLite tests. Independent
`:memory:` connections do not emulate file-backed persistence.

## Documentation and Packaging

Documentation tests check local links, Python example syntax, and documented
table names. Review descriptions and commands manually as well.

For changes affecting translations or packaging, run the relevant checks:

```sh
python scripts/i18n/i18n_check.py
python scripts/build.py --check
git diff --check
```

Release verification requires a target-platform build and artifact startup checks.
See [packaging](packaging.md). Record skipped environments and known failures;
a Windows result does not verify macOS or Linux.
