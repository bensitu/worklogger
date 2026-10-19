# WorkLogger

Track working time, keep daily notes, and turn your records into daily, weekly,
and monthly reports. WorkLogger brings your calendar, projects, and work summaries
together in a local-first desktop application.

Recording, notes, analytics, and template-based reports work without a hosted
service. AI assistance and personal cloud backups are optional.

[Download a release](https://github.com/bensitu/worklogger/releases/latest) |
[Try a development build](docs/packaging.md#trying-a-development-build) |
[User guide](docs/user-guide.md)

![WorkLogger calendar showing daily hours, classification colors, notes, and individual time records](docs/images/demo_1.png)

## What You Can Do

- **Record the day as it happened.** Enter time periods or start a timer for work
  and breaks. Add a lunch break inside a longer meeting with a replacement preview
  that preserves the surrounding work.
- **Find work without reconstructing it.** Organize records by project, work
  item, activity, and work mode. Search a month, year, or custom period.
- **Keep notes separate from hours.** Write date-specific memos with recoverable
  drafts and choose which notes may be included in reports or AI context.
- **Prepare reports from your records.** Edit localized daily, weekly, and monthly
  templates, keep saved versions, and export Markdown or XLSX/PDF timesheets.
- **Review hours and work patterns.** Compare months, quarters, and years; inspect
  overtime, actual attendance, planned work, and classification distributions.
- **Choose your own backup destination.** Keep local database backups or configure
  scheduled personal backups to WebDAV or S3-compatible storage, with client-side
  encryption enabled by default.

English, Japanese, Korean, Simplified Chinese, and Traditional Chinese interfaces
are included, with light/dark themes and an optional compact recording view.

**Version note:** this branch documents the 4.0.0 development version. Published
downloads may have a different interface and feature set. Read the release notes
and documentation at the downloaded version's tag. Back up existing data before
trying a development build; database upgrades do not provide a downgrade path.

## Download and Start

1. Open [Releases](https://github.com/bensitu/worklogger/releases/latest) and choose
   the application asset for your operating system. GitHub's **Source code**
   archives are not ready-to-run applications. Packaged applications do not need
   a separate Python installation.
2. Follow that release's extraction and launch instructions. Current development
   builds target Windows x64, Linux x64, and macOS Apple Silicon. Windows and Linux
   builds must keep their executable directory intact; do not move the executable
   away from its `_internal` folder.
3. Create a local account and store its recovery key privately. The first local
   account is an administrator. Managed installations may require an existing
   account and can disable registration or optional services.
4. In Calendar, choose a date, enter a time period and content, and save. Open
   Notes for a memo, Analytics for totals, or Reports to build a summary.

Development artifacts and published release assets are different downloads. See
[development build instructions](docs/packaging.md#trying-a-development-build)
for artifact selection, platform limits, and verification. Operating-system
warnings can appear for unsigned applications; verify the source and checksums
before deciding whether to run a download. Do not disable security software.

## Your Data and Optional Services

The primary database is stored on your device. Local accounts separate records
within that database; they are not a central company directory or a team
reporting server.
Google/Microsoft sign-in needs provider registration, and external AI and cloud
storage need their own configuration. None is required for local recording.

Find the active database under **Settings > Data > Local data location**. Use
**Backup Data** before moving data or upgrading. Source runs and packaged
applications use different data locations, so replacing an executable does not
replace or reset its database.

Local SQLite databases, local database backups, and ordinary exports are
unencrypted. Protect them with OS permissions and disk encryption. Personal
cloud backups use a separate backup passphrase by default; losing it prevents
recovery of encrypted versions. These backups contain only the current account's
portable data and do not provide automatic multi-device merging.

AI can use a selected local GGUF model or an explicitly enabled external service.
Model weights are downloaded or imported separately; they are not bundled.
Review sharing controls before sending content to an external service, and review
generated text before saving. Basic reporting does not require an AI model.

See [backup and recovery](docs/cloud-backups.md),
[security and privacy](docs/security.md), and
[startup troubleshooting](docs/troubleshooting.md#startup).

## Documentation

| Start Here | Details |
| --- | --- |
| [User guide](docs/user-guide.md) | Recording, notes, reports, and analytics |
| [Configuration](docs/configuration.md) | Work schedules, goals, deployment policies, and network settings |
| [Data formats](docs/data-formats.md) | CSV, iCalendar, Markdown, XLSX, and PDF |
| [Personal cloud backups](docs/cloud-backups.md) | Encryption, schedules, versions, and restoration |
| [Documentation index](docs/README.md) | All user and contributor guides |

## Run From Source

Use Python 3.11 through 3.14 and a virtual environment. From the repository root
on Windows:

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

These commands run the checked-out branch. To run a published version from source,
check out its tag first. Some Linux desktops need additional Qt system libraries;
see [platform setup](docs/development.md#setup).

Local AI is optional for source runs. Install its verified platform dependency
with `python scripts/install_native_dependencies.py` using the same virtual
environment. See [local model setup](docs/local-models.md). Contributors should
also read [development](docs/development.md) and [contributing](CONTRIBUTING.md).

## License

WorkLogger is distributed under the [GNU GPL v3 license](LICENSE). Fonts, icons,
and model files have their own licenses. Model weights are not bundled.
