# Time Recording

## Interaction Model

The calendar is a period recorder, not a single daily shift form. Each completed
period has an account-scoped ID, start/end, activity type, content, and revision.
The right-side total shows worked time already stored for the selected date.
Scheduled calendar events are displayed separately and do not count as work.

New time record is the main action in the calendar header. It opens Manual Input,
clears the editing selection, and focuses the start field. A separate, full-height
menu button contains quick logs, independent daily notes, and AI assistance.
These actions are distinct from creating a time period.

Manual Save creates a new period unless a list item was selected; Save changes
updates that item's ID. After saving, the next draft starts at the previous end,
with no end or content yet entered. Clear input resets the manual form and leaves
stored records intact. In Auto Record it clears only editable content, not the
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

## Automatic Recording

Start persists an active timer with its chosen type and content. The type is fixed
for that period. Save content persists the description without creating a finished
time row. End stores time and current content together and clears the timer.
Following End, Save content can update that completed row without inserting another.

Discard timer is a separate button beside the break control. It asks for confirmation
before removing an active or unrecoverable timer without saving a completed period.

Break closes the work period and transitions to a separate break using the account's
default duration. The application resumes the previous work type at the configured
deadline. Resume work can end it early. If the application was closed, reopening
uses the saved deadline rather than extending the break until reopening. A zero
default disables the shortcut; manual break periods remain available. A break
chosen directly as the activity type is a measured period and has no scheduled
automatic resumption.

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
Reports list the component periods and preserve separate daily notes. CSV and
iCalendar retain individual periods; iCalendar identifiers include the entry ID.

## Compatibility

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
uses the individual-entry API. Compact mode uses the same recorder, while selection
and per-item deletion are available in the full calendar list.

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
