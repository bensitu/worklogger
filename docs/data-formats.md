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
| `work_type` | `normal`, `remote`, `business_trip`, `meeting`, `training`, `break`, `paid_leave`, `comp_leave`, `sick_leave`, `other` |

Time entry accepts `HH:mm` and compact hour/minute digits. Legacy `HH.MM` requires
two minute digits; ambiguous decimal-looking input such as `1.5` is rejected,
not interpreted as either decimal hours or `01:05`. Break values remain decimal hours.

When records contain offset-aware timestamps, export appends `started_at` and
`ended_at` ISO timestamp columns. Import accepts these optional columns and verifies
that dates and clock times agree. Files containing only older clock-based records
keep the six-column format. Timestamp offsets preserve elapsed hours across daylight
saving changes; importing older files does not guess their original timezone.

If any record uses a custom type, export also appends `work_type_label` and
`work_type_category`. The type ID is `custom:` followed by a UUID in hexadecimal
form; its saved label and `work`, `break`, or `leave` category are required on
import. Built-in rows leave these optional fields empty. Import preserves the
record snapshot without modifying the receiving account's editable type catalog.
Imported custom records remain editable with their saved classification; select
an active account type explicitly when assigning a different classification.

Import also accepts `d` for the date and `lunch` for the break. Missing break values
default to zero; missing work types default to `normal`, and unknown types are
reported as invalid rows. Both ISO dates and year-first slash dates are accepted. The
importer trims field boundaries, so it is not a byte-for-byte archive of note text.

Each valid row is normalized using the work-log rules and saved to the currently
selected account. The import preview shows valid rows, existing dates, and invalid
rows before confirmation. Valid rows are written in one transaction; storage
failure rolls back the entire batch. Existing dates require explicit replacement
permission. Nonoverlapping timed rows may share a date; overlapping periods are
reported as invalid rows. An independent note-only row may share a date with timed
rows, but duplicate note-only rows are rejected. Files are
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
Records with captured timestamps export UTC event times. Older clock-only records
export local floating times, without a timezone definition.

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

Time-entry export emits each period separately, with distinct identifiers based on
the stored entry ID. Break events retain their duration and are labelled as breaks.
CSV export also retains individual periods and independent daily notes. Neither
export flattens a multi-entry day into its first-to-last clock span. CSV replacement
replaces all imported dates only after confirmation; entry IDs are local and are
not portable identifiers across CSV imports.

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
Export appends the required extension when another suffix is present; a destination
such as `summary.v2` becomes `summary.v2.csv` or `summary.v2.pdf`.

The PDF adapter uses Qt's text and PDF rendering with Unicode text, font fallback,
and automatic A4 pagination. It requires the desktop GUI application to be
initialized, but does not open a window or use an external PDF application.
It contains the complete text summary, not a rendered chart.

## Database Files

Database backups are SQLite files, not CSV or document exports. They include
accounts, credentials, work logs, notes, reports, settings, and related tables.
Treat them as sensitive data. Restore replaces the entire database and validates
the signed-in administrator's username and account ID. Proxy passwords are excluded
from new backups; re-enter them after moving an installation. See [backup details](database.md).

## Model Metadata

Local model storage uses `catalog.json` and `manifest.json` beside shared GGUF
files. The desktop also reads the bundled `model_catalog.json`; persistent entries
override bundled entries with the same ID. The root JSON object contains a
`models` list. Each entry follows `LocalModelEntry`: `id`, `display_name`,
`filename`, `status`, `sha256`, `download_url`, `estimated_size_mb` (MiB),
`min_ram_gb`, `context_length`, `max_output_tokens`, `description`,
`description_translations`, and `license`. The description is English text;
translations map locale IDs to text. Older localized `description` objects and
bare entry lists remain readable. Invalid individual entries are skipped.

Catalog reads are limited to 1 MiB and cached by path, timestamps, and file size;
changes invalidate the parsed metadata. Metadata writes are serialized within a
store instance. Metadata and models are not part of database backups. Bundled
entries do not automatically download, select, or load a model. See
[model choices and configuration](local-models.md).
