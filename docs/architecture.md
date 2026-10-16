# Architecture

Analytics queries and exports use the session's background runner. Requests
capture their period and preferences before dispatch, and only the newest query
can update the displayed dashboard. Exports retain their original data snapshot
when the user changes periods. Calendar cells are reused across refreshes, and
report-history search is debounced with bounded text-measurement caching.
Interactive calendar navigation also loads its overview in the background.
Synchronous refresh remains available to non-interactive callers and rejects
pending overview results before applying a newer state.

## Layers

| Directory | Responsibility |
| --- | --- |
| `domain/` | Models, rules, validation, repository contracts |
| `app/` | Commands, queries, use cases, service ports, job contracts |
| `infrastructure/` | SQLite, files, credentials, networking, external adapters |
| `presentation/` | Qt widgets, view models, controllers, themes |
| `composition/` | Feature-specific dependency assembly |
| `bootstrap.py` | Runtime assembly and lifecycle |
| `config/` | Shared constants and deployment feature definitions |

Domain code must not import Qt, storage, or infrastructure.
Application handlers depend on contracts, not concrete widgets or adapters.
Infrastructure implements those contracts. Presentation handles interaction and
state display; business calculations belong to the domain/application layers.

## Composition and Lifecycle

The entry point resolves language, logging, database paths, and instance locking.
Authentication creates or restores a local session. Bootstrap and composition
functions assemble account-scoped services, repositories, view models, workflows,
and a window. Logout disposes the session and returns to authentication.
`composition/lifecycle.py` supplies the same resource disposal order for desktop
exit and installed-application checks: stop and join jobs, close inference, then
dispose the window before temporary storage or Qt application teardown.

The main window creates its settings page on first access and reuses it during
the session. Initial calendar overviews, holiday loading, and AI configuration
use background jobs; the record editor is available before those jobs finish.

Dependencies are passed explicitly through constructors. Settings sections receive
callbacks; workflow controllers coordinate dialogs and jobs. The calendar
coordinator connects query results to views. The main window owns navigation,
themes, and lifecycle rather than database algorithms.

Settings workflows bind directly to `SettingsPage`, including the page hosted by
`SettingsDialog`. The shared page exposes named methods for service availability,
busy states, and processing feedback. Controllers do not probe widget attributes
to discover these capabilities. Dialog attribute forwarding remains available to
existing callers, but is not used to assemble or bind settings workflows.

`bootstrap.py` prepares the application, database, and authentication boundary.
`composition/desktop.py` assembles an account-scoped session and its window.
Composition factories use `build_` names and receive lifecycle dependencies
explicitly; feature modules must not import bootstrap to obtain services.
Preference defaults and normalization belong to `domain/settings`, and holiday
region validation uses an injected catalog rather than loading a provider from
the view model.
Settings composition supplies lazy readers for supported holiday regions and the
system country. The view model captures an immutable catalog on first access;
controls render it without importing optional holiday or timezone providers.
`app/settings.py` reads named preferences with optional batching and consistent
defaults. Callers use the same reader contract whether a store supports batch
queries or individual reads; secure credentials remain on their separate ports.

## Recording and Reporting

Record editors use view-model operations and the contracts in `app/recording_ports.py`.
Query, editing, and automatic recording operations have separate typed contracts;
`TimeEntryOperations` combines them for the editor's account-scoped session.
Normalization, elapsed time, type accounting, overlaps, and limits are validated
outside widgets. Writes use account ownership and expected revisions.

Timer completion and persistence of its next state share a transaction.
`domain/worklog/timer_state.py` owns timer models, persisted representation, and
recovery validation, including historical break fields. Application services own
storage access and context authorization. Recording operations capture an immutable
editor request and use an independent service session initialized from explicit
`RecordingState`. Completion returns a typed result containing the editor and
recording state, not a view model or service. Only completion updates the displayed
editor; failed operations also return their validation and recovery state. Timer
compare-and-update values remain unchanged. `domain/worklog/content.py` defines
the content limit shared by editing, recovery, and rewriting.
Daily summaries aggregate records, while editing and exports retain individual
identities. Custom type and project labels are historical snapshots.

Ordinary saves, imports, and interval transformations share `EntryWriteSession`
for overlap validation, insertion, and timer compare-and-update. The component
uses its caller's active SQLite transaction and never commits independently.
Bulk validation caches are limited to a single validation pass. Reversible change
history is a separate shared collaborator; transformations do not depend on the
ordinary write repository or call its private methods.

Daily notes are separate memos. Their sharing choices and drafts are account/date
scoped. Reports retain saved versions and generation references; regeneration
does not mutate recorded time. See [storage contracts](database.md).

The record view model exposes an immutable `TimeEntryEditorState` for both
rendering and action availability. It resolves manual, automatic, and linked-timer
selection without accessing Qt controls. Widgets retain responsibility for text
translation, layout, and signal delivery. Backup and file-export adapters implement
the shared contracts in `app/ports.py`, not parallel view-model definitions.

The report page coordinates state and requests. `widgets/report_editor.py` owns
editor controls without persistence dependencies; `reporting/exports.py` handles
export selection using immutable content and date snapshots. Period navigation
belongs to domain reporting rules and rejects dates outside the supported range.

## Results and Background Work

`Result[T]` contains a value or an `AppError`.
Presentation maps stable error codes to gettext messages without exposing raw
exception payloads. Follow each adapter's documented return/exception contract.

Long-running I/O, authorization, exports, and inference use `JobRunner`.
`QtJobRunner` runs workers and delivers completion on the UI thread.
Qt widgets must only be read or changed on that thread.

Cancellation is cooperative. Controllers reject stale results and completions
for disposed owners; cancellation does not forcibly stop a native call.
`ImmediateJobRunner` supplies deterministic behavior for isolated tests.

SQLite connections are short-lived. The connection factory serializes writes;
repositories enforce optimistic updates and atomic operations.
The optional application event bus publishes handler events independently of Qt.

## Optional Services

AI service selection is account-scoped. Explicit external selection uses its
configured endpoint and credentials; local selection uses a verified model and
native backend. Failed requests do not silently choose another provider.

HTTP transports enforce certificate validation and account proxy policy.
Provider authentication validates request binding and signed tokens before
resolving a local identity. Keep credentials out of generic configuration,
representations, exception text, and logs.

Deployment availability and account preferences are distinct. Disabling a feature
in deployment configuration must preserve saved account preferences.

## Resources and Presentation

Apply palettes and QSS at the application boundary. Reuse shared controls,
button roles, icons, and fonts. Icon-only actions need tooltips and accessible
names. Strings use gettext; date labels use presentation helpers.

`widgets/preview_list.py` provides shared lists and delegates for a title with
bounded secondary lines. Notes, local models, projects, work types, and report
versions reuse its sizing and horizontal elision. Selection profiles remain
explicit so existing component appearance is preserved.

One shared stylesheet uses semantic colors from an immutable `ColorPalette`.
Bounded caches reuse resolved colors, stylesheet strings, and Qt palette
templates. Callers receive independent palette copies; widgets are not cached.
Background-image transparency rules
are appended after component styles to preserve their selector priority.
Ancestor-property changes refresh only the affected widget tree, not the global
application stylesheet.

The resource manifest owns assets, QSS, catalogs, and public configuration.
Add new resources there and verify their packaged paths.
See [localization](localization.md), [packaging](packaging.md), and
[contributing](../CONTRIBUTING.md).
