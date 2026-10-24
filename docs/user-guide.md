# User Guide

## Accounts

On an installation without accounts, a welcome page explains local accounts and
the recovery key before opening account creation. Choosing Create my account
opens the form; Exit closes setup without creating an account. When another user
chooses Create account from sign-in, the same account and recovery information
appears above the registration fields.

Create a local account on first use when registration is allowed. The first
account is an administrator. Managed installations may disable self-registration;
an empty database then needs administrator-authorized setup or a prepared database.
Startup assistance provides guidance without enabling registration automatically.
New login IDs may contain up to 120 characters. Existing longer IDs remain valid
for sign-in and account recovery.
Passwords require at least eight characters. Recovery uses the saved recovery
key, so copy or save it privately when it is displayed.

After registration, save or copy the recovery key before choosing Saved safely,
start using WorkLogger. This key resets a forgotten password; it is not the
sign-in password. Saving creates an unencrypted text file, so choose a private
location. WorkLogger does not require saving a file if the key has been stored
safely elsewhere.

Each new account receives a short, nonmodal introduction after the main window
and recording editor are ready. Record a time period opens a new manual record;
it does not save sample data. Maybe later dismisses the introduction for that
account. Use Help in the main sidebar, or the Getting started information button
in compact view, to open it again. The User guide action opens this guide in
your browser. Existing accounts are not automatically shown the introduction
after an upgrade. Administrator-created and external sign-in accounts receive
the introduction on first use, after any required password change.

Sign in with your login ID and password. **Remember me** retains a local session
credential for up to 30 days. Repeated failed attempts cause temporary lockouts.
The sign-in window can be resized. On smaller screens, scroll the form to reach
provider sign-in and account recovery actions.

**Settings > Account** groups personal profile, sign-in/security, and user
administration separately:

- Display name is an optional alias, independent of your login ID. Choose its
  pencil icon to edit, then save or cancel. Enter saves; Esc cancels. Clear the
  alias to display your login ID. AI requests and generated report author fields
  use the preferred name; existing saved content is unchanged.
- Change avatar accepts PNG, JPEG, WebP, or BMP up to 10 MiB and 20 million pixels.
  Position the circular crop by dragging or using arrow keys, adjust Zoom, and
  save. Use default avatar restores the original image.
- Changing a password replaces its recovery key and remembered credentials.
  Store the new recovery key before continuing.
- Logout asks for confirmation.
- Administrators use Manage users to create accounts, reset passwords, require
  password changes, or delete accounts. Check the selected login ID before acting.
  A reset supplies a temporary password; the user must change it before proceeding.

To retain existing records with Google or Microsoft sign-in, sign in locally,
open **Linked identities**, and link the provider. Signing in with an unlinked
identity creates a separate account only when self-registration is enabled;
matching names or emails do not merge data. OIDC can be disabled by deployment
policy. Link the identity to the existing local account before using it to sign in.
See [browser sign-in](identity-signin.md) for provider registration.

Linking or unlinking requires the current local password. Accounts without a
local password must reauthenticate an already linked identity. The provider must
confirm a recent authentication time; cancelling leaves identities unchanged.

AI note-sharing permission also controls project and work-item labels in work-log
context. When disabled, durations and classifications remain available, but
record content and project labels are excluded.

For current-account cloud storage, schedules, encryption, and recovery, see
[personal cloud backups](cloud-backups.md).

## Recording Time

Select a date in Calendar. The right panel shows its editor and saved records.
**New time record** starts another record; selecting a saved record edits it.
**Clear input** resets a draft without deleting saved records.

### Manual Input

1. Enter start and end times.
2. Open Classification. Under Work, choose a period type, optional work
   arrangement, project, and work item; use Leave for a leave type.
3. Enter Content and save.

Each date can contain multiple nonoverlapping records. After saving, the record
remains selected for editing. Classification selections remain temporary until
Apply; Cancel, Esc, and clicking outside the popup leave the draft unchanged.
Apply updates only the draft; Save writes the record. Break and leave use the
same start/end fields and do not carry a work arrangement or project. Untimed
historical leave remains editable without invented time boundaries.

New work records default to the account's last successfully saved work arrangement,
or Not specified. Selecting Not specified and saving a new work record clears
that default. Editing an existing record never changes another record's arrangement
or the new-record default. Historical remote and business-trip classifications
retain their original meaning until explicitly changed to a current period type.

If a manually entered period overlaps saved records, review the replacement
preview. **Replace overlapping time only** preserves time outside the new period,
splitting existing records when necessary. For example, adding a 12:00-13:00
break to a 09:00-18:00 meeting produces 09:00-12:00 meeting, 12:00-13:00 break,
and 13:00-18:00 meeting, with eight worked hours. Preserved parts retain their
type, content, and project. **Replace entire overlapping records** removes the
complete conflicting records, including time outside the new period. Confirm
with **Replace and save**, or cancel to keep existing records and the current input.
Finish or discard any active timer before replacing records. A changed record
or a new conflict prevents replacement; reload and review it again.

An end time earlier than the start means the following day, such as 22:00 to
06:00. A period cannot exceed 16 hours. Equal start/end times represent 24 hours
and are rejected. Timed records require both boundaries.

### Auto Record

Choose a work or break period type and content, then Start. Work can also have
an arrangement and project context; breaks cannot.
Leave is entered manually.
Classification and project associations are locked while a timer runs.
End saves the finished period and
its content. Save content updates an active timer without ending it. When idle,
Save changes updates the selected record's content and classification; use Manual
Input to correct time boundaries.

The timer retains its start and account across restarts. Editing another date
does not move it. Discard timer asks for confirmation before removing it.
Clearing content does not stop or discard the timer. A completed work timer remembers
its arrangement for new work records; starting or discarding a timer does not.
If an automatic save fails, the elapsed-time display continues and the timer
retries after a short delay. Unsaved timer state is retained.

The Break shortcut creates a separate rest record for the default break duration;
it does not start a timer. To measure an actual break, select a break type under
Classification and use Start and End. Both approaches exclude rest from worked
hours and leave the remembered work arrangement unchanged. Finish an
active timer first. Starting a timer during a shortcut-created break asks whether to
end that break early; ordinary saved records are never shortened automatically.
A zero default break disables the shortcut.

Configure long-timer and continuous-work reminders in **Settings > General**.
If a timer exceeds the allowed interval, correct its end time or discard it
deliberately. Reminders do not certify compliance with working-time regulations.

### Types, Projects, and Corrections

Manage entry types, work arrangements, and projects in **Settings > General > Classification**. Custom types have Work,
Break, or Leave accounting. Saved records retain their original classification
and labels when catalog entries are renamed or archived.
Use **Manage work arrangements** to add, rename, or archive an arrangement. It is
available in the work classification picker for both manual and automatic input.
Archived arrangements are hidden for new records; existing records and running
timers retain their saved name. Work arrangements do not change hour accounting
and cannot be attached to break or leave records.

Calendar dates use one thin indicator along the bottom. A single type occupies
the line; mixed types share it in proportion to their classified durations.
Work classifications and arrangements use gray or muted cool colors, leave uses
muted warm colors, and break uses soft green colors. Built-in and custom choices
share these category palettes in menus, calendar indicators, and charts. A custom
ID selects a stable variation within its category, not a new random color on each
launch. Renaming does not change its color; changing its accounting category
changes the color family for new records without changing historical snapshots.
Color supplements the visible names; it is not a unique identifier for each type.
Work uses effective worked hours, break uses recorded
duration, and leave uses its leave-hour calculation, including historical untimed
leave. Historical deductions are not counted again as break records. Custom type
colors remain stable when renamed. Type menus use the same theme-aware colors.
The indicator does not add another click target or a classification hover panel.

Click the calendar month heading to jump to another month or year using the
shared date picker. Calendar dates continue to show worked hours, including
`0.0h`; the extra overtime line appears only when the displayed overtime is positive.

Record search opens with all records in the month currently displayed in Calendar,
newest first. Choose Month, Year, Custom range, or All dates; content and context
filters apply to the entire selected range before paging, not just visible rows.
The Project menu includes No linked project, which selects only records without
a linked project, including imported records that retain a historical project
label. All projects includes both linked and unlinked records. Work-item filtering
is available when the selected project has work items.
Open a result in Calendar. Recent context reuses an active project/work-item
selection. Batch assignment requires an explicit selection and confirmation.

Record actions can split a period, merge adjacent compatible periods, place a
historical break deduction, or undo a supported change. **Split record** accepts
a clock time and previews both resulting periods. Confirm an edited time with
the check icon or Enter before applying the split; the restore icon discards an
unconfirmed time change. The clock icon opens time selection. A date selector
appears only when the original period spans dates; choose the following date
to split an overnight record after midnight. Historical deductions have no
known break position until you assign one: choose **Place historical break** and
set its start time before splitting or partially replacing that record. Confirm
the preview before applying a correction. **Undo latest record change** can
restore an overlap replacement, including all affected records. CSV replacements
also record eligible time-record changes for undo, grouped by affected date.
Independent memo changes and whole-database restoration are not covered. Undo is
limited to retained changes and rejects records that have changed since the operation.

For an overnight period such as October 31, 22:00 to November 1, 06:00, choose
November 1, 00:00 as the split time to create two periods of two and six hours.
To insert a 00:00-01:00 break, select November 1 in Calendar, start a new time
record, enter the break, and choose **Replace overlapping time only**. The
remaining work periods are October 31, 22:00-00:00 and November 1, 01:00-06:00,
totaling seven worked hours. A break that itself crosses midnight, such as
23:30-00:30, starts on October 31. Each resulting record belongs to its start
date; daily and monthly totals are recalculated accordingly. Month and year
boundaries use the same rules.

The overlap preview aligns the new period above the existing records on a shared
time scale. Segment colors follow entry types; Normal uses gray and
Break uses a soft green color. Gaps remain visible. Whole-record replacement fades
the existing segments, while the new period remains opaque. The result table is
the complete list of records to save.

Imported calendar events are separate from worked time. Selecting one creates a
time-entry draft. Editing or deleting the local copy does not alter its source file.
All-day events require explicit start and end times before saving as worked time.
Holiday display and the first day of the week are controlled in General settings.

Calendar imports are bounded before recurrence expansion. Repeated events must
use daily or less frequent rules with an end date or count. Finite series can
span more than ten years when they fit within the event and processing budgets.
Event titles, descriptions, and locations are limited to 1 KiB, 64 KiB, and
4 KiB respectively; the expanded event content is limited to 16 MiB. Imports
that exceed these limits are rejected without changing existing events.

## Notes

Notes are independent date-specific memos and do not contribute hours. The
history opens at the month selected in the main calendar. Browse by month,
year, custom date range, or all dates. Use the period arrows or click the period
to select another month or year. Results are newest first; Load more retrieves
the next batch of dates for longer ranges, with 50 dates per batch by default.
Deployment page sizes are described in [configuration](configuration.md#deployment-configuration).

Search finds saved notes and retained previous entries within the selected
date range. Matching uses the full saved content before pagination, not just
the previews already loaded. Select **All dates** to browse or search across
years. Changing the range keeps the search text; clearing the search keeps the
selected range.
A loading indicator appears while results are being retrieved. Range selection,
search, and note editing remain available during loading.

Filtering never replaces the open note. Opening another date offers to keep
any unsaved draft. Copy and export operate on the open note; Reload saved note
discards its local draft.

Use **Delete note** to remove the open date's note and its draft after
confirmation. Its sharing choices are also removed. Time records, calendar
events, and retained previous entries are not deleted. A date may remain in
the list if it still has previous entries. Changes made in another editor
prevent deletion until the note is reloaded.

Dates with saved note content show a calendar dot even when they also contain
time records or scheduled events. When an overnight moon icon is present, the
dot appears to its left on the same row.

Drafts are retained after a typing pause. Closing edited text offers Keep draft,
Discard, or Cancel. Conflicting saves preserve your input; reload and compare
before replacing someone else's changes.
If a draft cannot be read, the saved note is displayed without removing the
draft. Reload explicitly discards it; saving edited content replaces it.

**Allow in reports** and **Allow in AI context** are separate per-date choices and
default to off. AI sharing also requires the account privacy setting.
Deleting a time record does not delete its date's note.

If Previous entries are shown, Add to note asks for confirmation. It saves the
memo and removes those source entries together; cancellation or failure retains
them. It does not create worked-time records.

## Reports

Choose a daily, weekly, or monthly period. Weekly periods follow the week-start
preference. Generate from records builds a draft from records, calendar events,
and notes approved for reports. Edit and save it. Templates selects the language
and report type; Save and apply saves the template and regenerates the draft.
See [template variables](templates.md).

Saved reports lists the current account's reports of the selected type. Daily
reports support week, month, year, custom, and all-date ranges. Weekly reports
support month, year, custom, and all-date ranges; monthly reports support year,
custom, and all-date ranges. Daily and weekly history initially follow the viewed
month; monthly history initially follows the viewed year. Week ranges follow the
week-start preference. Ranges match report periods, not save timestamps. A weekly
report spanning two months appears in both intersecting month ranges.

Choose ascending or descending report dates or first-save times. Report date,
newest first, is the default. Search matches report content, ISO dates, save
timestamps, and identifiers, including `#123`, throughout the selected range.
The list loads 50 summaries at a time by default; Load more continues the same query.
The batch size can be changed in the deployment configuration.
Search is not restricted to summaries already loaded. Selecting a summary reads
the report's latest saved content. Changing history filters does not discard the
open draft; opening another report still asks about unsaved changes.

Saving edited content asks before replacing that report and creates a new saved
version. Report versions applies to the open report only. Restoring a version
creates another version, rather than erasing later versions.

Sources describes the inputs used during generation, not verification of later
manual or AI edits. Saved report text does not change when work records change.

The export menu distinguishes:

- Current report: the editor's Markdown, including unsaved edits.
- Selected day's saved daily report.
- The month's saved daily reports: the newest saved report for each date,
  ordered by date.
- Timesheet for the selected day or month: time-record tables as XLSX or PDF,
  separate from narrative reports.

Exports do not save the current draft. See [data formats](data-formats.md).

## Analytics

Choose a month, quarter, or year. Worked hours exclude recorded rest and leave.
Overtime uses the daily standard-hours threshold. Daily average is worked hours
divided by dates with positive worked hours, not all dates in the period.

Actual attendance shows dates with positive worked hours and retains the dot
visualization. Planned work appears beside the previous-period comparison, not
as an attendance percentage. It is based on the weekly schedule in
General settings, with half days counted as 0.5. The dots are a calendar-period
overview, not a percentage of planned attendance. Work on a planned day off still
counts as attendance. Comparisons use the previous full calendar period; week
labels include their in-month date ranges. See [configuration](configuration.md)
for schedule options and holiday handling. Enabled regional holidays are excluded
from planned work; disabling holiday display also disables this exclusion.

Classification breakdown uses each recorded type's duration, including recorded
breaks and leave. Switch that chart to Work arrangement to group only actual
worked hours; unspecified arrangements remain separate. These are independent
views of the same records, not totals to add together. A two-hour remote meeting
is two worked hours, two hours classified as Meeting, and two hours under Remote.

Rest Days counts distinct dates with a positive-duration Break record. Multiple
breaks count once; a date can count as both a work day and a rest day. Missing
records do not imply rest, and leave is counted separately. Historical deducted
breaks are not separate rest-day records.

Custom monthly goals are multiplied by the number of months in the selected period.
Automatic goals use the period's planned workdays, excluding enabled regional
holidays, multiplied by daily standard hours. Configure the mode under General >
Hours goal; switching modes retains the custom value. Unavailable holiday data is
reported without replacing the automatic target with an unadjusted estimate.
Project statistics separates work, rest, and leave by project and work item.
Only work records can be linked to a project; break and leave remain unlinked.
Distinct-day counts cannot be added across groups; overtime is a whole-day measure.

CSV and PDF export calculated summaries. They are not work-log import files or
database backups.

## Settings and Optional Services

Appearance controls language, theme, light/dark mode, and the startup view when
minimal view is available. Language and view changes take effect after restarting
or signing in again. Most other settings save when changed.

Liquid Glass adds frosted, refractive panel backgrounds in light and dark mode.
It uses the application's own background, not desktop screenshots. Text editors
and tables retain readable surfaces. All platforms use the same PyGlass rendering
core adapted for PySide6, including the sidebar.
Glass surfaces retain a tint for text contrast even at full background opacity.

On macOS, the application menu provides About, Settings (Command+,), and Quit
(Command+Q). File provides New time record (Command+N), Save (Command+S), and
Close window (Command+W). Save uses the current record, report, note, or other
editor's existing save action; settings that save automatically do not require
this command. Closing and quitting retain the usual unsaved-change confirmation.

Edit commands apply to the focused text field. Read-only fields and hidden
password fields retain their editing and clipboard restrictions. View opens the
available pages; unsupported pages are disabled in minimal view. Window provides
Minimize (Command+M) and Show main window. Help opens the project homepage or the
issue reporting page.

Minimal view provides time recording, the selected day's records, Notes, and the
complete Settings dialog. Use New time record to start another entry; selecting
a saved record loads it for editing. Enable or disable Minimal view in Appearance
to choose the view for your next startup or sign-in. Account permissions and
stored records are the same in both views.

When Background image is available, enable its switch to show upload and opacity
controls. Until an image is uploaded, the normal theme background remains.
Disabling keeps the image; removing it keeps the enabled preference and opacity.
Images cover the four main pages or the minimal recording window, not the sidebar
or separate dialogs.
See [configuration](configuration.md) for formats and deployment controls.

Enable AI Assist and configure either a selected local model or an external
service before polishing text. Requests show progress and can be cancelled.
Review the proposed text before using it; polishing does not save records or
change recorded hours. See [local models](local-models.md) and
[AI configuration](configuration.md#ai).

Polishing keeps time records concise, preserves lists and checklists in notes,
and retains Markdown structure in reports. Instructions require preserving facts
and completion status without inventing achievements, risks, or plans. Local
models receive compact instructions; external services receive more detailed
instructions. These constraints do not guarantee factual accuracy, so compare
the result with the original before saving. Generate from records uses templates,
not an AI request.

AI rewriting keeps the source text's language regardless of the interface
language. AI-generated summaries and reports also follow the supplied notes'
language. To translate, explicitly request the output language in the report's
extra instructions or your AI Assist message. Mixed-language passages are
preserved when no translation is requested.

Network settings apply an account HTTP CONNECT proxy to supported HTTPS requests.
This includes updates, model catalog refreshes and downloads, external AI, cloud
backups, and application-side identity requests after sign-in. They do not change
the operating system or browser proxy; authentication before account selection
uses direct HTTPS. See [network routing](configuration.md#network) for boundaries.

On supported platforms, enabling tray/menu-bar residency keeps a closed window
available through its icon. The menu can start a timer when idle or end an active
timer.

## Backups and Updates

**Settings > Data > Local data location** identifies the active database directory.
Opening it does not move data. Use Backup Data instead of copying a live database
without its journal files.

Administrators can back up all accounts and restore a compatible database.
Restore replaces the database, retains the previous copy, and ends the session.
The backup must contain the administrator's login ID with the same account ID.
Model files, OS credentials, and remembered-login files require separate handling.
See [database safety](database.md).

Startup assistance offers retry and diagnostic actions for permission, storage,
logging, and initial-account problems. Database recovery separately supports a
validated backup or retaining existing files and creating an empty database.
Neither retries nor account cancellation reset data. See
[startup and database recovery](troubleshooting.md#startup).

**Settings > About > Check for updates** checks published releases. It does not
install an update. Back up before replacing an installation.
