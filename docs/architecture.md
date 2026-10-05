# Architecture

## Structure

WorkLogger is a single-process Qt Widgets desktop application. SQLite is local
storage, not a network service. The code separates domain rules, application
operations, infrastructure implementations, and presentation.

```text
main.py -> bootstrap.py
               | constructs repositories, handlers, view models, and controllers
               v
presentation -> app -> domain
      |           ^      ^
      +---- infrastructure
```

The diagram describes principal responsibilities, not an absolute import rule:
presentation also uses infrastructure translation/resource helpers, and existing
domain defaults are defined in `config/constants.py`.

| Location | Responsibility |
| --- | --- |
| `worklogger/main.py` | Desktop entry point and non-interactive checks |
| `worklogger/bootstrap.py` | Runtime composition, account resolution, settings, resource setup |
| `worklogger/config/` | Application constants and optional feature-switch definitions |
| `worklogger/domain/` | Data models, calculations, validation, repository protocols |
| `worklogger/app/commands/` | Immutable write-operation inputs |
| `worklogger/app/queries/` | Immutable read-operation inputs |
| `worklogger/app/use_cases/` | Validation and coordination through repository/service contracts |
| `worklogger/app/ports.py` | AI, export, backup, credential, and model service contracts |
| `worklogger/infrastructure/` | SQLite, files, HTTP clients, identity, models, translations, logging |
| `worklogger/presentation/viewmodels/` | UI-independent presentation state and operation results |
| `worklogger/presentation/shell/` | Navigation, pages, main window, compact window, tray behavior |
| `worklogger/presentation/widgets/` | Reusable visual controls and painting |
| `worklogger/presentation/theme/` | Palette tokens, QSS generation, font registration |

The [architecture tests](../tests/architecture/test_layer_boundaries.py) check
import boundaries, filenames, Qt object names, and stylesheet placement.

## Startup and Authentication

1. `main()` handles command-line checks or starts the desktop loop.
2. `build_authenticated_desktop_runtime()` configures logging, resolves the
   database, and applies pending migrations.
3. A `QApplication` is created or reused; bundled fonts and the application icon
   are installed. Language preferences are resolved before authentication.
4. `AuthController` restores a valid remembered session or displays account
   registration/login and, when required, password-change dialogs.
5. `bootstrap.py` constructs repositories, use-case handlers, view models,
   workflow controllers, and the application window for the authenticated user.
6. Account settings determine language, appearance, working-hour defaults, and
   calendar options. The window is refreshed before the Qt event loop runs.
7. Logout clears the local remembered session, closes the current window, and
   returns to the authentication loop.

`build_desktop_runtime()` is a separate programmatic construction path used by
tests and runtime checks. Its explicit `create_user_if_empty` option is not the
normal interactive registration flow.

## Application Operations

A manual save follows this path:

```text
WorkLogEntryPanel
  -> AppWindow save callback
  -> WorkLogEntryViewModel
  -> SaveWorkLogHandler(SaveWorkLogCommand)
  -> normalize_work_log
  -> SQLiteWorkLogRepository
  -> calendar, totals, and record-detail refresh
```

Repositories scope records by user ID. Domain validation owns time normalization,
overnight detection, shift-length limits, and break constraints. The UI must not
reimplement these calculations independently.

Quick logs, daily notes, reports, calendar events, accounts, and settings follow
the same command/query and handler pattern. Daily notes have independent storage,
and time-entry reads combine the note for the selected date. Editor saves use
optimistic content checks to prevent overwriting another editor's changes.

## Results and Errors

`Result[T]` represents either a value or an `AppError`. Error types include
validation, authentication, authorization, conflict, infrastructure, cancellation,
and not-found conditions. Infrastructure adapters may catch external exceptions
and return structured failures; some repository methods deliberately raise to
their callers. Do not assume every method returns `Result`.

`presentation/errors.py` translates stable error codes into user-facing messages.
Controllers/pages follow existing dialog and status behavior. Empty status labels
occupy no space when `StatusLabel` is used. Saving ordinary time entries refreshes
the view without a success popup.

## Concurrency

`JobRunner` is the application contract for long operations. `QtJobRunner` executes
jobs in `QThreadPool` and delivers completion through a Qt signal on the UI thread.
`ImmediateJobRunner` provides deterministic synchronous behavior for tests.

Cancellation is cooperative: cancellation does not forcibly terminate Python or a
network request. Controllers must ignore obsolete completions and avoid updating
closed dialogs. Widgets must only be read or changed on the GUI thread.

`SQLiteConnectionFactory` opens short-lived connections and serializes writes
through its instance lock. File databases use foreign keys, WAL, and a busy
timeout. Its `:memory:` connections are not a shared persistent in-memory database;
use temporary files for repository tests spanning multiple connections.

## Composition Boundaries

`AppContainer` and `EventBus` are reusable, tested utilities. The standard desktop
currently constructs dependencies directly in `bootstrap.py` and connects Qt
signals; it is not assembled through a global container or event bus.

Feature switches control assistant, model-management, and update-check composition,
but do not supply missing service implementations. AI handlers
are constructed without a generation service, identity providers are disabled,
and the local model manager is independent of inference. See
[integrations](integrations.md) for the implemented boundaries.

## Presentation and Resources

The shell exposes Calendar, Reports, Analytics, and Settings. Each feature uses
existing reusable controls. Calendar cells and charts use `QPainter`; reports use
Markdown-backed editors and history. Theme tokens render the shared QSS templates.
The Qt palette and QSS are applied at the application boundary.

Fonts, SVG icons, WebP imagery, platform icons, and compiled gettext catalogs are
runtime resources. Source and frozen path handling is defined in the resource,
database-path, and translation helpers. A new asset must be covered by the
[packaging manifest](../scripts/build_resources.py) and rendering tests.
