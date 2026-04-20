# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
