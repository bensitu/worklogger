# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.1.0] - 2026-05-01

### Added

- Added a repository-root `model_catalog.json` for GitHub-hosted local model catalog updates.
- Added dynamic catalog refresh before opening Settings -> AI -> Local Model model management.
- Added administrator user creation with generated initial passwords, immediate list refresh, and first-login forced password changes.
- Added user management "In Use" status based on first successful login.

### Changed

- Leave, comp leave, and sick leave entries no longer contribute to work totals, overtime, work-day counts, reports, or exported work calendar events.
- Analytics leave overlays now use actual leave hours instead of filling remaining target time or using a fixed-height marker.
- First-login forced password changes generate a recovery key without requiring the old or initial password.
- PyInstaller packaging now validates and includes the repository-root remote model catalog file alongside the offline fallback catalog.
- Local model download management now opens an import-only dialog when remote catalog refresh fails, and disables Download when the selected model is already downloaded or no downloadable model is available.
- Gettext POT/PO catalogs are sorted by msgid, matched across all built-in languages, and verified obsolete entries have been removed.

### Fixed

- Fixed analytics display when a week has both full-day leave and enough work hours to reach or exceed the weekly target.
- Fixed leave records with explicit start/end times over 8 hours being treated as overtime and attendance.
- Fixed the issue where the “Previous/Next” date buttons were unresponsive when the selected date did not have valid start and end times.
- Fixed AI Assist cancellation while a local model is loading so worker callbacks detach from closed dialogs and Qt timers are stopped on the UI thread.

## [3.0.0] - 2026-04-26

### Added

- Added localized built-in template display names for daily, weekly, and monthly report templates.
- Added custom theme color support with persistent accent storage and an OK/Cancel color picker.
- Added minimal mode, which hides secondary panels and report/analytics controls after restart for a focused workflow.
- Added first-run system language detection for English, Japanese, Korean, Simplified Chinese, and Traditional Chinese.
- Added enhanced analytics controls for Work hours/Average metrics, Bar/Line chart modes, remembered Show leaves preference, leave overlays, and leave hours in exports.
- Added account management with registration, login, logout, password changes, remember-me auto-login, and encrypted remember-token storage.
- Added strict per-user data isolation for work logs, quick logs, calendar events, reports, and settings.
- Added Settings -> Data database backup/restore with a 30-day backup reminder and current-account restore validation.
- Added weekly/monthly report persistence so saved reports reload automatically for the selected calendar week or month.

### Changed

- Report save now updates the current week or month instead of creating a separate visible history list.
- Report dialogs now prompt to save unsaved weekly/monthly edits before closing.
- Analytics and report data preparation were moved behind service-layer APIs so UI code does not compute or query persistent data directly.
- Settings now includes an Account tab for current-user display, password changes, and logout.
- Existing single-user databases are migrated into a default `admin` account during upgrade.

### Fixed

- Fixed custom color picker behavior so theme changes apply only after OK, while Cancel/close leaves the active theme unchanged.
- Fixed the custom-theme palette control to use an icon button with localized tooltip text.
- Fixed remember-token storage to require encrypted storage instead of silently falling back to plain text when `cryptography` is unavailable.
- Fixed backup timestamp handling so restoring a freshly created backup does not re-trigger the 30-day backup reminder.
- Fixed analytics i18n coverage for new Metric/Chart labels and related chart controls.

## [2.2.2] - 2026-04-22

### Changed

- Windows build now installs `llama-cpp-python` from the prebuilt CPU wheel index with explicit pip timeout/retry controls, avoiding local source compilation on machines without MSVC/NMake toolchains.
- Local-model runtime dependency installation was split from general requirements in the Windows build flow so packaging remains deterministic while still bundling local inference support into the executable.

### Fixed

- Fixed a localization issue with the fallback state in external model handover messages, ensuring that AI-related messages are parsed via gettext in all supported language environments.
- Fixed remaining untranslated local-model status/error strings in non-English locale catalogs, including verification timeout/cancel/failure and permission-denied messages.
- Fixed locale catalog consistency so all five built-in languages (`en_US`, `ja_JP`, `ko_KR`, `zh_CN`, `zh_TW`) pass gettext extraction/sync/compile/check validation.

## [2.2.1] - 2026-04-21

### Changed

- macOS packaging flow was updated to a deterministic per-architecture pipeline with explicit x86_64/arm64 verification and clearer build diagnostics.
- PyInstaller macOS bundling was switched to an onedir-style `.app` layout to align with current PyInstaller guidance.

### Fixed

- Fixed language switching in packaged builds by ensuring gettext `.mo` catalogs are compiled and included during build/packaging.
- Fixed update-check SSL failures in packaged apps by using a strict certifi-backed CA bundle path while keeping certificate verification enabled.
- Fixed universal-merge reliability so the final app contains both x86_64 and arm64 Mach-O slices.

## [2.2.0] - 2026-04-18

### Added

- Local model status now shows clear `Ready · Active/Inactive` state labels.
- Expanded UI coverage for local model state switching and language-aware rendering.

### Changed

- Added gettext-based internationalization support with five built-in languages: `en_US`, `ja_JP`, `zh_CN`, `zh_TW`, and `ko_KR`. Additional standard PO translation files can be added from the POT template.
- Improved the local model downloader and validator flow with timeout and retry handling, better failure recovery, and clearer state transitions.
- Refined global local-model toggle behavior so that related actions are consistently blocked when the local runtime is disabled.

### Fixed

- Fixed an issue where the local model status could remain stale after a delete action in the model management flow; the UI now refreshes immediately to the not-downloaded state.
- Fixed repeated validation triggers when reopening settings or reselecting options, reducing redundant validation checks.
- Fixed a language mismatch issue affecting status labels under **Settings → AI → Local Model**.

## [2.1.0] - 2026-04-16

### Added

- Calendar overnight indicator `🌙` in day-cell top-right corner with dark-mode-aware rendering and runtime toggle.
- New settings key `settings.general.show_overnight_indicator` with persistence and immediate calendar refresh.
- New i18n keys across `en/zh-CN/zh-TW/ja/ko`:
  - `settings.general.show_overnight_indicator`
  - `settings.ai.local_model_disabled_tooltip`
  - `ai_assist.local_model_not_running`
- Local-model global switch enforcement tests and fallback behavior tests.

### Changed

- Local model switch now acts as a true global gate:
  - when disabled and no local model downloaded, model-management download action is blocked with tooltip;
  - toggling off unloads local provider immediately and persists disabled state.
- AI Assist progress log now reports local-model-not-running state and continues with cloud fallback when available.
- Calendar cell text keeps concise layout while overnight status is surfaced via icon marker.

## [2.0.1] - 2026-04-14

### Fixed

- Fixed the logic for checking for updates.

## [2.0.0] - 2026-04-13

### Added

- **Local model inference** — on-device AI via llama-cpp-python, zero data sent externally.
- **Model catalog** (`models/catalog.json`) — 5 models: Qwen2.5-3B Q4, Qwen3-4B, SmallThinker-3B Q4/Q2, Llama-3.2-3B Q4.
- Model Management dialog with card-style selection, per-model status, and delete controls.
- Automatic dependency installation (httpx, portalocker, llama-cpp-python) on first use.
- Thinking-tag stripping (`<think>`, `<|begin_of_thought|>`) for reasoning models.
- Automatic fallback to external API when local model fails.

### Changed

- Progress bar respects active theme colour.
- Download status messages consolidated into the log area.
- PyInstaller frozen-app models directory now correctly placed next to the executable, not in the temp folder.
- `_app_root()` uses `sys.frozen` / `sys.executable` for reliable path resolution in packaged apps.
- `max_tokens` raised to 1024–8192 (per-model via catalog `max_tokens` field).
- `n_ctx` set to model training context (32768 / 131072) via catalog `n_ctx` field.

### Fixed

- `Signal(int, int)` overflow for files > 2 GB changed to `Signal(object, object)`.

## [1.1.1] - 2026-04-10

### Fixed

- Fixed AI setting issue.

## [1.1.0] - 2026-04-09

### Added

- Added more customizable options throughout the application.

### Changed

- Slightly adjusted the visual layout and styling of the main interface.
- **Refactoring:** Decoupled several tightly coupled modules to improve overall architecture and long-term maintainability.
- **Structure:** Split the monolithic `ui/dialogs.py` into a dedicated `ui/dialogs/` directory with separate modules per functionality.

## [1.0.1] - 2026-04-08

### Added

- Dual time-entry tabs allowing users to switch between manual input and automatic recording workflows.
- Break tracking enhancements, including localized state management, a quick 1-hour entry option, and "Restart or Continue" prompts for clarity.
- Reminder dot settings for days containing only notes, with an option to make note markers fully optional.
- Public holiday visibility controls with explicit default settings.
- An About page featuring a comprehensive feature overview in all supported languages.
- Localized standard dialog buttons (e.g., OK, Cancel, Save, Discard) across the interface.
- Windows tray icon and macOS menu bar residency options, providing context actions for background operation.

### Changed

- Updated documentation to accurately reflect current features, settings, and packaging behavior.

### Fixed

- Resolved connection errors with the AI service and improved the display of error messages during AI connectivity tests.

## [1.0.0] - 2026-04-07

### Added

- Initial public release.
- Quick log entry, notes management, templates, and reporting workflows.
- Repository documentation standards including Contribution guidelines, Code of Conduct, and Security policy.

### Changed

- Improved UI theme consistency for dialog boxes and list views.
- Enhanced default fallback behavior for language, theme, country locale, and number formatting settings.
