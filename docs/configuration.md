# Configuration

## Account Preferences

Use Settings for ordinary preferences. General separates work/recording,
calendar display, and application behavior. Account settings belong to the signed-in
user; provider registrations belong to the operating-system user's installation.

| Group | Important defaults |
| --- | --- |
| Appearance | Blue accent, light mode; language inherits startup selection |
| Work/recording | 8 standard hours, 1-hour default break, 168-hour monthly target |
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
    "background_images": true
  }
}
```

`features.background_images` controls whether the background setting and rendering
are available. Disabling it does not delete account images or preferences.
The flag must be a JSON boolean. Missing or invalid configuration disables this
feature. Files are limited to 64 KiB. Keep credentials and private data out of this
file.

Assistant, model-management, and update-check workflows also honor
`WORKLOGGER_FEATURE_AI`, `WORKLOGGER_FEATURE_LOCAL_MODELS`, and
`WORKLOGGER_FEATURE_UPDATE_CHECK`. These default to enabled. Values `1`,
`true`, `yes`, and `on` enable them; other values disable them.
Account preferences cannot override a disabled deployment workflow.

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

## Network

Enable the proxy switch before configuring its host and port. The address accepts
a hostname or `http://host`; enter the port separately. Optional authentication
uses a username/password and, where needed, a domain prefix.

The proxy carries HTTPS requests using HTTP CONNECT without disabling destination
certificate verification. It applies to update checks, model downloads, external
AI, and authenticated account-linking requests. Pre-login provider requests use
direct HTTPS; the system browser follows its own network settings.

An invalid enabled proxy fails rather than silently bypassing the proxy.
Password storage requires an approved OS credential backend. Use a trusted proxy
and network; do not put passwords in configuration files.

## Files and Directories

| Item | Source run | Packaged run |
| --- | --- | --- |
| Database | `worklogger/worklog.db` | `worklog.db` in Qt's application-local user-data directory |
| Models | `models/` beside the database | Same |
| Runtime log | `worklogger.log` in the working directory | Beside the database |
| Deployment flags | Repository-root `worklogger.config.json` | Adjacent override or bundled copy |
| Assets/catalogs | Package resources | Bundled resources |

Open Settings > Data > Data location to see the active path. Model files are shared
by accounts using that database directory; model selection is per account.

Session and installation credential files use `%APPDATA%/WorkLogger/` on Windows,
`~/Library/Application Support/WorkLogger/` for new macOS installations, and
`~/.config/worklogger/` elsewhere. Existing credential pairs can retain their
original directory. Files include `remember_session.enc`,
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
Build and test environment options belong in [packaging](packaging.md) and
[testing](testing.md), not ordinary account configuration.
