# Notes

Daily notes are date-scoped memos, independent of recorded work periods. They do
not add worked hours, break time, or leave. The calendar provides a direct Notes
action and marks dates with saved notes when note markers are enabled.

## Editing and Recovery

The editor supports plain Markdown, copying, export, and optional text polishing.
Report templates are managed in Reports; the memo editor never changes them.
Search returns up to 50 matching dates, scoped to the signed-in account. It searches
saved memo content and descriptions in previous quick logs. Percent signs and
underscores in search terms are literal characters, not wildcard operators.

Search sits above the date history. Each history row separates its date from a
single-line, width-constrained content preview. The selected date is highlighted;
the unfiltered list also includes the open date when it has no saved note. The
editor heading displays that date in the active language, next to Polish text,
Copy Markdown, Export Markdown, and Reload saved note. These actions operate only
on the displayed note. Empty notes show an input placeholder; polishing, copying,
and exporting remain disabled until the editor contains non-whitespace text.

Drafts are saved after a short typing pause. Each draft retains the content on
which editing began and the sharing choices. Reopening restores that draft without
overwriting the saved memo. If another editor changed the saved content, Save
rejects the stale update. Sharing changes are also compared with their loaded
values so an older editor cannot restore revoked permissions. Reload saved note
deliberately discards the local draft and loads the latest saved text. Closing an
edited memo offers Keep draft, Discard, or Cancel. A draft can contain up to 1 MiB
of UTF-8 text; saved memo writes use the same
limit. Background writes are serialized before saving or closing the editor.

Saving commits the memo, sharing choices, and draft removal in one SQLite
transaction. Storage, content, or sharing conflicts retain the editor content. Save, export,
and error feedback use dialogs, not persistent readiness messages.

## Previous Entries

The separate Quick Log creation interface is no longer part of the calendar.
Existing quick-log rows remain unchanged and can be viewed in the memo editor.
Add to note copies their descriptions and optional times into the current draft.
Repeating it does not append the same unchanged lines again. These references are
not converted into worked-time entries. Existing report template placeholders and
database backups continue to support the original rows.
Generated reports omit a separate quick-log reference when an approved memo
already contains that same unchanged reference, avoiding duplicate report text.

## Sharing

Both sharing choices default to off, including for existing memos without explicit
preferences. Allow in reports makes that date's saved memo eligible for generated
reports. Allow in AI context makes it eligible for collected AI context only when
the account's AI privacy settings also permit notes. Private memo text is not
automatically collected. Explicitly choosing Polish text submits the visible text
for that operation, independently of automatic-context permission.

Previously saved reports are snapshots and are not rewritten by changing a memo
or its sharing choices. Exports contain the memo text and are unencrypted files.
Drafts and preferences are stored in the existing account-scoped settings table;
the feature requires no schema change or automatic conversion of historical data.
