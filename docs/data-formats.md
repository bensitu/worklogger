# Data Formats

## Work-Log CSV

Export writes UTF-8 with a byte-order mark and these columns:

```csv
date,start,end,break,note,work_type
2026-05-21,09:00,18:00,1.0,Documentation,normal
2026-05-22,22:00,06:00,0.5,Maintenance,remote
2026-05-23,,,0,Personal leave,paid_leave
```

| Column | Meaning |
| --- | --- |
| `date` | ISO date `YYYY-MM-DD` |
| `start`, `end` | Local clock times; blank together for an untimed record |
| `break` | Decimal hours, not minutes |
| `note` | Text; CSV quoting preserves commas and line breaks on export |
| `work_type` | `normal`, `remote`, `business_trip`, `paid_leave`, `comp_leave`, `sick_leave` |

Import also accepts `d` for the date and `lunch` for the break. Missing break values
default to zero; missing work types default to `normal`, and unknown types are
reported as invalid rows. Both ISO dates and year-first slash dates are accepted. The
importer trims field boundaries, so it is not a byte-for-byte archive of note text.

Each valid row is normalized using the work-log rules and saved to the currently
selected account. The import preview shows valid rows, existing dates, and invalid
rows before confirmation. Valid rows are written in one transaction; storage
failure rolls back the entire batch. Existing dates require explicit replacement
permission. Duplicate dates in the file are reported as invalid rows. Files are
limited to 10 MiB and 50,000 rows. UTF-8 is preferred, with the selected language's
legacy Windows encoding used when UTF-8 decoding fails. The adapter also accepts
an explicit encoding. Invalid encoding and CSV syntax return an import error.

Spreadsheet-sensitive text is prefixed with an apostrophe to prevent formula
execution. The prefix is part of the exported text. Generated files replace their
destination atomically after successful writing; failed exports preserve the
existing destination.

## iCalendar

Work-log export emits UTF-8 iCalendar text with CRLF endings, escaped text, and
75-byte line folding. Timed non-leave records become events; untimed and leave
records are omitted. Overnight shifts end on the following date. Event summaries
include worked hours, and descriptions include up to 500 characters of the note.
Event times are local floating times, without a timezone definition.

Calendar import uses `icalendar` and `recurring-ical-events`. Files are limited to
10 MiB and 10,000 expanded daily entries. UTC and named timezones are converted to
system local time; floating times retain their local clock values. Event properties
are kept separate from nested alarm properties. Only the source filename is stored.

Imports remain independent calendar records, not work-log entries or hours worked:

- Finite recurrence rules, recurrence exclusions, and cancelled occurrences are handled.
- A recurrence without an end date or occurrence count is rejected, not truncated.
- Multi-day events expand across occupied dates; an all-day end date is exclusive.
- Replacement is transactional. Appending deduplicates matching date, time, and content.

Do not use this import/export pair as a lossless round trip for an arbitrary
calendar provider. Review a small representative file before importing a large one.

## Markdown

Daily notes and reports are text content. Markdown export writes UTF-8. Saved
reports retain their content; the renderer does not reevaluate them when source
work logs change. See [template variables](templates.md).

## Analytics Exports

Analytics CSV and PDF are presentation outputs from chart/statistics data. They
are different from the six-column work-log CSV. The analytics CSV header is:

```csv
label,bar_value,line_value,leave_hours,leave_marker
```

Numeric values use two decimal places, and the leave marker is `1` or `0`.
The file uses UTF-8 with a byte-order mark.

The PDF adapter uses Qt's text and PDF rendering with Unicode text, font fallback,
and automatic A4 pagination. It requires the desktop GUI application to be
initialized, but does not open a window or use an external PDF application.
It contains the complete text summary, not a rendered chart.

## Database Files

Database backups are SQLite files, not CSV or document exports. They include
accounts, credentials, work logs, notes, reports, settings, and related tables.
Treat them as sensitive data. Restore replaces the entire database and validates
the signed-in username. See [backup details](database.md).

## Model Metadata

Local model storage uses `catalog.json` and `manifest.json` beside shared GGUF
files. Model entries include an ID, display name, filename, status, optional
download URL and SHA-256 checksum, description, and estimated size. Metadata and
models are not part of database backups. The root `model_catalog.json` is a
separate tracked resource and is not automatically loaded by the default desktop
model store. See [integrations](integrations.md).
