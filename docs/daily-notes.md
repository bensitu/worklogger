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
Search starts after a 650 ms pause and runs independently of editing and draft
saving. It does not disable the search field or move keyboard focus. Results from
an older query or a previously opened date are discarded.
When no saved notes match, the empty-result message appears directly below the
search field rather than at the bottom of the date history.

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
Existing quick-log rows can be viewed in the memo editor. Add to note asks for
confirmation before adding their descriptions and optional times and saving the
current note, including its sharing choices. After successful saving, the matching
original rows are deleted and the previous-entry area disappears when no rows
remain. Note saving, draft removal, and source-row deletion share one transaction.
A changed or missing source row, an incomplete reference, or a note conflict rolls
back the entire operation. Cancelling the confirmation changes nothing. Ordinary
Save never removes previous entries.
References already present in the note are not appended again, including
multi-line descriptions. These references are not converted into worked-time
entries. Existing report template placeholders and database backups continue to
support previous entries that have not been transferred.
Generated reports omit a separate quick-log reference when an approved memo
already contains that same unchanged reference, avoiding duplicate report text.
After transfer, the text follows the note's report and AI sharing choices;
previously saved reports remain unchanged.

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
