# User Guide

## Project Statistics

Open **Analytics > Projects**, choose the inclusive date range and select **Apply**.
The summary separates work, rest and leave at project level with work-item detail
under each project. Select a project to browse all its records or a work item to
browse only that item's records.
Work-day counts are distinct dates within each group and must not be added across
groups. Historical break deductions remain separate from worked time. Overtime is
not apportioned to projects because its threshold applies to the whole day.
Select a row and **View records** to browse its paged records or open one in the
calendar editor. Archived associations remain visible. Imported, unlinked labels
remain distinct from owned catalog identifiers. Queries exceeding 50,000 records
are rejected rather than returning incomplete totals.

## Report Recovery and Sources

**Report versions** beside the report editor opens versions of that report only;
the right-hand **Saved reports** panel continues to list separate saved reports.
Preview a version, then **Restore version** and confirm. The restored content becomes
a new saved version. Unsaved editor content is replaced only after successful
recovery. A stale version rejects saving or recovery; reload before trying again.

The **Sources** tab lists the most recent generation time, language, daily threshold,
template fingerprint and record/note/event references. These references describe
generation inputs, not verification of later manual or AI edits. Older reports can
have unavailable source information. Current Markdown exports and saved daily-report
exports include this information; copying the editor copies its content only.
The preview lists at most 1,000 source references; Markdown export includes all
stored references. Version content loads only when selected.

## Data Location

**Settings > Data > Data location** shows the directory containing the active
database. **Open data directory** opens that folder using the operating system.
The path is selectable but not editable; opening it does not move or replace data.
Use the existing backup operation instead of copying an open SQLite database file.

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
supported system language, otherwise English. After the initial local administrator
account is created, configured Google and Microsoft buttons open the system browser
for sign-in. The settings icon beside each provider opens its application registration
configuration. These values come from the distributor or deployment administrator,
not from the user's account password; no source edit or rebuild is required.

In **Settings > Account > Linked identities**, choose a configured provider and
**Link**, then complete browser authorization. Signing in through an existing link
opens the same local account and retains its display name and data. An unlinked
identity creates a separate non-administrator account; matching email addresses
do not merge accounts. **Unlink** cannot remove the only usable sign-in method.
The cancel icon stops pending authorization without opening a session. Closing
an authorization dialog requests cancellation and waits for the bounded background
operation to finish. See [provider configuration and compatibility](identity-signin.md).

### Display Names

**Settings > Account** separates personal profile fields from sign-in and security
actions. Display name, login ID, role and avatar belong to the current account.
Password changes, linked identities and logout affect that account's sign-in.
The separate **User administration** group manages all accounts in the current
database and appears only for administrators when user management is available.
Ordinary users cannot open it, including through a direct workflow request;
business operations independently recheck the requesting account's permissions.

Login ID is the stable identifier entered at sign-in. Display name is an optional
personal name and does not change authentication or data ownership. In Settings >
Account, choose the pencil beside Display name, edit it, then use the checkmark to
save or the cross to cancel. Enter saves and Esc cancels while editing. Moving
focus does not save. Unsaved changes require confirmation before leaving; failed
saves retain input. Clear the name and save to use the login ID again.

Names support Unicode and spaces, allow up to 80 characters, and may be shared by
different accounts. User management shows both names and login IDs so identical
aliases remain distinguishable. Successful changes update the main and compact
interfaces immediately and survive restarting. New AI requests use the latest
preferred name without changing names in source text or past messages. Report
templates can use `{{display_name}}`; already-saved report content is not rewritten.

## Calendar

Use the month arrows or Today to choose a month, then select a date. The right
panel records individual periods and lists the selected day's time records and
imported calendar events. New time record opens an empty manual editor and focuses
the start time. Notes opens the selected date's separate memo. The calendar
does not expose a separate quick-log editor or a general AI chat window.

**Settings > General > Calendar display > Show recent context** controls the
history shortcut beside Project in both recording interfaces. It is enabled by
default, is stored per account, and takes effect immediately without changing
the current draft or removing saved project associations. Existing installations
retain the visible shortcut without a database schema change.

History shortcuts use the history-arrow icon; time selection and timer actions
retain the clock icon. Report generation uses a new-file icon, and project
statistics use a project-folder icon. Ordinary actions use a surface background
with a neutral outline, neutral text and medium weight. Primary save, creation,
sign-in and confirmation actions use a theme-colored background, white text and
semibold weight. Auxiliary actions use regular weight and a transparent background;
destructive actions use red text and matching icons. Selected navigation retains
theme-color emphasis. Disabled framed actions use muted text and icons with a distinct
background; frameless auxiliary actions keep their transparent contour. Both retain
their role's weight to avoid layout changes. Button icons
follow the text color rather than applying a separate accent color.

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
After saving, the record remains selected in both input modes. New time record or
Clear input resets the next draft to Normal. Selecting an
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
description without creating a finished period. When idle, Save changes updates
the selected record's content, type and project; use Manual Input for boundary
corrections. Unsaved manual boundary edits are not committed by an automatic-mode
content save.
After End succeeds, the completed record remains selected for review in both modes.
Use New time record or Clear input before entering another period. Saving content
during a timer does not change its classification or boundaries.

Break immediately saves a separate rest period starting at the click time and
ending after the configured default duration. It is available without pressing
Start, but disabled while a timer is running: finish that timer first. The record
appears in Schedule / Records immediately and can be edited in Manual Input.
No timer is started, and work does not resume automatically. Choose the type of the
next activity before Start, or use New time record to restore Normal. Clicking Start
during this rest period asks whether to end it early. Confirming shortens the rest
to the Start click time and begins the new timer at that same time; cancelling
keeps it unchanged.
Manual and imported periods are never automatically shortened. Other overlapping
records are rejected. A default duration of zero disables this shortcut; a manual
break can still be recorded.
The separate Discard timer button beside the break control asks for confirmation
before removing an unwanted or unrecoverable timer. Clearing the form does not
discard or stop it.

Manual and automatic modes share the selected record's content, classification and
project. A running timer keeps its own content when another historical record is
being edited; an unrelated unsaved manual draft is not silently overwritten.
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

The note toolbar orders polishing, export, copy and reload from left to right.
Copy and reload remain frameless when disabled; their icons become muted instead
of gaining a border. The icon targets keep the same size, and keyboard navigation
follows the displayed order.

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

The report export menu also provides Timesheet > Selected day/month in Excel or
PDF. This is a structured export of time records, separate from editor Markdown
and saved-daily-report aggregation. Multiple periods retain individual rows.


| Category | Available controls and behavior |
| --- | --- |
| Appearance | Native-language choices, preset/custom accent, light/dark mode; palette appears only for Custom |
| General | Separate rounded groups for work and recording, calendar display, and application behavior; existing preferences and management entries remain in this category |
| AI | Local model selection and native runtime, explicit external-model opt-in with HTTPS endpoint/model/key, sample connection test, and context privacy |
| Data | Work-log CSV and iCalendar export, CSV and calendar import, database backup/restore; clearing calendar events is disabled |
| Network | Enable and configure an HTTP CONNECT proxy; subsequent update, download, and external AI requests use it |
| Account | Personal profile, sign-in and security, and a separate user administration group visible only to authorized administrators |
| About | Version and author information, license display, repository link, manual update check |

Under AI > Local Model, Model context limit is read-only catalog metadata; Runtime
context is your account's adjustable local inference window. It defaults to 8,192
tokens and cannot exceed the selected model's declared limit. A smaller model
temporarily limits the effective value without overwriting your saved preference.
Changes apply on the next request, not during an active generation. Larger values
use more memory and may prevent loading. This control does not change the model
file, catalog, or external AI configuration.

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
It intentionally has no separate About subtitle. Checking disables only the
check button, retaining the application image's original colors.
