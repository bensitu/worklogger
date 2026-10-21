# WorkLogger

Remember what you worked on, see where your time went, and prepare reports
without starting from a blank page. WorkLogger brings your working hours,
daily notes, projects, and reports together on your desktop.

Record time and prepare reports locally, with no hosted service required.
AI assistance and personal cloud backups are optional, so you can use only
what you need.

📥 **[Download WorkLogger](https://github.com/bensitu/worklogger/releases/latest)**

📖 [Explore the user guide](docs/user-guide.md)

![WorkLogger calendar showing daily hours, classification colors, notes, and individual time records](docs/images/demo_1.png)

## What You Can Do

- **Record the day as it happens.** Start a timer for work or breaks, or enter
  time afterward. Keep leave records in the same calendar.
- **Correct a record without re-entering the whole day.** Add a lunch break
  inside a longer meeting, preview what will change, and keep the surrounding
  work. Split or merge periods and undo eligible changes.
- **Find the work you need to remember.** Organize time by project, work item,
  activity, or work arrangement. Search a month, year, or custom period.
- **Keep the details, not just the hours.** Write daily notes with recoverable
  drafts. Choose which notes belong in reports or may be shared with AI.
- **Spend less time putting reports together.** Build daily, weekly, and monthly
  drafts from your records, adjust the templates, and recover saved versions.
  Share reports as Markdown or export XLSX/PDF timesheets.
- **See where your time goes.** Review hours, overtime, and project breakdowns.
  Compare actual attendance with your work plan and set a schedule-based or
  custom hours goal.
- **Keep a backup where you choose.** Save a local database backup or schedule
  personal backups to your own WebDAV or S3-compatible storage, with encryption
  enabled by default for cloud backups.

English, Japanese, Korean, Simplified Chinese, and Traditional Chinese interfaces
are included, with light/dark themes and an optional compact recording view.

## Download and Start

This guide describes WorkLogger 4.0.0. For older versions, use the release notes
and documentation at the matching version tag.

1. Open [Releases](https://github.com/bensitu/worklogger/releases/latest) and choose
   the application download for your operating system, not the **Source code**
   archive. You do not need to install Python to use a packaged application.
2. Follow that release's extraction and launch instructions. Keep all extracted
   application files together rather than moving only the executable.
3. Create a local account and store its recovery key privately. The first local
   account is an administrator.
4. In Calendar, choose a date, enter a time period and content, and save. Open
   Notes for a memo, Analytics for totals, or Reports to build a summary.

Application downloads are available for Windows x64, Linux x64, and macOS Apple
Silicon. See [packaging and verification](docs/packaging.md) for archive layouts,
checksums, and continuous integration builds. Back up existing data before
upgrading; upgraded databases cannot be downgraded.

Operating-system warnings can appear for unsigned applications. Verify the
source and available checksums before deciding whether to run a download;
do not disable security software.

## Your Data and Optional Services

**Use it locally, on your terms.** Your primary database is stored on your device.
You do not need Google/Microsoft sign-in, an AI model, or cloud storage to record
time and prepare reports. Those optional services need their own configuration.

**Know where your data is.** Find the active database under
**Settings > Data > Local data location**. Use
**Backup Data** before moving data or upgrading. Source runs and packaged
applications use different data locations, so replacing an executable does not
replace or reset its database.

**Choose how you protect it.** Local databases, local database backups, and
ordinary exports are unencrypted. Protect them with OS permissions and disk
encryption. Personal cloud backups use a separate backup passphrase by default;
losing it prevents recovery of encrypted versions. These backups contain only
the current account's portable data and do not provide automatic multi-device merging.

**Use AI only when you choose.** Select a local model or explicitly enable an
external service. Models are downloaded or imported separately. Review sharing
controls before sending content externally, and review generated text before
saving. Basic reporting does not require AI.

Local accounts separate records on one installation; they are not a central
company directory or team reporting server. On a managed installation, your
administrator may disable registration or optional services.

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

![Python](https://img.shields.io/badge/python-3.11+-green)

This section is for contributors and users who prefer running Python directly.
For a ready-to-run application, use the [download instructions](#download-and-start).

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

![License](https://img.shields.io/badge/license-GPLv3-blue)

WorkLogger is distributed under the [GNU GPL v3 license](LICENSE). Fonts, icons,
and model files have their own licenses. Model weights are not bundled.
