# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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