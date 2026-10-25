# Architecture

Analytics queries and exports use the session's background runner. Requests
capture their period and preferences before dispatch, and only the newest query
can update the displayed dashboard. Exports retain their original data snapshot
when the user changes periods. Calendar cells are reused across refreshes, and
report-history search is debounced with bounded text-measurement caching.
Report history queries return cursor-paginated metadata without report bodies or
source references. Filtering, full-content search, and deterministic sorting run
in SQLite; selecting an owned report reads its latest body separately. History
requests reject superseded results without replacing the open editor draft.
Interactive calendar navigation also loads its overview in the background.

Daily records and events travel with the background overview request. Completion
updates record lists and change-history actions without replacing the live editor
draft. Superseded requests cannot update a newly selected day. Saved settings are
persisted immediately; control-state reloads are coalesced within one event-loop
turn, and unrelated settings do not rebuild calendar statistics.
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

Unexpected adapter failures use `infrastructure_failure` to record the operation
code and exception type without logging exception messages or business payloads.
Validation and conflict results retain their distinct application contracts.
Infrastructure implements those contracts. Presentation handles interaction and
state display; business calculations belong to the domain/application layers.

## Composition and Lifecycle

Managed-account deletion commits database removal before deleting external
service credentials. Database failure leaves those credentials untouched.
Credential cleanup can be retried for a deleted account by an administrator;
cleanup failure does not recreate the account or its removed business data.

The entry point resolves language, logging, database paths, and instance locking.
Authentication creates or restores a local session. Bootstrap and composition
functions assemble account-scoped services, repositories, view models, workflows,
and a window. Logout disposes the session and returns to authentication.
`composition/lifecycle.py` supplies the same resource disposal order for desktop
exit and installed-application checks: stop and join jobs, close inference, then
dispose the window before temporary storage or Qt application teardown.

Startup retries retain the instance-lock requirement and do not reset storage.
Infrastructure classifies storage failures in `startup_errors.py`; presentation
provides retry, read-only file locations, and bounded diagnostic information.
`composition/startup_assistance.py` assembles that UI without requiring an
authenticated session. Database replacement remains a separate recovery flow.
Failed bootstrap attempts stop their jobs and release their runner before another
authentication attempt; retries skip remembered sign-in. Invalid deployment
configuration preserves disabled policies and never enables initial registration.

Presentation helpers without an injected session runner reuse one application-owned
fallback runner. Closing a helper cancels its requests without creating another
thread pool for each interaction. Report reads capture preference snapshots before
dispatch, and repeated project-statistics actions reuse the open dialog.

The main window creates its settings page on first access and reuses it during
the session. Initial calendar overviews, holiday loading, and AI configuration
use background jobs; the record editor is available before those jobs finish.

Dependencies are passed explicitly through constructors. Settings sections receive
callbacks; workflow controllers coordinate dialogs and jobs. The calendar
coordinator connects query results to views. The main window owns navigation,
themes, and lifecycle rather than database algorithms.

Full and minimal windows share `shell/lifecycle_controller.py` for residency,
restore/quit actions, date polling, and presentation cleanup. Window-specific
unsaved-change checks remain explicit callbacks. Hiding a window pauses date
polling, showing it refreshes the current date, and accepted closure stops both
date polling and editor ticks without changing the persisted recording state.
Record-discard prompts share the presentation feedback helper.

`shell/record_dialogs.py` owns record-search reuse and project-statistics dialog
lifecycle. The window supplies live date readers, record selection, and refresh
callbacks; the controller does not access window internals or storage adapters.
Record selection and unsaved-editor navigation remain window responsibilities.

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

Stored timer decoding reports malformed state through `auto_record_restore_failed`
without discarding the original payload. Record-search cursors require canonical
ISO calendar dates to preserve keyset ordering. Corrupt translation catalogs
fall back to source messages without preventing application startup.

Record editors use view-model operations and the contracts in `app/recording_ports.py`.
Query, editing, and automatic recording operations have separate typed contracts;
`TimeEntryOperations` combines them for the editor's account-scoped session.
Normalization, elapsed time, type accounting, overlaps, and limits are validated
outside widgets. Writes use account ownership and expected revisions.

`app/use_cases/manual_entries.py` constructs manual records and requests overlap
replacement previews through the repository contract. `app/entry_selection.py`
resolves classifications and project associations for manual editing, selection
validation, and timer startup using the same account-scoped service ports.
`TimeEntryService` retains the recording state, error translation, and transaction
coordination for automatic recording. Manual edits preserve stored timestamps
when the displayed interval is unchanged, including historical timezone offsets.

Timer completion and persistence of its next state share a transaction.
Work and break classifications support start/end timers; leave remains manual.
The preset-break shortcut writes a bounded rest record without starting a timer.
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

`EntryType` and `CustomEntryType` define an accounting category: work, break, or
leave. `WorkMode` and `CustomWorkMode` are optional metadata on work records and timers, not an
additional source of hours. Break and leave records cannot carry a work mode or
project association. Historical remote and business-trip types retain their
original identities; a known arrangement does not imply a particular activity.
Interval slicing preserves classification and arrangement; merging requires
both to match along with the project context.
Custom type and arrangement catalogs share classification management operations,
optimistic storage updates, and a common editor. Arrangement IDs and historical
labels are carried through timers, record changes, CSV, reports, and personal
backups. Catalog lookup authorizes new choices against the active account;
editing an existing record retains its original snapshot. Shared semantic color
palettes belong to presentation; accounting categories travel with calendar
allocations and chart data rather than being inferred from a hashed identifier.
New manual work saves and completed work timers remember the account's last
selected arrangement in the same transaction as the record. An explicit
unspecified arrangement clears that preference. Historical edits, imports,
project reassignment, break/leave saves, and undo do not change it.

Ordinary saves, imports, and interval transformations share `EntryWriteSession`
for overlap validation, insertion, and timer compare-and-update. The component
uses its caller's active SQLite transaction and never commits independently.
Bulk validation caches are limited to a single validation pass. Reversible change
history is a separate shared collaborator; transformations do not depend on the
ordinary write repository or call its private methods.

Overlap replacement uses immutable `EntryReplacement` values. Domain rules
calculate the new record and preserved fragments; the presentation layer previews
them without writing. Persistence rechecks ownership, expected revisions,
active timers, and overlaps in one transaction before saving records and undo
snapshots. Replacement never infers the position of a historical break deduction.
Clock-based splitting and replacement share interval slicing, preserving captured
instants, classification, content, and project metadata.

Daily notes are separate memos. Their sharing choices and drafts are account/date
scoped. Reports retain saved versions and generation references; regeneration
does not mutate recorded time. See [storage contracts](database.md).

The record view model exposes an immutable `TimeEntryEditorState` for both
rendering and action availability. It resolves manual, automatic, and linked-timer
selection without accessing Qt controls. Widgets retain responsibility for text
translation, layout, and signal delivery. Backup and file-export adapters implement
the shared contracts in `app/ports.py`, not parallel view-model definitions.

`widgets/time_entry_editor.py` builds recording controls without a view model or
business callbacks. `TimeEntryPanel` binds actions and renders editor state. Both
window layouts reuse those controls; the calendar can relocate the mode selector
and action row without changing their action bindings or public control names.

The shared Classification control opens an anchored top-level Qt popup outside
the editor's scroll area. Its selection is isolated from the immutable editor
draft until Apply. Application services revalidate type and project availability
before the widget updates that draft; only the main recording action persists
data. Context changes dismiss the popup instead of applying an old selection.

Calendar allocation is a pure domain calculation over the original records in
each daily summary. Immutable segments carry their contributed hours and semantic
color IDs; the calendar view model resolves theme colors once per refresh. The
single bottom indicator renders those segments without storage access or a
classification tooltip. An explicit `CalendarDimension` separates allocation from
drawing. Entry type is the visible default; work-arrangement allocation retains
unknown values as unspecified and has no user-facing switch.

Analytics exposes independent entry-type and work-arrangement distributions.
Classification duration uses the same domain accounting as calendar allocation;
arrangement totals include only actual work. Report classification labels use
an injected translator, while UI/export adapters use the configured locale.
Neither path mutates historical labels or derives an arrangement from an account
default when reading existing records or importing CSV.

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
Business operations, long-running service requests, and glass rendering use
separate owned thread pools. Glass rendering is limited to two workers; shutdown
cancels and drains all pools. Browser authorization and local model transfers use a separate two-worker pool so waiting for a browser or downloading a model does not occupy interactive AI workers.

Cancellation is cooperative. Controllers reject stale results and completions
for disposed owners; cancellation does not forcibly stop a native call.
CSV and calendar imports check cancellation during parsing and before writing.
Once an atomic database write or file replacement begins, it completes or rolls
back through its storage contract; completion is not relabelled as cancellation
after data has been committed. SQLite backup, integrity validation, and bounded
third-party calendar expansion must return before shutdown can finish waiting.
The synchronous runner in `tests/job_runner.py` supplies deterministic behavior
for isolated tests and is not part of the packaged application.

SQLite connections are short-lived. The connection factory serializes writes;
repositories enforce optimistic updates and atomic operations.
The optional application event bus publishes handler events independently of Qt.

## Optional Services

AI service selection is account-scoped. Explicit external selection uses its
configured endpoint and credentials; local selection uses a verified model and
native backend. Failed requests do not silently choose another provider.

`settings/workflows/text_processing.py` owns AI configuration delivery, local
model status, and connection checks. Model status requests reject superseded
results per settings surface. Connection checks pass the job cancellation token
to the gateway; closing the surface cancels pending checks. Optional startup
initialization completes even if background submission is unavailable.

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
bounded secondary lines. Notes, local models, projects, entry types, and report
versions reuse its sizing and horizontal elision. Selection profiles remain
explicit so existing component appearance is preserved.

One shared stylesheet uses semantic colors from an immutable `ColorPalette`.
Bounded caches reuse resolved colors, stylesheet strings, and Qt palette
templates. Callers receive independent palette copies; widgets are not cached.
Background-image transparency rules
are appended after component styles to preserve their selector priority.
Ancestor-property changes refresh only the affected widget tree, not the global
application stylesheet.

Background option saves reuse validated image frames and coalesce consecutive
changes without blocking the controls. Image imports and removal remain serialized
with pending option saves. Opacity updates retain the current animation frame and
playback source instead of restarting the decoder.
Animated backgrounds pause when hidden or when the application is inactive and
resume on activation. Opening another window within the active application does
not pause playback. Visibility behind other applications depends on platform
activation events; complete occlusion is not a portable Qt visibility signal.

Segmented tabs share the `tab_style="segmented"` role. Compact recording controls
use the `density="compact"` and `selection_style="subtle"` modifiers rather than
duplicating rules by widget ID. Theme metrics define their corner radii without
changing application-wide colors.

The resource manifest owns assets, QSS, catalogs, and public configuration.
Add new resources there and verify their packaged paths.
`widgets/file_location.py` groups a copyable, read-only path with directory access
for startup assistance and database recovery. It never edits configuration or
replaces files.
See [localization](localization.md), [packaging](packaging.md), and
[contributing](../CONTRIBUTING.md).
