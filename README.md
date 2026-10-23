# WorkLogger

Remember what you worked on, see where your time went, and prepare reports without starting from a blank page. WorkLogger brings your working hours, daily notes, projects, and reports together on your desktop.

Record time and prepare reports locally, with no hosted service required. AI assistance and personal cloud backups are optional, so you can use only what you need.

📥 **[Download WorkLogger](https://github.com/bensitu/worklogger/releases/latest)**

📖 [Explore the user guide](docs/user-guide.md)

![WorkLogger calendar showing daily hours, classification colors, notes, and individual time records](docs/images/demo_1.png)

## What You Can Do

- **Record the day as it happens.** Start a timer for work or breaks, or enter time afterward. Keep leave records in the same calendar.
- **Correct a record without re-entering the whole day.** Add a lunch break inside a longer meeting, preview what will change, and keep the surrounding work. Split or merge periods and undo eligible changes.
- **Find the work you need to remember.** Organize time by project, work item, activity, or work arrangement. Search a month, year, or custom period.
- **Keep the details, not just the hours.** Write daily notes with recoverable drafts. Choose which notes belong in reports or may be shared with AI.
- **Spend less time putting reports together.** Build daily, weekly, and monthly drafts from your records, adjust the templates, and recover saved versions. Share reports as Markdown or export XLSX/PDF timesheets.
- **See where your time goes.** Review hours, overtime, and project breakdowns. Compare actual attendance with your work plan and set a schedule-based or custom hours goal.
- **Keep a backup where you choose.** Save a backup on your computer or schedule personal backups to your own cloud storage, with encryption enabled by default for cloud backups.

English, Japanese, Korean, Simplified Chinese, and Traditional Chinese interfaces are included, with light/dark themes and an optional compact recording view.

## Download and Start

1. Open [Download WorkLogger](https://github.com/bensitu/worklogger/releases/latest) and choose the file for your computer from the list below.
2. Extract the downloaded file, then open the application. On Windows and Linux, keep the whole extracted folder together rather than moving only the app.
3. Create an account and keep your recovery key somewhere private. You will need it if you forget your password.

| Your Computer | Download | Open After Extracting |
| --- | --- | --- |
| Windows (64-bit) | `WorkLogger-Windows-x64.zip` | `WorkLogger.exe` inside the `WorkLogger` folder |
| Linux (64-bit) | `WorkLogger-Linux-x64.tar.gz` | `WorkLogger` inside the extracted folder |
| Mac with Apple Silicon | `WorkLogger-macOS-arm64.zip` | `WorkLogger.app` |

**Make your first record:** in Calendar, choose a date, enter when you started and finished, add what you worked on, and save. Or start a timer and end it when you finish. Use Notes to remember the details, Analytics to review your hours, and Reports to turn your records into a daily, weekly, or monthly summary.

**Upgrading?** Back up your data in **Settings > Data > Backup Data** first. Once your data has been upgraded, it cannot be opened with an older version.

If your computer shows a security warning or the application does not open, check the [download guidance](docs/packaging.md#application-downloads) and [startup help](docs/troubleshooting.md#startup). Only use downloads you trust; do not disable security software.

## Your Data and Optional Services

**Use it locally, on your terms.** Your records are stored on your computer. Create an account within the app and start recording; Google/Microsoft sign-in, AI assistance, and cloud backups are optional.

**Know where your data is.** Find your data folder under **Settings > Data > Local data location**. Use **Backup Data** before moving data or upgrading. Replacing the application does not erase your records or create a fresh account.

**Choose how you protect it.** WorkLogger does not encrypt local data files, local backups, or ordinary exports. Keep these files in a protected location and use your computer's storage encryption when needed. Personal cloud backups use a separate backup passphrase by default; keep it safe, because encrypted backups cannot be recovered without it. Cloud backups restore one account at a time; they do not automatically combine changes made on different devices.

**Use AI only when you choose.** Basic reporting does not require AI. If you want assistance, choose an on-device option or connect an external service in Settings. Review what you allow the app to share, and check generated text before saving. On-device AI requires a separate download.

**Using WorkLogger at work?** Accounts keep records separate within the app; WorkLogger does not provide a shared company dashboard. Your administrator may disable account registration or optional services on a managed installation.

See [backup and recovery](docs/cloud-backups.md),
[security and privacy](docs/security.md), and
[startup troubleshooting](docs/troubleshooting.md#startup).

## Help and Guides

| Start Here | Details |
| --- | --- |
| [User guide](docs/user-guide.md) | Recording, notes, reports, and analytics |
| [Settings](docs/configuration.md) | Work schedules, goals, appearance, and connection settings |
| [Data formats](docs/data-formats.md) | CSV, iCalendar, Markdown, XLSX, and PDF |
| [Personal cloud backups](docs/cloud-backups.md) | Encryption, schedules, versions, and restoration |
| [Troubleshooting](docs/troubleshooting.md) | Help with sign-in, startup, and missing data |

## For Contributors

Want to improve WorkLogger, translate the interface, or build it yourself?
Start with [contributing](CONTRIBUTING.md) and the [development guide](docs/development.md).

| Guide | Details |
| --- | --- |
| [Architecture](docs/architecture.md) | Application layers and responsibilities |
| [Build and verification](docs/packaging.md) | Dependencies, CI artifacts, checksums, signatures, and release builds |
| [Localization](docs/localization.md) | Updating and checking translations |
| [Deployment configuration](docs/configuration.md) | Feature policies, public configuration, and data locations |
| [Documentation index](docs/README.md) | All user and contributor guides |

### Run From Source

![Python](https://img.shields.io/badge/python-3.11+-green)

For a ready-to-run application, use the [download instructions](#download-and-start).
The following setup is only needed to work with the source code.

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

These commands run the checked-out branch. To run a published version from source, check out its tag first. Some Linux desktops need additional Qt system libraries; see [platform setup](docs/development.md#setup).

Source runs and packaged applications use different default data locations.
Check the active location before testing with existing data.

Local AI is optional for source runs. Install its verified platform dependency with `python scripts/install_native_dependencies.py` using the same virtual environment. See [local model setup](docs/local-models.md).

## License

![License](https://img.shields.io/badge/license-GPLv3-blue)

WorkLogger is distributed under the [GNU GPL v3 license](LICENSE). Fonts, icons, and model files have their own licenses. Model weights are not bundled.
