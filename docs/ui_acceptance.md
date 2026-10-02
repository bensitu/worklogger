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

Verified on Windows on 2026-10-02:

- `unittest`: 222 tests passed.
- `pytest`: 222 tests and 35 subtests passed.
- Catalog consistency, nonempty translations and format fields passed.
- Source and console-enabled Windows distribution passed all three smoke checks.
- Screenshot review covered login, shell routes and settings categories. Login
  field icons also have automated containment and vertical alignment assertions.

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
