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
default to zero; missing or unrecognized work types normalize to `normal`. The
importer trims field boundaries, so it is not a byte-for-byte archive of note text.

Each valid row is normalized using the work-log rules and saved to the currently
selected account. Existing dates are updated. Invalid rows are reported with
their row numbers; other valid rows can still be saved. Import is not an atomic
all-or-nothing operation. Back up before importing over existing records.

CSV files can contain user-supplied text. WorkLogger does not neutralize spreadsheet
formula syntax; inspect untrusted exports before opening them in a spreadsheet
application that evaluates formulas.

## iCalendar

Work-log export emits UTF-8 iCalendar text with CRLF endings, escaped text, and
75-byte line folding. Timed non-leave records become events; untimed and leave
records are omitted. Overnight shifts end on the following date. Event summaries
include worked hours, and descriptions include up to 500 characters of the note.
Event times are local floating times, without a timezone definition.

Calendar import reads files up to 10 MiB. It supports unfolded `VEVENT` entries
with a valid start date and nonempty summary, optional end time, description,
location, and date-only all-day events. Unsupported or incomplete events may be
skipped. The source filename is stored with each imported event.

The importer is a limited interchange reader, not a full calendar engine:

- Recurrence rules and exception expansion are not implemented.
- Timezone identifiers and UTC suffixes are not converted to local time.
- Multi-day events are represented on their start date rather than expanded.
- Imports are independent calendar records, not work-log entries or hours worked.

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

The PDF adapter writes a single A4 text page, limited to 45 lines including the
title and spacing. It does not include a rendered chart. It uses Helvetica and
Latin-1 replacement encoding without embedded fonts, so characters outside that
encoding, including Japanese, Korean, and Chinese, are not preserved. Use CSV
when localized labels must remain intact. No external PDF application is required
to generate the file.

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
