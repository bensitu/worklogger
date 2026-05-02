# WorkLogger

![License](https://img.shields.io/badge/license-GPLv3-blue)
![Python](https://img.shields.io/badge/python-3.10+-green)

WorkLogger is a privacy-first desktop app for tracking work hours, notes, quick logs, reminders, and AI-assisted reports in multiple languages.

![WorkLogger preview](docs/images/demo_1.jpg)

## Highlights

- Desktop-first PySide6 application with local SQLite storage
- Account-based multi-user data isolation with registration, login, password changes, and remember-me sessions
- Flexible time tracking with Manual Input and Auto Record modes
- Overnight-shift-aware calculations with work type and leave classification
- AI-assisted note and report generation with external API providers and local model fallback
- Multi-turn AI Assist for daily notes, weekly reports, monthly reports, and analytics PDF narratives
- Optional Google sign-in using system-browser OIDC + PKCE and Firebase Identity Toolkit
- Built-in local model management with a GitHub-hosted dynamic catalog, download, resume, verify, switch, and `.gguf` import
- Template-driven daily/weekly/monthly writing with custom template support
- Persistent weekly/monthly reports that reload by selected calendar week or month
- Calendar + Quick Log context integration for richer reports
- Monthly/quarterly/annual analytics with work-hours/average metrics, actual-hours leave overlays, CSV export, and PDF export
- Database backup/restore with a 30-day backup reminder
- Custom accent colors, dark mode, and restart-aware minimal mode
- Multi-language UI (English, Japanese, Korean, Simplified Chinese, Traditional Chinese)
- Cross-platform desktop packaging for Windows, macOS, and Linux

## Download

Release packages are published through GitHub Releases:

- Windows: `WorkLogger.exe`
- macOS: `WorkLogger.app.zip`
- Linux: `WorkLogger.tar.gz`

Build outputs are generated into the `dist/` directory.
For the tag-based release process, see [docs/release.md](docs/release.md).

### Linux install note

The Linux release archive contains a PyInstaller onefile executable named `WorkLogger`.
Extract it, ensure it is executable, and launch it from a desktop session:

```bash
tar -xzf WorkLogger.tar.gz
chmod +x WorkLogger
./WorkLogger
```

The release build targets the current GitHub-hosted Ubuntu runner. Test it on the Linux distributions you plan to support before publishing a release.

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

### Optional Google Sign-In

Google sign-in is disabled unless both Google OAuth and Firebase Web API settings are provided. Local username/password login continues to work without these settings.

The recommended local development path is to copy `worklogger/config/identity.local.example.json` to `worklogger/config/identity.local.json` and fill in deployment-specific values.

```json
{
  "identity_enabled": true,
  "google_login_enabled": true,
  "google_client_id": "YOUR_GOOGLE_OAUTH_CLIENT_ID.apps.googleusercontent.com",
  "firebase": {
    "apiKey": "YOUR_FIREBASE_WEB_API_KEY",
    "authDomain": "your-project.firebaseapp.com",
    "projectId": "your-project"
  }
}
```

Configuration lookup order:

1. `WORKLOGGER_IDENTITY_CONFIG` pointing to a JSON file
2. `%APPDATA%\WorkLogger\identity.local.json` on Windows, or `~/.config/worklogger/identity.local.json` on other platforms
3. `worklogger/config/identity.local.json` in source builds, or `config/identity.local.json` next to a packaged executable

Environment variables are also supported and take precedence over JSON files:

```bash
WORKLOGGER_IDENTITY_ENABLED=1
WORKLOGGER_GOOGLE_LOGIN_ENABLED=1
WORKLOGGER_GOOGLE_CLIENT_ID=your-google-oauth-client-id.apps.googleusercontent.com
WORKLOGGER_FIREBASE_API_KEY=your-firebase-web-api-key
WORKLOGGER_FIREBASE_AUTH_DOMAIN=your-project.firebaseapp.com
WORKLOGGER_FIREBASE_PROJECT_ID=your-project
```

Google sign-in needs a Google OAuth client ID in addition to Firebase configuration. Firebase `appId` is not the OAuth client ID. OAuth is used only for sign-in and account linking. WorkLogger stores provider, broker issuer, subject, email, and display name in SQLite, but does not store OAuth access tokens, refresh tokens, ID tokens, authorization codes, or PKCE verifiers.

## Build

### Windows

```powershell
WorkLogger_build_windows.bat
```

### macOS

```bash
./WorkLogger_build_macOS.sh
```

### Linux

```bash
./WorkLogger_build_linux.sh
```

All build scripts use `worklogger.spec`. The generated executable and packaged artifacts are expected in `dist/`. If you create a macOS App, place the final `.app` file in `dist/` as well.
`WorkLogger_build_macOS.sh` re-signs the merged universal app before zipping. By default it uses ad-hoc signing (`CODESIGN_IDENTITY=-`) for integrity.
`WorkLogger_build_linux.sh` creates `dist/WorkLogger`; the GitHub Actions release workflow packages that executable as `WorkLogger.tar.gz`.

Linux builds require Python 3.10+, PyInstaller, and the desktop runtime libraries needed by PySide6/Qt. The release workflow installs the required Ubuntu packages before running the Linux build script.

### macOS install note (no Apple Developer ID)

If the app is not Developer ID signed + notarized, macOS Gatekeeper may show "Apple cannot verify".
Users can still install by removing the quarantine flag after copying the app:

```bash
pkill -x WorkLogger 2>/dev/null || true

sudo rm -rf "/Applications/WorkLogger.app"
sudo mv "$HOME/Downloads/WorkLogger.app" "/Applications/WorkLogger.app"

sudo xattr -dr com.apple.quarantine "/Applications/WorkLogger.app"

open "/Applications/WorkLogger.app"
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
WorkLogger_build_windows.bat  Windows build entrypoint
WorkLogger_build_macOS.sh     macOS universal build entrypoint
WorkLogger_build_linux.sh     Linux build entrypoint
worklogger.spec               Shared PyInstaller specification
scripts/                      Build helpers and i18n automation scripts
worklogger/
  assets/        Application icons
  config/        Constants, themes, and identity configuration JSON
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

WorkLogger stores data in a local SQLite database named `worklog.db`. In packaged builds, the database is created next to the executable. Work logs, quick logs, calendar events, reports, and settings are scoped by account so users on the same installation do not share data.

On upgrade from older single-user versions, existing local data is migrated to a default `admin` account so it remains accessible after the new login flow is enabled. User-created custom templates and local app settings are also stored locally.

### Administrator Recovery

New accounts receive a recovery key during registration. Store it outside the application; it can reset that account's password without network access. Administrators can also create ordinary users from Settings > Account > Manage Users. Administrator-created users receive a generated initial password, are marked unused until first login, and must set a new password before continuing; that first password change generates their recovery key.

If every administrator loses access and no recovery key is available, technical support can reset a local administrator password with:

```powershell
$env:WORKLOGGER_RESET_PASSWORD = "new-password"
python scripts/admin/reset_admin.py --db path/to/worklog.db --username admin --no-prompt
```

The reset account is marked as an administrator and must change the password on next login.

## Current Features

- Account management with register/login/logout, password change, recovery-key password reset, administrator user management, administrator-created users, remember-me auto-login, and encrypted remember-token storage
- Per-user isolation for work logs, quick logs, calendar events, reports, and settings
- Calendar-centered daily workflow with per-day totals, overtime, holidays, note markers, and overnight indicators
- Manual Input and Auto Record tabs for start/end/break capture with input validation and unsaved-change protection
- Work types: normal, remote, business trip, paid leave, comp leave, and sick leave
- Quick Log editor with start/end time support, inline edit/delete, and report/note integration
- Note editor with template insertion, Quick Log insertion, and AI rewrite assistance
- Weekly and monthly report generation with template picker, AI Assist multi-turn refinement, save/reload by selected period, unsaved-change prompts, copy, and Markdown export
- AI Assist dialog with bounded multi-turn history, selected-period context, Apply actions, Close-driven request cancellation, and switches for including notes, calendar events, calendar event titles, or quick-log details
- Optional Google/Firebase sign-in and account linking with local password login preserved
- Analytics dialog with monthly/quarterly/annual charts, Work hours/Average metric switching, Bar/Line views, actual-hours leave overlays, and export to CSV/PDF
- Data portability: CSV import/export, database backup/restore, `.ics` calendar import/export, and calendar event merge into notes/reports
- AI provider settings with connectivity test, primary/secondary provider routing, local-model fallback, and status-rich AI Assist request feedback
- Local model controls: enable/disable switch, dynamically refreshed model selection from `model_catalog.json` on GitHub, resumable download, hash verification, deletion, and `.gguf` import
- Secure API key handling via OS keychain with encrypted local fallback
- Appearance and behavior controls for preset/custom theme, dark mode, language, minimal mode, week start, holiday display, note reminders, and residency icon mode
- First-run system language detection for English, Japanese, Korean, Simplified Chinese, and Traditional Chinese

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## Security

If you find a security issue, please follow the instructions in [SECURITY.md](SECURITY.md).

## License

This project is licensed under [GPL-3.0-or-later](LICENSE).
