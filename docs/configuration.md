# Configuration

## Files and Directories

| Item | Source run | Packaged run |
| --- | --- | --- |
| SQLite database | `worklogger/worklog.db` | `worklog.db` in Qt's user-specific application data directory |
| Model storage | `models/` beside the database | Same rule |
| Runtime log | `worklogger.log` in the working directory | Beside the user database |
| Bundled assets | `worklogger/assets/` | Included application resources |
| gettext catalogs | `worklogger/locales/` | Included application resources |

Packaged applications use `QStandardPaths.AppLocalDataLocation` with organization
and application name `WorkLogger`. Application resources remain read-only. If no
user database exists, startup copies a database beside the executable using a
SQLite snapshot that includes committed WAL transactions. The original is kept.
A pending restore prevents this relocation. A database-specific process lock
prevents simultaneous desktop instances throughout login and logout.

The session credential and machine-key files use `%APPDATA%/WorkLogger/` when
`APPDATA` is set, otherwise `~/.config/worklogger/`:

- `remember_session.enc`: encrypted remembered-login credential.
- `.worklogger_machine_key`: local key used by the session storage implementation.

Do not publish either file. Moving only the database does not move a remembered
session or operating-system credentials.

The pre-login language preference uses Qt native user settings with organization
and application name `WorkLogger` and key `ui/language`. Its physical location is
platform-dependent. Account settings are stored separately in SQLite.

## Environment Variables

| Variable | Consumer and behavior |
| --- | --- |
| `WORKLOGGER_LANG` | Explicit startup language override; account language is applied after authentication |
| `WORKLOGGER_LOG_PATH` | Alternative runtime log path |
| `WORKLOGGER_DEBUG` | Enables debug logging for `1`, `true`, `yes`, or `on` |
| `WORKLOGGER_BUILD_CONSOLE` | Read by `WorkLogger.spec`; normally set by `scripts/build.py --console` |
| `WORKLOGGER_BUILD_LOCAL_INFERENCE` | Normally set by `scripts/build.py --with-local-inference` |
| `WORKLOGGER_CODESIGN_IDENTITY`, `WORKLOGGER_CODESIGN_ENTITLEMENTS` | Optional macOS build-signing inputs |
| `WORKLOGGER_MODEL_CATALOG_URL` | Explicit HTTPS catalog URL for model refresh; unset uses local metadata |
| `QT_QPA_PLATFORM=offscreen` | Headless GUI tests and runtime checks; omit for interactive desktop use |
| `QT_SCALE_FACTOR` | Useful for display-scaling verification, not a saved application preference |
| `WORKLOGGER_SCREENSHOTS` | Test-only destination for rendered screenshots |
| `WORKLOGGER_QA_DATABASE` | Optional read-only calendar test dataset; omit to use synthetic records |

There is no command-line database-path switch. Programmatic callers may pass
`DesktopRuntimeConfig(database_path=...)`; ordinary interactive runs use the path
rules above.

## Language Resolution

Before authentication, the order is an explicit environment override, the saved
device preference, the first supported system UI language, then English.
After authentication, an explicit account preference takes precedence. An account
without a stored language inherits the startup language.

Supported codes are `en_US`, `ja_JP`, `ko_KR`, `zh_CN`, and `zh_TW`. Region/script
matching maps Traditional Chinese variants such as `zh-Hant` and `zh-HK` to
`zh_TW`, and Simplified Chinese variants to `zh_CN`.

## Account Defaults

Values below are defaults from `SettingsViewModel`, not deployment environment
variables. They are stored as strings in the settings repository.

| Key | Default | Meaning or range |
| --- | --- | --- |
| `theme` | `blue` | `blue`, `pink`, `green`, `purple`, `custom` |
| `custom_theme_color` | `#4f8ef7` | Normalized six-digit RGB color |
| `dark_mode` | `0` | Light mode by default |
| `language` | Inherited at startup | Supported language code |
| `standard_work_hours` | `8.0` | 1 to 24 hours |
| `default_break_hours` | `1.0` | 0 to 4 hours |
| `monthly_target_hours` | `168.0` | 0 to 400 hours |
| `show_holidays` | `1` | Calendar holiday display |
| `holiday_region` | Empty | Automatic system region, or an ISO country with optional subdivision such as `DE/BW` |
| `show_note_markers` | `1` | Stored preference; its settings control is hidden |
| `show_overnight_indicator` | `1` | Calendar overnight indicator |
| `week_start_monday` | `0` | Sunday-first calendar by default |
| `enable_tray`, `enable_menu_bar` | `0` | Platform residency preference |
| `minimal_mode` | `0` | Programmatic/stored option; its settings control is hidden |
| `ai_assist_enabled` | `1` | Preference, not proof of a configured generation service |
| `ai_privacy_include_notes` | `1` | Include notes when building AI context |
| `ai_privacy_include_calendar` | `1` | Include calendar events in AI context |
| `ai_privacy_include_quick_logs` | `1` | Include quick logs in AI context |
| `local_model_enabled` | `1` | Local model preference |
| `external_model_base_url` | `https://api.openai.com/v1` | Stored external-service preference |
| `external_model_name` | `gpt-4o-mini` | Stored model identifier, not an active service |
| `network_proxy_enabled` | `0` | Stored preference; not applied to HTTP adapters |
| `network_proxy_port` | `0` | Integer from 0 to 65535 |
| `network_proxy_address`, `network_proxy_username`, `network_proxy_domain` | Empty | Stored proxy fields |
| `network_proxy_password` | Empty | Accessed through the system credential store |
| `last_backup_at` | Empty | Last recorded successful backup timestamp |

Model selection also uses `local_model_active_id`. Account password-change
requirements are enforced by the authentication workflow, not by changing a UI
preference alone.
Automatic recording stores its active or completed unsaved state as JSON under
`auto_record_state`; it is runtime state, not a user-editable preference.

## Feature Definitions

Desktop composition reads `WORKLOGGER_FEATURE_AI`, `WORKLOGGER_FEATURE_LOCAL_MODELS`,
and `WORKLOGGER_FEATURE_UPDATE_CHECK`. All default to enabled; set a value other
than `1`, `true`, `yes`, or `on` to disable the corresponding assistant workflow,
model-management workflow, or manual release check. Account preferences cannot
override a disabled deployment feature. These switches do not supply AI services
or enable disconnected identity providers. Unsupported identity and PDF-narrative
feature definitions have been removed rather than suggesting an available service.
