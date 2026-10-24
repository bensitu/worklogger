# Data Formats

## Work-Log CSV

Work-log export writes UTF-8 with a byte-order mark:

```csv
date,start,end,break,note,entry_type
2030-01-15,09:00,18:00,1.0,Documentation,normal
2030-01-16,22:00,06:00,0.5,Maintenance,remote
```

| Column | Meaning |
| --- | --- |
| `date` | ISO date, `YYYY-MM-DD` |
| `start`, `end` | Local clock boundaries |
| `break` | Historical deducted hours, not minutes |
| `note` | Record content; quoting preserves commas and line breaks |
| `entry_type` | Built-in type ID or a custom classification ID |

Built-in IDs are `normal`, `remote`, `business_trip`, `meeting`, `training`,
`break`, `paid_leave`, `comp_leave`, `sick_leave`, and `other`.
Custom records also need `entry_type_label` and `entry_type_category`, with category
`work`, `break`, or `leave`. Import preserves that snapshot without editing the
account's type catalog.

The original v3.3.3 six-column CSV remains accepted with `work_type` in place of
`entry_type`. New exports use `entry_type`; legacy files cannot represent a
separate work arrangement or custom classification snapshots. Historical
`remote` and `business_trip` IDs remain readable without guessing a work activity.

Optional `work_mode` stores `onsite`, `remote`, `business_trip`, or `other`.
Custom arrangements use a `custom:<uuid>` identifier and require the additional
`work_mode_label` column. Export includes that column when needed and applies the
same reversible text encoding as other user-supplied labels. Import retains the
historical name without adding to or modifying the destination account's catalog.
Missing or empty values mean unspecified and never inherit an account preference.
Exports include the column when at least one record has an arrangement. Break
and leave cannot carry a work arrangement or project/work-item context; invalid
combinations are rejected in the import preview. Import does not change the
arrangement remembered for new records.

Optional `started_at` and `ended_at` carry offset-aware ISO timestamps and must
agree with dates and clock boundaries. Clock-only records retain their wall-clock
meaning; import does not invent offsets.
Optional `project_label` and `work_item_label` preserve labels, not another
database's identifiers. Link them to local catalogs explicitly.

Import accepts `d` as a date alias and `lunch` as a break alias. Missing breaks
default to zero; missing types default to normal. Clock fields accept `HH:mm`
and compact hour/minute digits. Decimal-looking ambiguous values are rejected.
Breaks remain decimal hours.

Review the preview before confirmation. Multiple nonoverlapping periods may share
a date. Explicit note-only rows import independent memos; ordinary record content
does not overwrite them. Duplicate note-only dates and overlapping periods are
invalid. When dates already contain data, choose either matching-period replacement
or replacement of all time records on the affected dates. Matching-period
replacement retains other periods and rejects different overlapping boundaries.
Back up data before replacing dates or importing independent memos.
Valid rows commit together or roll back together.
Recent time-record replacements use the normal bounded undo history. A replaced
date may contain at most 250 records, and each history snapshot is limited to
1,048,576 serialized characters. Independent memo changes are not part of
time-record undo.

Imports are limited to 10 MiB and 50,000 rows. UTF-8 is preferred, with the selected
language's legacy encoding as a fallback. Field boundaries are trimmed.
Spreadsheet-sensitive exported text receives an apostrophe prefix.
Exports containing protected text include `text_format=spreadsheet-safe-v1`.
This marker allows import to restore formula-like text and literal apostrophes
without guessing. Files without the marker retain their literal text.
CSV is an exchange format, not a byte-for-byte database archive.

## iCalendar

Work-log export emits UTF-8 iCalendar with CRLF endings and folded lines. Timed
non-leave periods become individual events. Overnight periods end the next day.
Captured offsets export as UTC; clock-only records use floating local times.
Event descriptions include classification, an optional arrangement, project
context, and condensed record content. Leave records remain excluded. iCalendar
is an event exchange, not a lossless record backup; use CSV or a database backup
for complete supported record data.

Calendar import accepts files up to 10 MiB and 10,000 expanded daily entries.
UTC/named zones convert to system local time; floating times keep their clocks.
Finite recurrence, exclusions, and cancellations are handled.
Recurrence without an end date or count is rejected.
Declared recurrence counts above the event limit are rejected before expansion,
even if exclusions would reduce the final selection.
Date-bounded recurrence and combined rules are also counted before expansion;
the capacity budget includes additional dates and exclusion rules.
Long-running annual series are supported within the event budget; there is no
fixed ten-year cutoff. Expansion also limits candidate recurrence periods and
estimated output size, so sparse or excessive rules may still be rejected.
An end date before the first occurrence produces no events.

Multi-day events expand by occupied date; all-day end dates are exclusive.
Daily calendar segments may end at `24:00`, meaning the exclusive boundary at
the following midnight. This calendar representation is separate from manual
time-entry clock fields, which use `00:00` and an overnight date boundary.
Append deduplicates matching events; replace is transactional.
Imported events are separate from worked time, and the source file is unchanged.
Review representative files before importing a large calendar.

## Reports and Notes

Markdown export writes UTF-8 text. Current-report export can include unsaved edits.
Saved-daily-report aggregation selects the newest daily report per date and orders
dates chronologically. It does not save the open draft.

Report exports can include generation-source references. These describe inputs,
not validation of later edits. See [templates](templates.md) and the [user guide](user-guide.md).

## Timesheets

Timesheet export reads the selected day's or month's time records, not narrative
report content. XLSX and PDF separate work, recorded rest, historical deductions,
and leave. Multiple periods remain separate; unrecorded gaps do not become work.

XLSX includes a period table and reference worksheet. User text is typed as text.
The workbook contains snapshot totals; edits do not update WorkLogger.

PDF contains paginated landscape tables with repeated headings. It is separate
from an analytics summary PDF.

Limits are 50,000 entries and two million text characters per snapshot.
XLSX rejects cells exceeding 32,767 characters rather than truncating them.
Exports publish only after successful generation and retain existing files on
failure. They are records of captured data, not payroll or legal certification.

## Analytics

Analytics dashboard CSV exports the loaded period's individual time records,
including work, breaks, and leave. Column headings use the interface language
and identify dates, clock boundaries, the end date for overnight records,
classification, accounting category, work arrangement, project, work item,
content, worked/rest/leave hours, record status, and available original
timestamps. Dates without records have an explicit No records row with zero
hours. Decimal hours retain six places, and files use UTF-8 with a byte-order
mark. Spreadsheet-sensitive text is protected. This is an analysis export,
not the work-log import format, and has no corresponding import operation.
The separate chart dialog exports readable period/work-hour/leave-hour columns
for its selected chart metric.
Its quarterly chart covers all four quarters, so that overview's filename
identifies the full year instead of a single quarter.

Suggested filenames identify the scope and period, for example
`analytics-monthly-2026Oct-20261024-153045-123.csv`,
`analytics-quarterly-2026Q4-20261024-153045-123.csv`, or
`analytics-annual-2026-20261024-153045-123.pdf`. The final part is the local export
date, time, and milliseconds; month abbreviations are consistently English.
Analytics dashboard PDF starts with a landscape overview of all eight areas:
period hours and goal progress, overtime and comparison, actual attendance and
planned work, rest dates, work-hour trends, average work hours, the selected
classification/work-arrangement distribution, and daily averages. It uses a
light print layout regardless of the interface theme, not a screenshot of the
visible viewport. Following pages contain complete numeric tables with repeated
headings, explicit period boundaries, both distribution dimensions, and the
previous-period comparison range. Long labels remain complete in those tables;
the overview groups distributions beyond five items under Other. Work and leave
averages use their respective positive-work and leave-date counts.

Both formats use the loaded dashboard snapshot rather than rereading records
during export. Changing a period after starting an export does not change that
export's data. Files replace their destination only after successful generation.

## Database Backups

SQLite backups contain all accounts, records, notes, reports, settings, background
media, and stored history. They replace the whole database when restored.
OS credentials, remembered-session files, language preferences, and model files
need separate handling. Proxy passwords and API-key settings are excluded from
newly created backups.
Protect backups as sensitive, unencrypted files. See [database handling](database.md).

## Model Metadata

The public `model_catalog.json` contains a `models` list. Entries describe IDs,
display names, filenames, checksums, download URLs, estimated sizes, RAM estimates,
context/output limits, descriptions, translated descriptions, and licenses.

Persistent `models/catalog.json` and `manifest.json` accompany shared GGUF files.
Catalog reads are bounded to 1 MiB. Metadata never automatically downloads or
selects weights, and database backup does not copy this directory.
See [local models](local-models.md).
