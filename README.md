# WorkLogger

WorkLogger is a local desktop application for recording working hours, keeping
daily notes, preparing reports, and reviewing work patterns. The application uses
Python, PySide6/Qt Widgets, and SQLite. Application metadata currently identifies
version 4.0.0; this does not imply that a matching release has been published.

## Capabilities

- Calendar-based manual entry and clock-in/clock-out controls, including breaks,
  overnight shifts, work types, notes, and public holidays.
- Daily, weekly, and monthly Markdown reports with editable templates and history.
- Monthly, quarterly, and annual analytics with CSV and PDF export.
- Local accounts, password recovery keys, remembered login, and administrator tools.
- English, Japanese, Korean, Simplified Chinese, and Traditional Chinese interfaces.
- Light and dark modes with preset or custom accent colors.
- CSV and iCalendar exchange, database backup and restore, and local model management.

Google/Microsoft sign-in is not connected. External AI is connected but disabled
by default; explicitly enable it and configure an HTTPS endpoint, model, and
securely stored credential. Offline rewriting uses the selected, verified
GGUF model when the optional native inference dependency, Local Model, and AI Assist
are enabled. Model loading and rewriting run on a background worker.
Account proxy settings route update checks, model downloads, and external AI calls.
See [integration availability](docs/integrations.md) for exact boundaries.

## Run From Source

The verified development environment uses Python 3.11.9 and PySide6 6.11.0 on
Windows. Other Python/Qt combinations require validation; installing a newer Qt
SDK alone does not change the Qt libraries used by PySide6.

From the repository root on Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts/i18n/i18n_compile.py
.\.venv\Scripts\python.exe -m worklogger.main
```

On macOS or Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/i18n/i18n_compile.py
.venv/bin/python -m worklogger.main
```

Native inference is a separate optional dependency in `requirements-ai.txt`.
Install an appropriate wheel or native build before using local rewriting.
See [local model setup](docs/local-models.md) and [development setup](docs/development.md).

Create an account on first use. The first registered account is an administrator;
there is no supplied administrator password. Keep the displayed recovery key in
a private location.

## Data and Upgrades

Source runs use `worklogger/worklog.db`. Packaged applications use `worklog.db`
beside the running executable. These are separate locations. The directory must
be writable. Back up through **Settings > Data** before replacing an installation
or changing dependencies. SQLite files and exported reports are not encrypted.

Startup applies database migrations. The activity-event naming migration preserves
existing records and creates a compatibility backup when older storage is found.
See [database compatibility](docs/database.md) before opening existing data with a
different application version.

## Documentation

Start with the [documentation index](docs/README.md).

- [User guide](docs/user-guide.md)
- [Configuration and file locations](docs/configuration.md)
- [Architecture](docs/architecture.md)
- [Development and testing](docs/development.md)
- [Packaging](docs/packaging.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Contributing](CONTRIBUTING.md), [security policy](SECURITY.md), and [changes](CHANGELOG.md)

## License

WorkLogger is distributed under the [repository license](LICENSE). Bundled fonts
and icons retain their own license notices. Model files have separate licenses
and are not bundled with the application.
