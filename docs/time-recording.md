# Time Recording

## Interaction Model

The calendar is a period recorder, not a single daily shift form. Each completed
period has an account-scoped ID, start/end, activity type, content, and revision.
The right-side total shows worked time already stored for the selected date.
Scheduled calendar events are displayed separately and do not count as work.

New time record is the main action in the calendar header. It opens Manual Input,
clears the editing selection, and focuses the start field. A separate Notes
button opens the selected date's memo without creating a work period. Historical
quick logs are readable there; they do not contribute worked hours.

Manual Save creates a new period unless a list item was selected; Save changes
updates that item's ID. After saving, the next draft starts at the previous end,
with the Normal work type and no end or content yet entered. Clear input resets
the manual form and leaves stored records intact. In Auto Record it clears only
editable content, not the
timer or already saved descriptions. Delete is a per-item hover/focus action with
confirmation. Its space is reserved so revealing it does not resize the record.

Selecting an imported event creates a time-entry draft from its schedule and text.
Saving that draft creates worked-time data; it does not modify the source event.
Deleting a calendar event removes the local imported copy only. Re-importing its
source file may bring it back. The original file or calendar provider is untouched.

## Activity Types

| Type | Classification |
| --- | --- |
| Normal | Regular work not assigned a more specific activity |
| Remote | Work primarily identified by its remote working arrangement |
| Business trip | Work identified by a business trip |
| Meeting | A meeting or collaborative discussion |
| Training | A training or learning period |
| Break | Rest time, excluded from work and leave totals |
| Paid leave | Paid absence, included in leave totals only |
| Compensatory leave | Compensatory absence, included in leave totals only |
| Sick leave | Health-related absence, included in leave totals only |
| Other | Miscellaneous work outside the specific categories; shown last |

There are no duplicate labels for meeting/conference, training/learning, or rest.
The retained remote/trip categories describe an arrangement rather than a task;
choose the primary category and put additional context in Content. A separate
location dimension would be a future schema change, not an implicit second type.

Settings > General > Manage work types creates account-owned custom types. Each
has a name and a Work, Break, or Leave accounting category. Work contributes to
worked hours, Break contributes only to rest-date counts, and Leave contributes
to leave totals. The selector retains one classification dimension; use Content
for additional context. Other remains the last choice.

Each saved period and active timer keeps a name/category snapshot. Renaming,
changing, or archiving a type affects new records only. Editing an existing period
without changing its selected type preserves the snapshot, even if archived.
Archived types cannot be chosen for new periods. Active names are unique per
account after Unicode normalization and case folding.
The recorder only selects a type. Returning from type management refreshes its
choices without clearing entered times/content or changing a running timer's
saved classification.

The calendar's date, mode/time controls, and Save/Clear actions remain outside
the editor scroll area. The record list scrolls independently, without an outer
scroll area enclosing the complete right panel.
The right column grows within a 300-to-380 logical-pixel range. Editor rows remain
top-aligned and height-bounded, so taller windows give their extra space to the
record list rather than expanding gaps between labels and fields.

## Automatic Recording

The system tray and macOS menu-bar menu offer Start recording and End recording.
Their enabled states follow the same account timer as the editor. Start is available
only when idle and restored successfully; End only while a timer exists. Both are
disabled during a record operation. They reuse the editor's background workflow,
captured boundaries, overlap validation, and break confirmation. Tray actions use
the automatic type/content draft without overwriting manual input or opening the
main window unnecessarily.

Start persists an active timer with its chosen type and content. The type is fixed
for that period. Save content persists the description without creating a finished
time row. End stores time and current content together and clears the timer.
Following End, Save content can update that completed row without inserting another.
Successful End resets the type selector to Normal for the next timer without
changing the completed record's type. Saving content while a timer is running
does not change its type. Failed saves and failed End operations preserve the
selected type for correction or retry.

Discard timer is a separate button beside the break control. It asks for confirmation
before removing an active or unrecoverable timer without saving a completed period.

Break is available only when no timer is running. It immediately saves an independent
Break record from the captured click time to that time plus the account's default
duration, including current Content. It does not start a timer or resume work at
the end. Finish the current timer before using the shortcut. Overlapping periods
are rejected. A zero default disables the shortcut; manual break periods remain
available. A break
chosen directly as the activity type is a measured period.

Starting work during a shortcut break offers to end it early. Confirmation shortens
that record to the original Start click time and starts work at the same instant
in one transaction. Cancellation changes neither record nor timer. If no rest time
has elapsed, the unused break record is removed instead of saving a zero-length
period. Revision and timer checks reject stale or competing requests. Only shortcut
breaks identified by their capture ID are eligible; manual and imported records
are never automatically shortened.

Previously persisted scheduled break timers remain readable. They retain their
saved deadline and resume the original activity there rather than extending the
break until application reopening. The shortcut no longer creates such timers.

Only one account timer may be active. Its capture ID, offset-aware start, description,
type, and break/resume state are stored in the database. A period write and the
corresponding timer-state transition share one transaction. Failure preserves the
previous state and prevents a partial transition. A failed background deadline
operation stops automatic retries until user interaction, avoiding repeated dialogs.

Work writes run through the desktop job runner. Inputs and conflicting actions are
serialized; user-triggered timer boundaries are captured before queue submission,
so worker delay does not shift the recorded click time. Controls are
disabled until completion, and normal closing waits for the operation. Idle panels
do not run a timer, and closing a window stops its UI refresh timer. Content typed
after the last Save content remains a local draft until Save content or End;
normal navigation/closing handles unsaved input deliberately.

## Validation and Totals

New periods require both clock times and a positive elapsed interval of at most
16 hours. Overnight entries keep their start date for accounting compatibility.
Captured timestamps preserve real elapsed time in UTC; manual edits use the
system's named timezone. Content-only edits preserve original timestamps.

Periods must not overlap, including adjacent-date overnight records and the active
timer's reserved interval. Touching endpoints are valid. Imported scheduled events
are not part of this overlap restriction. Updates/deletions check ownership and
revision; a stale editor cannot recreate a deleted record or replace a newer edit.

Worked hours sum the individual work periods. Breaks contribute zero. Timed leave
uses its duration; historical untimed leave retains the standard-day convention.
Work-day counts and overtime are calculated once per date, not once per period.
Type breakdowns use individual activities rather than the day's generic summary.
Reports list each component period, including its type and content. Separate
daily notes are included only with explicit per-date permission. CSV and
iCalendar retain individual periods; iCalendar identifiers include the entry ID.

## Compatibility

Projects and work items are optional record context. Manage them under Settings >
General > Projects; the recorder provides only selection. Manual and automatic
records save their context labels, and active timing keeps the captured context
until completion. Catalog archival hides a choice from new associations without
removing historical records. Editing old content preserves its existing association.
Unlinked labels imported from CSV remain visible and can be explicitly cleared or
assigned to a local project. Record history and generated reports show the context.


Migration 7 makes a complete private snapshot before converting populated daily
records. It copies times, content, offsets, and historical break deductions without
inventing break placement. Independent daily notes remain available. Previous
automatic drafts are converted on first account use, and malformed state is not
silently removed. Historical break deduction remains visible when editing that
record; splitting it requires assigning actual break periods rather than guessing.

The six existing CSV columns remain readable. Repeated dates now support distinct
nonoverlapping periods and an independent note-only row. Optional offset columns
continue to preserve elapsed time. Explicit CSV replacement replaces the imported
dates as a whole. Database backups contain the new IDs, revisions, and timer state.
The older daily-save API refuses to overwrite a multi-entry day; desktop editing
uses the individual-entry API. Compact mode uses the same recorder and history
widget, including individual selection and deletion. The previous daily editor
and its presentation timer classes are no longer used or shipped.

## Text Assistance

The month grid reads all 42 displayed dates, including records in adjacent months.
Weekly totals use this same visible range. Copying an imported event normalizes
the calendar-only end-of-day notation `24:00` to next-day `00:00`; the regular
record duration and overlap rules still apply, including the maximum shift length.


An available AI service adds a Polish text action to the Content heading. The
operation rewrites the current description on a background worker. Its result
remains a local draft until Save or End; times, types, and records are unchanged.
The general calendar chat entry point is not part of the recording workflow.
Current Polish text requests are single-turn operations. Repeating the command can
rewrite the latest draft, but does not carry prior conversation messages. Generic
chat handlers retain bounded history separately; they are not the polish workflow.
Collected AI context expands each daily summary into its individual periods and
includes work descriptions only when account privacy settings permit them. Memo
content additionally requires per-date approval.

## Improvement Options

These are design options, not implemented features.

| Priority | Improvement | Implementation direction and safeguards |
| --- | --- | --- |
| High | Split/merge periods and convert historical deductions | Add transactional commands operating on entry IDs/revisions. Ask the user for actual break boundaries, preserve total hours, and provide undo before changing history. |
| High | Separate activity from project and location | Add optional project/tag/location fields with explicit migration defaults. Preserve current type IDs on import and distinguish meeting/training from remote/trip context. |
| High | Measured versus scheduled breaks | Offer an explicit account preference for scheduled resumption or user-ended breaks. Store both planned and actual boundaries so reminders cannot silently change attendance data. |
| Medium | Timeline editing | Add a per-day timeline with keyboard-accessible resizing and splitting. Reuse the same overlap/CAS rules rather than duplicating validation in painting code. |
| Medium | Forgotten-timer reminders | Notify near the duration limit and after reopening a long-running timer. Require confirmation to correct the boundary; never silently shorten a period. |
| Medium | Cross-midnight daily allocation | Optionally distribute elapsed time across local-date boundaries while conserving UTC duration. Keep current start-date accounting as a documented default and compare changed report totals before activation. |
| Medium | Search and large histories | Add date/type/project filters and bounded paging. Benchmark representative histories before introducing a daily-summary cache with transactional invalidation. |
| Medium | Change recovery | Add reversible record operations and an optional debounced content draft. Keep explicit Save content behavior available and preserve failed/conflicting drafts separately from authoritative time rows. |
