# User Guide

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
panel edits the selected day's record and lists its work entry and imported
calendar events. Add Entry opens quick-log, note, and AI-assistance actions; AI
generation requires a configured service and is unavailable by default.

### Manual Entry

1. Select Manual Input and enter start and end times. The clock icon opens the
   time-selection control.
2. Enter break duration in decimal hours: `0.5` means 30 minutes.
3. Select the work type, optionally enter a note, and save.

A saved work record is unique per account and date. Saving again updates that
record; it does not add another shift. Use quick logs for multiple task descriptions.
Successful time-entry saves update the calendar without a confirmation popup.

The maximum elapsed shift is 16 hours, before subtracting breaks. Breaks must be
nonnegative and shorter than the elapsed shift. An end time earlier than the start
means the next day, for example `22:00` to `06:00`. Equal times represent a 24-hour
interval and therefore fail the maximum-length check. Both times may be omitted
for a note-only or leave record; entering only one time is invalid.

Work types are normal, remote, business trip, paid leave, compensatory leave, and
sick leave. Leave is accounted for separately from worked hours in summary totals.

### Automatic Entry

Clock In records the current local date and time in the editor. Clock Out fills
the end time; choose Save to persist the completed record. Break controls measure a break or
add 15 minutes; measured break totals are rounded to quarter hours when ended.
The configured default break applies when starting a new record.

The active timer is application state, not a background service. Do not assume an
unfinished entry survives closing the application or restarting the computer.
Review and save the completed values before leaving the session.

### Holidays and Markers

Enable holiday display in Settings > General. The country is inferred from the
system time zone using the application's country mapping, with US as the fallback.
Holiday names come from the holiday data library and may not match the interface
language. A holiday is not an imported event and does not create a work record.

Cells can show notes, overnight work, event counts, and work-type indicators.
Markers and daily totals are visual summaries, not additional entries.

## Notes and Quick Logs

Quick logs store a description and optional same-day time range. They do not
increase the day's worked-hour total. A quick-log end time must follow its start
time; overnight ranges belong in the main work record instead.

The note editor supports Markdown, template insertion, quick-log insertion, save,
and Markdown export. Daily notes and the time-entry note use the same underlying
field. Review unsaved changes before changing the selected day or leaving an editor.

## Reports

Choose a daily, weekly, or monthly period. Weekly periods run Monday through
Sunday, independently of the calendar's displayed week-start preference. Generate
a report from the period's work records, quick logs, and calendar events, then
edit and save it. Select a history item to reopen saved content.

Report content is saved Markdown, not a live query. Changing a work record does
not rewrite an already saved report. Generate or edit it again when needed.
Template changes are scoped by account, language, and report type. Exported
Markdown is an unencrypted document. See [templates](templates.md).

## Analytics

Choose monthly, quarterly, or annual scope and navigate between periods. The
dashboard displays worked hours, overtime, work days, averages, work types, and
comparisons with the preceding period. Leave is represented separately. The
configured monthly target is multiplied by the number of months in the period.

The hours card is titled Monthly Hours, Quarterly Hours, or Annual Hours to match
the selected period. Its percentage is not capped at 100%. The inner ring shows
the first 100%, and a contrasting outer ring shows the next 100%. At 200% and above,
both rings are full while the percentage continues to show the actual rounded
value. A zero target displays 0% rather than an undefined ratio.

CSV and PDF exports contain computed analytics. They are not database backups and
the analytics CSV is not the same format as the work-log import CSV. PDF currently
provides a single-page text summary, not the chart, and does not preserve all
localized characters. See [export limitations](data-formats.md).

## Settings

| Category | Available controls and behavior |
| --- | --- |
| Appearance | Native-language choices, preset/custom accent, light/dark mode; palette appears only for Custom |
| General | Standard hours, default break, monthly target, holidays, week start, overnight display, platform residency |
| AI | Preferences and privacy switches, external service fields, local model management; generation is not connected by default |
| Data | Work-log CSV and iCalendar export, CSV and calendar import, database backup/restore; clearing calendar events is disabled |
| Network | Stored proxy preferences and system-stored proxy password; these do not currently route adapter traffic |
| Account | Current account, password change, identities, administrator tools when authorized, logout |
| About | Version and author information, license display, repository link, manual update check |

Most settings save when changed. Language changes take effect after restart or
the next login rather than rebuilding the open interface immediately. Appearance
and calendar preferences update the active window.

## Backups and Updates

Use Settings > Data to create a database backup. It includes all accounts and
their stored records, not only the signed-in user's data. It does not include model
files, operating-system credentials, language preferences, or the remembered-login
file. Store backups privately.

Restore replaces the database rather than merging records. The file must pass
integrity checks and contain the current username. Follow the application's
confirmation and restart instructions. Keep a separate known-good backup.

Check for Updates contacts the configured GitHub release endpoint. It does not
download or install an application update automatically.
