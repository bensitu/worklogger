# User Guide

Weekly reports and analytics week groups follow the account's week-start setting.
Daily reports cover one day, weekly reports cover seven days starting on Sunday or
Monday, and monthly reports cover a complete calendar month. Generated report text
uses the selected language; multiline notes retain Markdown list indentation.

## Accounts

Create a local account on first use. The first registered account receives
administrator permissions. New passwords require at least eight characters. Keep
the recovery key displayed after registration; password recovery uses this key,
not an email service.

Enter your ID and password, then press Enter or choose Login. The eye icon changes
password visibility. Remember me stores a local session credential with a
30-day expiry recorded in the local database. Repeated failed logins cause
temporary lockouts. See [security behavior](security.md).

The login language uses the previous explicit language choice, otherwise a
supported system language, otherwise English. Google and Microsoft login buttons
are disabled in the standard application.

## Calendar

Use the month arrows or Today to choose a month, then select a date. The right
panel records individual periods and lists the selected day's time records and
imported calendar events. New time record opens an empty manual editor and focuses
the start time. Notes opens the selected date's separate memo. The calendar
does not expose a separate quick-log editor or a general AI chat window.

### Manual Entry

1. Select Manual Input and enter start and end times. The clock icon opens the
   time-selection control.
2. Select the work type and optionally describe the activity in Content.
3. Save the period. Repeat with another nonoverlapping period on the same date.

A date can contain multiple records with independent IDs. Select a record to edit
it in Manual Input; saving preserves its ID. Use New time record to start another
period. Clear input resets the editor without deleting saved records; in Auto
Record it clears content without stopping the timer. A record's delete button
appears on hover or keyboard focus and requires confirmation.
Successful time-entry saves update the calendar without a confirmation popup.
After saving, the work type resets to Normal for the next record. Selecting an
existing record still loads its saved type for editing.

The maximum elapsed period is 16 hours. Historical break deductions must be
nonnegative and shorter than that period; new breaks are separate records.
An end time earlier than the start
means the next day, for example `22:00` to `06:00`. Equal times represent a 24-hour
interval and therefore fail the maximum-length check. New time entries require
both times. Daily notes remain independent; historical untimed leave remains
readable and its content can be edited without inventing times.

Work types are normal work, remote work, business trip, meeting, training, break,
paid leave, compensatory leave, sick leave, and Other. Other appears last and counts
as worked time. Breaks do not count as work or leave. Leave is accounted for
separately from worked hours.
Settings > General > Manage work types adds custom account classifications. Assign
each to Work, Break, or Leave. Names and accounting categories are saved with each
period; later catalog edits and archiving do not change historical totals.

### Automatic Entry

Choose a work type, enter optional content, and choose Start. End saves the timed
record and its current content automatically. Save content updates the timer's
description without creating a finished period; after End it updates that same
saved record's description. Edit a completed record through Manual Input.
After End succeeds, the work type resets to Normal for the next timer; the saved
record keeps its original type. Saving content during a timer does not reset it.

Break immediately saves a separate rest period starting at the click time and
ending after the configured default duration. It is available without pressing
Start, but disabled while a timer is running: finish that timer first. The record
appears in Schedule / Records immediately and can be edited in Manual Input.
No timer is started, and work does not resume automatically. Clicking Start during
this rest period asks whether to end it early. Confirming shortens the rest to the
Start click time and begins work at that same time; cancelling keeps it unchanged.
Manual and imported periods are never automatically shortened. Other overlapping
records are rejected. A default duration of zero disables this shortcut; a manual
break can still be recorded.
The separate Discard timer button beside the break control asks for confirmation
before removing an unwanted or unrecoverable timer. Clearing the form does not
discard or stop it.

Manual and automatic editors preserve their separate drafts when switching modes.
Calendar refreshes do not replace the active timer's content. The type is fixed
during a running period; finish it before choosing the next activity.
Clock Out rejects invalid or excessive elapsed intervals rather than wrapping
them into a shorter shift. The active record keeps its original date when the
calendar selection changes.

The timer is not a background service. Its start, break boundaries, note, work
type, and completed unsaved draft are nevertheless stored per account in the
database. Reopening restores the original date and elapsed break. A new timer
cannot replace another active timer. Completing a period stores its time and
clears or transitions the timer in one transaction. Failed state writes retain
the previous state and show an error. Invalid stored state is not silently deleted;
starting a replacement requires confirmation. System-date changes update the
calendar's Today indicator without discarding the selected date or draft.

Historical records retain their original break deduction, shown in the editor;
the software does not invent a break location. Deleting an imported event affects
only the local copy. Selecting an imported event creates a manual time-entry draft,
not an edit to the source calendar file. Imported events themselves contribute no
worked hours. See [time-recording details and improvement options](time-recording.md).

### Holidays and Markers

Enable holiday display in Settings > General. Choose a country and an optional
state/province, or keep System region to infer the country from the system's named
timezone. Unknown or country-neutral timezones do not select another country's holidays.
Holiday names come from the holiday data library and may not match the interface
language. A holiday is not an imported event and does not create a work record.

Cells can show notes, overnight work, event counts, and work-type indicators.
Markers and daily totals are visual summaries, not additional entries.

## User Administration

Settings > Account displays an avatar below Role. Change avatar accepts PNG,
JPEG, WebP, or BMP images up to 10 MiB and 20 million pixels. Drag the circular
preview and adjust Zoom; arrow keys also move the crop. Save stores a normalized
256-pixel PNG for this account, without the original path or image metadata.
The sidebar updates immediately and retains a circular display after restarting.
Use default avatar removes the custom selection. Avatar pixels are included in
database backups; they are not an operating-system credential.

Settings > Account asks for confirmation before logging out. Changing the password
replaces the recovery key. After a successful change, copy or save the new key
before continuing; the saved file is not encrypted. The previous key no longer
recovers the account.

Administrators can open Manage users from Settings > Account. The left-hand table
selects the account shown in the Selected user panel. Password-change requirements,
password resets, and deletion apply to that selection. Refreshing keeps the same
selected account when it still exists. Create user opens a separate form; after
creation, the new account is selected and its recovery key is displayed. Resetting
shows the supplied temporary password, and changing the selected account clears
credential text and unfinished reset fields. Deletion requires confirmation and
still enforces the existing account-protection rules.
Recovery keys issued during registration, password recovery, or administrator
account creation use the same copy and plain-text save controls as password
changes. Administrator resets provide a separate temporary-password handoff.
The account detail panel temporarily replaces reset fields with that result;
Back to account returns to editing and clears the displayed credential.

## Notes

Use Notes for extra matters that do not belong to a work period. Search finds
saved notes and previous quick-log descriptions. Previous entries remain readable
and can be transferred into a saved note without converting them to work time.
Add to note asks for confirmation: it saves the current note and removes the
original entries only if that save succeeds. Cancelling or encountering a conflict
preserves the source entries. The editor supports
draft recovery, copying, Markdown export, and optional text polishing. Templates
belong to Reports and cannot be changed from the memo editor.

Notes are private by default. Allow in reports and Allow in AI context are explicit
per-date choices; AI collection also respects the account's privacy settings.
Concurrent changes reject stale saves. Closing edited text offers to keep its draft,
discard it, or cancel. Deleting a time record does not delete its day's memo.
See [daily notes](daily-notes.md) for recovery and sharing behavior.

## Reports

Choose a daily, weekly, or monthly period. Weekly periods follow the calendar's
Sunday-first or Monday-first preference. Generate
a report from the period's individual work records, previous quick logs,
approved daily notes, and calendar events, then
edit and save it. Select a history item to reopen saved content.
Polish text edits the current report draft without changing recorded work time.
History items display the report period, the first save date and time in your
local time zone, and a report number that distinguishes multiple reports saved
in the same second. Editing an existing report and saving it asks for confirmation
before replacing that report's content. Declining keeps the edited text without
changing the saved report. Saving unchanged content does nothing. The report
number and first save time remain unchanged when its content is replaced.

Each saved history item exposes a Delete report button on hover or keyboard focus.
Deletion requires confirmation and affects only that account's selected report.
Deleting the open report clears its editor and saved identity; deleting another
report preserves the current draft. If the stored content has changed elsewhere,
deletion is rejected so that you can reload and review it first. A storage failure
retains the report and editor content.

Report content is saved Markdown, not a live query. Changing a work record does
not rewrite an already saved report. Generate or edit it again when needed.
Template changes are scoped by account, language, and report type. Exported
Markdown is an unencrypted document. See [templates](templates.md).
The editor identifies generated drafts and saved report numbers, and marks
unsaved changes. Generate from records rebuilds the visible content without
changing the saved report until Save changes succeeds. Cancelling or failing
generation preserves the visible draft. Export current report is beside Copy and
Save; it exports the visible content, including unsaved edits, not the history
list. Suggested filenames identify the period and saved report number or draft.

## Analytics

Choose monthly, quarterly, or annual scope and navigate between periods. The
dashboard displays worked hours, overtime, work days, averages, work types, and
comparisons with the preceding period. Leave is represented separately. The
configured monthly target is multiplied by the number of months in the period.
Period selectors retain recent periods when you switch scopes after viewing
historical data, including the current month, quarter, and year.
Rest Days counts distinct record dates containing a positive-duration Break
entry, not dates with missing work records. Multiple breaks on one date count
once; work and rest counts can overlap. Leave and historical break deductions
are separate, and unrecorded or future dates are not inferred to be rest days.

The Daily Average chart displays the six months ending in the selected month for
monthly scope, all four quarters of the selected year for quarterly scope, and
January through December of the selected year for annual scope. Each point is
total worked hours divided by the number of days with positive worked hours in
that interval. Leave and zero-hour records are excluded; empty intervals show
zero. The value above the chart and its comparison refer to the selected period.

The hours card is titled Monthly Hours, Quarterly Hours, or Annual Hours to match
the selected period. Its percentage is not capped at 100%. The inner ring shows
the first 100%, with another concentric ring for each additional 100% interval.
For example, 250% displays two full rings and a half-filled third ring. Rings
become thinner as their number increases, keeping the card size unchanged. The
compact chart displays at most 32 rings; the percentage always shows the actual
rounded value. A zero target displays 0% rather than an undefined ratio.

The overtime card compares the previous period (left, muted bar) with the current
period (right, colored bar), using a shared scale. Hover over the chart to read
both values. Zero overtime produces no filled bar.

CSV and PDF exports contain computed analytics. They are not database backups and
the analytics CSV is not the same format as the work-log import CSV. PDF provides
a paginated Unicode text summary, not the chart. See [data formats](data-formats.md).

## Settings

| Category | Available controls and behavior |
| --- | --- |
| Appearance | Native-language choices, preset/custom accent, light/dark mode; palette appears only for Custom |
| General | Standard hours, default break, monthly target, holidays, week start, overnight display, platform residency |
| AI | Local model selection and native runtime, explicit external-model opt-in with HTTPS endpoint/model/key, sample connection test, and context privacy |
| Data | Work-log CSV and iCalendar export, CSV and calendar import, database backup/restore; clearing calendar events is disabled |
| Network | Enable and configure an HTTP CONNECT proxy; subsequent update, download, and external AI requests use it |
| Account | Current account, password change, identities, administrator tools when authorized, logout |
| About | Version and author information, license display, repository link, manual update check |

Most settings save when changed. Language changes take effect after restart or
the next login rather than rebuilding the open interface immediately. Appearance
and calendar preferences update the active window.
Unavailable services do not discard their stored settings or credentials. A
verified selected model file is not presented as an active inference service.
Settings switches can receive keyboard focus and toggle with Space; native
accessibility exposes their name and checked state.

## Backups and Updates

Administrators can use Settings > Data to create a database backup. It includes all accounts and
their stored records, not only the signed-in user's data. It does not include model
files, operating-system credentials, language preferences, or the remembered-login
file. Store backups privately.

Restore replaces the database rather than merging records. The file must pass
integrity and schema checks and contain the current username with the same account
ID. Restore requires administrator permission, retains the previous database, and
ends the session so you can sign in again. Keep a separate known-good backup.

Check for Updates contacts the configured GitHub release endpoint. It does not
download or install an application update automatically.
The About page reserves a status area beneath the check button, so checking,
completion, and error messages do not reposition the application information.
