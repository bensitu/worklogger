# Configuration

## Work Schedule

Settings > General > Work plan contains an account-specific weekly
work schedule. Full month plans every calendar day. One day off defaults to
Sunday; two days off defaults to Saturday and Sunday. The 2.5-day option defaults
to Saturday and Sunday off with Friday as a half day. The weekdays can be changed;
custom schedules allow each weekday to be a full day, half day, or day off.
The compact weekly table shows one column per weekday with a single choice in
each column. Abbreviated weekday headings have full weekday names in tooltips;
each choice also has a weekday-specific accessible name.
Presets initially show a summary. Use Adjust schedule to expand the weekly table;
Custom keeps the table expanded.
Use Save within the schedule editor to apply the selection.

Analytics displays actual attendance and planned work separately. Attendance
counts distinct dates with positive worked hours, including work on planned
days off; a half-day plan contributes 0.5 to planned work, not to attendance.
Plans cover the entire selected month, quarter, or year. Comparisons use the
previous complete calendar period, rather than matching elapsed days. Weekly
charts show the in-month date range for each calendar week.

The current recurring schedule is used when viewing any period. With Public
holidays enabled, plans exclude holidays in the selected country and subdivision,
or the system region when selected. With Public holidays disabled, no holiday
dates are excluded and no holiday provider is queried. A holiday on a scheduled
day off is not deducted twice; a holiday on a half day excludes only 0.5 day.
Actual attendance, saved records, leave rules, and daily overtime are unchanged.
Missing or invalid
schedule settings fall back to Full month. The `work_schedule` setting is a
validated JSON object in the existing account settings table; no database schema
change or stored-record migration is required.

## Hours Goal

General > Hours goal offers From work schedule and Custom target. Automatic
targets multiply the selected period's holiday-adjusted planned workdays by
daily standard hours. Quarter and year targets use their actual dates, not a
single month's target multiplied by three or twelve. Custom targets retain a
monthly hours value and are multiplied by the selected number of months.

Existing targets remain custom, including the 168-hour default. Switching to
automatic calculation hides the monthly hours input without deleting its saved
value. Switching back restores it. Work schedules affect goals, not overtime
classification; working a holiday still counts as actual work.

If enabled holiday data or its region is unavailable, planned days and automatic
targets show an unavailable state, while recorded hours and custom targets remain
visible. No unadjusted target is substituted. `work_target_mode` is an account
setting with `manual` and `schedule` values. A missing value retains manual
behavior; the existing settings table requires no schema change or record migration.

## Account Preferences

Use Settings for ordinary preferences. General separates work plans, hours goals,
recording and reminders, classification, calendar display, and application behavior.
Account settings belong to the signed-in
user; provider registrations belong to the operating-system user's installation.

| Group | Important defaults |
| --- | --- |
| Appearance | Blue accent, light mode, full view; language inherits startup selection |
| Work plan and goal | 8 daily standard hours, full-month schedule, custom 168-hour monthly target |
| Recording | 1-hour default break |
| Reminders | Long timer: 10 hours; continuous-work reminder: off |
| Calendar | Holidays and overnight indicators on; Sunday first; recent context on |
| AI | AI Assist and local-model preference on; external processing off |
| AI context | Work content, calendar, and previous entries included; daily notes also require per-date approval |
| Network | Proxy off; address and authentication blank |
| Residency | Tray/menu-bar preference off |
| Background image | Off per account, with 50% image opacity |

Saving an incomplete service configuration does not make it ready.
A disabled service keeps its saved preferences.

## Deployment Configuration

`worklogger.config.json` is a public, non-secret configuration file. In source runs
it is read from the repository root, independently of the working directory.
Packaged runs prefer a file beside the executable, then the bundled copy.
Changes apply after restarting.

```json
{
  "features": {
    "ai": true,
    "cloud_backup": true,
    "self_registration": true,
    "oidc": true,
    "background_images": true,
    "minimal_view": true
  },
  "ai": {
    "rewrite_timeout_seconds": 180,
    "chat_timeout_seconds": 180,
    "connection_test_timeout_seconds": 30
  },
  "local_models": {
    "download_timeout_seconds": 30,
    "catalog_timeout_seconds": 15
  },
  "pagination": {
    "notes_page_size": 50,
    "records_page_size": 100,
    "reports_page_size": 50
  },
  "cloud_backup": {
    "startup_delay_seconds": 300,
    "check_interval_seconds": 60,
    "retry_initial_seconds": 300,
    "retry_max_seconds": 3600
  }
}
```

`features.background_images` controls whether the background setting and rendering
are available. Disabling it does not delete account images or preferences.
`features.minimal_view` controls whether the minimal-view preference and startup
mode are available. Disabling it selects the full view without removing the
account's saved preference or interrupting its persisted timer.
Both display flags must be JSON booleans and default to disabled when omitted.
Invalid configuration disables deployment-controlled features. Files are limited to
64 KiB. Keep credentials and private data out of this file.

`features.ai` is the installation-wide AI policy and defaults to `true` when the
file or this property is absent. Set it to `false` to disable local and external
AI generation, polishing, connection tests, model management, and AI-related
settings, including per-note AI sharing controls. Buttons and settings remain
visible but unavailable; navigation and scrolling remain available. Saved account preferences, credentials,
and model files are retained. Ordinary recording, notes, template-based reports,
updates, and backups remain available. Restart to apply changes.

The policy accepts only a JSON boolean. An invalid AI value or a malformed or
unreadable configuration file disables AI. Environment variables and account
preferences cannot override `features.ai: false`. Protect the configuration and
installation files with deployment permissions; this client-side switch is not
an enforcement boundary against someone who can replace those files or the
application itself.

`features.cloud_backup` is the installation-wide personal cloud backup policy
and defaults to `true` when the file or property is absent. Set it to `false` to
disable WebDAV and S3-compatible backup configuration, connection tests, uploads,
downloads, and cloud backup recovery, including local recovery copies created by
this feature. Controls remain visible but disabled. No cloud backup service,
background schedule, startup catch-up, or retry workflow is started. Saved
configuration, credentials, and existing local and remote backups are retained.
Restart to apply changes. This policy is independent of the AI policy and does
not disable local database backups, CSV/ICS operations, updates, or external
sign-in. Account settings cannot override it. It accepts only JSON booleans;
invalid values or malformed or unreadable files disable cloud backups. Protect
the configuration file with deployment permissions as described above.

`features.self_registration` defaults to `true`. Set it to `false` to disable the
login screen's Register button and reject new self-registered accounts, including
automatic account creation by an unlinked external identity. Existing local
accounts can still sign in, and administrators can still create managed users.
Linked external identities can still sign in when OIDC is enabled. Create the
initial administrator before disabling registration; an empty database does not
provide a registration exception. Startup assistance explains this condition
before opening a login form with no available accounts. If unreadable or malformed
configuration caused the restriction, the guidance identifies the configuration
file instead of treating it as an intentional policy. Correct it and retry;
registration is not enabled automatically.

`features.oidc` defaults to `true`. Set it to `false` to disable Google and
Microsoft browser authentication, identity linking/unlinking, and provider
configuration buttons on the login and account settings screens. Controls remain
visible but disabled. Existing accounts, associations, and provider configuration
are retained. Establish local password access for external-only accounts before
disabling OIDC. Local password login, recovery, and existing local remembered
sessions are not revoked by this setting.

Both policies accept only JSON booleans, apply after restarting, and take
precedence over provider environment variables and account preferences. Invalid
configuration disables both features. Protect deployment files with installation
permissions; these settings do not prevent a local user from replacing the client.

`cloud_backup.startup_delay_seconds` is the minimum delay before automatic cloud
backups may run after signing in. It defaults to 300 seconds and accepts integers
from 0 to 86400 inclusive. Zero removes this delay; invalid values use the default
without changing valid feature flags or model profiles. Manual uploads and
restores are not delayed. After the delay, automatic backups still wait while
recording controls or the reports page are busy. Scheduled checks run once per
minute by default, so the configured delay is a minimum, not an exact execution time. This
setting does not enable automatic backups or change the account's schedule.

Cloud backup scheduling accepts these additional integer values in seconds:

| Key | Default | Allowed range |
| --- | --- | --- |
| `cloud_backup.check_interval_seconds` | 60 | 5 to 3600 |
| `cloud_backup.retry_initial_seconds` | 300 | 5 to 86400 |
| `cloud_backup.retry_max_seconds` | 3600 | 5 to 86400 |

The check interval controls due-work polling, not the account's backup frequency.
Transient failures double the retry delay up to the configured maximum; checks
can start a retry later than its minimum delay. Version conflicts still require
manual review. The maximum must be at least the initial delay; otherwise both
retry values revert to their defaults. Invalid fields use their own defaults
without discarding valid scheduling fields or other configuration sections.

Processing and model network timeouts also accept integer seconds:

| Key | Default | Allowed range |
| --- | --- | --- |
| `ai.rewrite_timeout_seconds` | 180 | 1 to 3600 |
| `ai.chat_timeout_seconds` | 180 | 1 to 3600 |
| `ai.connection_test_timeout_seconds` | 30 | 1 to 300 |
| `local_models.download_timeout_seconds` | 30 | 1 to 600 |
| `local_models.catalog_timeout_seconds` | 15 | 1 to 300 |

Rewrite and chat deadlines apply to both local and external processing. The
connection-test timeout applies only to the sample request in Settings.
Download and catalog timeouts apply to network operations, not a total duration
limit for downloading an entire model. Existing size limits, integrity checks,
proxy routing, and cancellation behavior remain in effect. Invalid timeout
fields independently use their defaults. Restart to apply changes.

List page sizes accept bounded integers:

| Key | Default | Allowed range |
| --- | --- | --- |
| `pagination.notes_page_size` | 50 | 1 to 100 |
| `pagination.records_page_size` | 100 | 1 to 250 |
| `pagination.reports_page_size` | 50 | 1 to 250 |

These sizes control each load-more batch in note history, record search, and
saved reports. Search still evaluates all matching data in the selected range,
and cursor pagination preserves ordering. Report history continues to read
summaries first and content only after selection. These settings do not change
report version retention, undo history, analytics, or exports. Missing or invalid
fields use their individual defaults; booleans, strings, and fractional values
are not accepted. Restart to apply changes.

Assistant, model-management, and update-check workflows also honor
`WORKLOGGER_FEATURE_AI`, `WORKLOGGER_FEATURE_LOCAL_MODELS`, and
`WORKLOGGER_FEATURE_UPDATE_CHECK`. These default to enabled. Values `1`,
`true`, `yes`, and `on` enable them; other values disable them.
These environment flags can further restrict the JSON policy, not enable AI
against it. Disabling AI also disables local model management. Account preferences
cannot override a disabled deployment workflow.

## Minimal View

When available, use **Settings > Appearance > Minimal view** to choose the
account's startup view. The choice applies after restarting or signing in again;
it does not replace the current window or discard current edits.

Minimal view provides manual/automatic time recording, the selected day's
record list, daily notes, and the complete Settings dialog. Settings use the same
account permissions as the full view. The appearance switch can return to the
full view on the next startup or sign-in. Background images and themes apply to
the recording window when enabled, not to separate dialogs.

## Background Images

Enable the account switch before uploading. PNG, JPEG, GIF, and WebP are accepted.
The long edge must be at least 1280 pixels and the short edge at least 720 pixels,
including portrait images. Limits are 20 MiB encoded data, 16 million pixels per
frame, 300 frames, and 128 million decoded pixels across an animation.

Image opacity ranges from 0 to 100%. Zero hides the image; 100 is fully opaque.
Images retain their proportions and fill the main content area with a centered crop.
The light/dark theme remains underneath. Invalid imports preserve the previous
image. Encoded images can contain metadata and are included in database backups.

## AI

For local processing, enable Local Model, select a verified file through Manage
models, and enable AI Assist. See [local model setup](local-models.md).

For external processing, enable the external-model switch and enter an HTTPS API
base address, model ID, and API key for an OpenAI-compatible service. The adapter
uses the base address with `/chat/completions`. Saving fields makes no request.
Test uses sample text rather than work records.

External processing takes precedence when explicitly enabled. A failed local or
external request does not silently choose another provider. Review privacy choices
before sending content. Secrets are stored through credential adapters, not this
deployment file. See [security](security.md).

### External Generation Parameters

Optional `external_model_profiles` in `worklogger.config.json` configure generation
parameters for an exact API base address and model ID. They do not enable external
processing, select an endpoint, or change account credentials. The API address and
model remain the values shown in the account's AI settings. For example, add this top-level property
alongside `features`:

```json
"external_model_profiles": [
  {
    "base_url": "https://api.example.com/v1",
    "model": "your-model-id",
    "temperature": 0.2,
    "max_output_tokens": 2048,
    "token_limit_parameter": "max_tokens"
  }
]
```

Use only parameters supported by the selected service and model. Temperature is
optional and ranges from 0 to 2; omit it for models that do not accept adjustable
sampling. The optional output limit is an integer from 1 to 131,072, subject to the
service's lower limits. `token_limit_parameter` accepts `max_tokens` (default) or
`max_completion_tokens`; only the selected parameter is sent. With
`max_completion_tokens`, the service can include reasoning tokens in the limit.
See the [Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
and your provider's model documentation.

Without a matching profile, generation parameters are omitted and the service's
defaults apply. Base addresses match after trimming surrounding whitespace and
trailing slashes; model IDs are case-sensitive. Profiles apply to both rewriting
and AI Assist conversations. They never apply to local models. Restart or sign in
again to reload profiles. Invalid profiles are ignored with a diagnostic warning
without changing feature flags or account preferences. Duplicate endpoint/model
pairs and unknown profile fields invalidate the profile list. At most 128 profiles
are accepted within the configuration file's existing 64 KiB limit.

## Network

Enable the proxy switch before configuring its host and port. The address accepts
a hostname or `http://host`; enter the port separately. Optional authentication
uses a username/password and, where needed, a domain prefix.

The proxy carries account-scoped HTTPS requests using HTTP CONNECT without
disabling destination certificate verification:

| Request | Account proxy |
| --- | --- |
| Update checks | Yes |
| Remote model catalogs and model downloads | Yes |
| External AI generation and connection tests | Yes |
| WebDAV and S3-compatible backups, including connection tests and restores | Yes |
| Identity linking and external identity confirmation after sign-in | Yes, for application token and signing-key requests |
| Provider authentication before sign-in | No; no account is selected, so application requests use direct HTTPS |
| System browser authorization and external links | No; the browser follows its own network settings |
| Loopback authorization callback | Local only; never forwarded to the proxy |

This setting is not a system-wide proxy or an outbound firewall. Public destination
checks can resolve DNS locally even when HTTPS uses the proxy. Local inference,
holiday calculations, and ordinary local database operations do not require remote
HTTP requests. Application HTTPS transports do not inherit environment proxy or
`NO_PROXY` bypass settings. Proxy changes apply to subsequent HTTP requests; an
S3 client captures the proxy when a backup operation starts. In-progress requests
are not rerouted.

An invalid enabled proxy fails rather than silently bypassing the proxy.
Password storage requires an approved OS credential backend. Use a trusted proxy
and network; do not put passwords in configuration files.

## Files and Directories

| Item | Source run | Packaged run |
| --- | --- | --- |
| Database | `worklogger/worklog.db` | `worklog.db` in Qt's application-local user-data directory |
| Models | `models/` beside the database | Same |
| Runtime log | `worklogger.log` beside the database | Same |
| Deployment configuration | Repository-root `worklogger.config.json` | Adjacent override or bundled copy |
| Assets/catalogs | Package resources | Bundled resources |

Open Settings > Data > Local data location to see the active path. Model files are shared
by accounts using that database directory; model selection is per account.

Configure account-scoped WebDAV or S3-compatible storage separately under
**Personal cloud backup**. See [personal cloud backups](cloud-backups.md) for
credentials, encryption, schedules, version checks, retention, and restoration.

New session and installation credential files use `%LOCALAPPDATA%/WorkLogger/`
on Windows, falling back to `%APPDATA%/WorkLogger/` when local application data
is unavailable. An existing roaming directory containing an earlier machine
key, session, or provider registration remains in use to preserve access.
On macOS, new installations use `~/Library/Application Support/WorkLogger/`;
other systems use `~/.config/worklogger/`. Existing credential pairs can retain
their original directory. Files include `remember_session.enc`,
`.worklogger_machine_key`, and `identity-config.enc`. Keep them private.
Moving only the database does not transfer OS credentials or model files.

## Language and Runtime Overrides

Before login, language selection uses `WORKLOGGER_LANG`, a saved device preference,
the first supported system UI language, then English. An account preference takes
precedence after login. Supported codes are `en_US`, `ja_JP`, `ko_KR`, `zh_CN`,
and `zh_TW`.

`WORKLOGGER_LOG_PATH` overrides the log location. `WORKLOGGER_DEBUG` enables debug
logging for the same true values listed above.
`WORKLOGGER_MODEL_CATALOG_URL` supplies an HTTPS URL for model catalog refresh.
Provider registration overrides are described in [browser sign-in](identity-signin.md).
Tray residency uses the Windows/macOS platform mapping when Qt reports a tray
service. On other platforms, closing the main window exits normally; saved timer
state remains available after signing in again.
Build and test environment options belong in [packaging](packaging.md) and
[testing](testing.md), not ordinary account configuration.
