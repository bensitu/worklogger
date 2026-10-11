# User Guide

## Accounts

Create a local account on first use. The first account is an administrator.
Passwords require at least eight characters. Recovery uses the saved recovery
key, so copy or save it privately when it is displayed.

Sign in with your login ID and password. **Remember me** retains a local session
credential for up to 30 days. Repeated failed attempts cause temporary lockouts.

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
identity creates a separate account; matching names or emails do not merge data.
See [browser sign-in](identity-signin.md) for provider registration.

## Recording Time

Select a date in Calendar. The right panel shows its editor and saved records.
**New time record** starts another record; selecting a saved record edits it.
**Clear input** resets a draft without deleting saved records.

### Manual Input

1. Enter start and end times.
2. Choose a work type and optionally a project and work item.
3. Enter Content and save.

Each date can contain multiple nonoverlapping records. After saving, the record
remains selected in both input modes. Content, type, and project are shared between
manual and automatic views. Use New time record or Clear input before starting a
different record.

An end time earlier than the start means the following day, such as 22:00 to
06:00. A period cannot exceed 16 hours. Equal start/end times represent 24 hours
and are rejected. Timed records require both boundaries.

### Auto Record

Choose a type and optional content, then Start. End saves the finished period and
its content. Save content updates an active timer without ending it. When idle,
Save changes updates the selected record's content and classification; use Manual
Input to correct time boundaries.

The timer retains its start and account across restarts. Editing another date
does not move it. Discard timer asks for confirmation before removing it.
Clearing content does not stop or discard the timer.

Break creates a separate rest record for the default break duration. Finish an
active timer first. Starting work during a shortcut-created break asks whether to
end that break early; ordinary saved records are never shortened automatically.
A zero default break disables the shortcut.

Configure long-timer and continuous-work reminders in **Settings > General**.
If a timer exceeds the allowed interval, correct its end time or discard it
deliberately. Reminders do not certify compliance with working-time regulations.

### Types, Projects, and Corrections

Manage work types and projects in **Settings > General**. Custom types have Work,
Break, or Leave accounting. Saved records retain their original classification
and labels when catalog entries are renamed or archived.

Use record search to filter dates, content, types, projects, or work items, then
open a result in Calendar. Recent context reuses an active project/work-item
selection. Batch assignment requires an explicit selection and confirmation.

Record actions can split a period, merge adjacent compatible periods, place a
historical break deduction, or undo a supported change. Historical deductions
have no known break position until you assign one. Confirm the preview before
applying a correction. Record undo does not cover CSV replacement or database
restore.

Imported calendar events are separate from worked time. Selecting one creates a
time-entry draft. Editing or deleting the local copy does not alter its source file.
Holiday display and the first day of the week are controlled in General settings.

## Notes

Notes are independent date-specific memos and do not contribute hours. Search
finds saved notes and retained previous entries. Copy and export operate on the
open note; Reload saved note discards its local draft.

Drafts are retained after a typing pause. Closing edited text offers Keep draft,
Discard, or Cancel. Conflicting saves preserve your input; reload and compare
before replacing someone else's changes.

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

Saved reports lists separate reports, newest first. Selecting one opens it.
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

Rest Days counts distinct dates with a positive-duration Break record. Multiple
breaks count once; a date can count as both a work day and a rest day. Missing
records do not imply rest, and leave is counted separately. Historical deducted
breaks are not separate rest-day records.

The monthly target is multiplied by the number of months in the selected period.
Project statistics separates work, rest, and leave by project and work item.
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

Network settings apply an account HTTP CONNECT proxy to supported HTTPS requests.
They do not change the operating system or browser proxy.

On supported platforms, enabling tray/menu-bar residency keeps a closed window
available through its icon. The menu can start a timer when idle or end an active
timer.

## Backups and Updates

**Settings > Data > Data location** identifies the active database directory.
Opening it does not move data. Use Backup Data instead of copying a live database
without its journal files.

Administrators can back up all accounts and restore a compatible database.
Restore replaces the database, retains the previous copy, and ends the session.
The backup must contain the administrator's login ID with the same account ID.
Model files, OS credentials, and remembered-login files require separate handling.
See [database safety](database.md).

**Settings > About > Check for updates** checks published releases. It does not
install an update. Back up before replacing an installation.
