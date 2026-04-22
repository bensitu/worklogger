# WorkLogger

![License](https://img.shields.io/badge/license-GPLv3-blue)
![Python](https://img.shields.io/badge/python-3.9+-green)

WorkLogger is a privacy-first desktop app for tracking work hours, notes, quick logs, reminders, and AI-assisted reports in multiple languages.

![WorkLogger preview](docs/images/demo_1.jpg)

## Highlights

- Desktop-first PySide6 application with local SQLite storage
- Flexible time tracking with Manual Input and Auto Record modes
- Overnight-shift-aware calculations with work type and leave classification
- AI-assisted note and report generation with external API providers and local model fallback
- Built-in local model management (download, resume, verify, switch, import `.gguf`)
- Template-driven daily/weekly/monthly writing with custom template support
- Calendar + Quick Log context integration for richer reports
- Monthly/quarterly/annual analytics with CSV and PDF export
- Multi-language UI (English, Japanese, Korean, Simplified Chinese, Traditional Chinese)
- Cross-platform desktop behavior (Windows tray icon, macOS menu bar icon)

## Download

Release packages are published through GitHub Releases:

- Windows: `WorkLogger.exe`
- macOS: `WorkLogger.app.zip`

Build outputs are generated into the `dist/` directory.

## Run From Source

### Requirements

- Python 3.10+
- pip

### Install

```bash
pip install -r requirements.txt
```

### Start the app

```bash
python -m worklogger.main
```

## Build

### Windows

```powershell
WorkLogger_build.bat
```

### macOS / Linux

```bash
./WorkLogger_build.sh
```

Both scripts use `worklogger.spec`. The generated executable and packaged artifacts are expected in `dist/`. If you create a macOS App, place the final `.app` file in `dist/` as well.
`WorkLogger_build.sh` re-signs the merged universal app before zipping. By default it uses ad-hoc signing (`CODESIGN_IDENTITY=-`) for integrity.

### macOS install note (no Apple Developer ID)

If the app is not Developer ID signed + notarized, macOS Gatekeeper may show "Apple cannot verify".
Users can still install by removing the quarantine flag after copying the app:

```bash
mv ~/Downloads/WorkLogger.app /Applications/WorkLogger.app
xattr -dr com.apple.quarantine /Applications/WorkLogger.app
open /Applications/WorkLogger.app
```

## i18n Workflow

WorkLogger uses gettext catalogs under `worklogger/locales`.

- Template extraction (`messages.pot`):

```bash
python scripts/i18n/i18n_extract.py
```

- Sync language catalogs (`messages.po`):

```bash
python scripts/i18n/i18n_sync.py
```

- Compile binary catalogs (`messages.mo`):

```bash
python scripts/i18n/i18n_compile.py
```

- CI/local validation:

```bash
python scripts/i18n/i18n_check.py
```

`messages.mo` files are generated artifacts and ignored by git. Missing translations automatically fall back to English at runtime.

## Project Layout

```text
WorkLogger_build.bat          Windows build entrypoint
WorkLogger_build.sh           macOS universal build entrypoint
worklogger.spec               Shared PyInstaller specification
scripts/                      Build helpers and i18n automation scripts
worklogger/
  assets/        Application icons
  config/        Constants and themes
  core/          Time parsing and calculation logic
  data/          SQLite persistence layer
  locales/       gettext catalogs (.po/.mo)
  models/        Local models
  services/      AI, export, and calendar services
  stores/        Setting, state
  templates/     Built-in and custom report templates
  ui/            Main window, dialogs, and widgets
  utils/         Shared helpers (including i18n runtime)
docs/
  images/        README and documentation images
dist/            Local build output directory
```

## Data Storage

WorkLogger stores data in a local SQLite database named `worklog.db`. In packaged builds, the database is created next to the executable. User-created custom templates and local app settings are also stored locally.

## Current Features

- Calendar-centered daily workflow with per-day totals, overtime, holidays, note markers, and overnight indicators
- Manual Input and Auto Record tabs for start/end/break capture with input validation and unsaved-change protection
- Work types: normal, remote, business trip, paid leave, comp leave, and sick leave
- Quick Log editor with start/end time support, inline edit/delete, and report/note integration
- Note editor with template insertion, Quick Log insertion, and AI rewrite assistance
- Weekly and monthly report generation with template picker, AI enhancement/regeneration, copy, and Markdown export
- Analytics dialog with monthly/quarterly/annual charts and export to CSV/PDF
- Data portability: CSV import/export, `.ics` calendar import/export, and calendar event merge into notes/reports
- AI provider settings with connectivity test, primary/secondary provider routing, and status-rich progress dialogs
- Local model controls: enable/disable switch, model selection, resumable download, hash verification, deletion, and `.gguf` import
- Secure API key handling via OS keychain with encrypted local fallback
- Appearance and behavior controls for theme, dark mode, language, week start, holiday display, note reminders, and residency icon mode

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## Security

If you find a security issue, please follow the instructions in [SECURITY.md](SECURITY.md).

## License

This project is licensed under [GPL-3.0-or-later](LICENSE).
