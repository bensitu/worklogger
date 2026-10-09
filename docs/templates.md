# Report Templates

## Storage and Selection

`BuiltInTemplateProvider` supplies daily, weekly, and monthly Markdown templates
for all supported interface languages. `UserTemplateProvider` first looks for an
account-specific template in SQLite, then uses a built-in template. Saved custom
templates are identified by account, language, and report type.

Reset removes the custom template for that selection; it does not delete existing
reports. Changes affect subsequent generation, not previously saved content.
Generate from records is available directly in the report editor. Applying a
saved template uses the same draft-generation operation. Existing report IDs
are retained until saving; generation failure or a declined replacement leaves
the visible draft unchanged. Native editor normalization of line endings and
spacing does not mark an untouched stored report as modified.
The template editor displays its report type and language. Save and apply persists
the edited template and starts generation in one interaction. Replacing edited
report content still requires confirmation; a failed generation preserves the
report draft even though the template may already have been saved.

Saved reports shows all account-owned reports of the selected type, newest first
by initial save time and ID. It is not a revision history of the visible report.
The selected item is marked Open in editor, rather than an unexplained checkmark.
Content replacement retains the saved report's ID and initial save time.

Export report offers the visible editor content, the selected date's saved daily
report, or that month's saved daily reports. Saved-report exports do not save or
replace the current draft. For each date, the newest saved daily report by timestamp
and ID is included; dates are ordered chronologically. Weekly/monthly reports and
other accounts are excluded. An empty selection reports an error and preserves
any destination file.

## Rendering

Variables use double braces, for example `{{total_hours}}`. Whitespace around a
variable name is ignored. Unknown variables are preserved as double-braced text
so they remain visible to the editor. Rendering is plain substitution: templates
do not execute Python, evaluate expressions, or implement loops.

```markdown
# Work summary: {{date_range}}

Worked hours: {{total_hours}}
Overtime: {{overtime_hours}}

## Work
{{task_list}}

## Calendar
{{calendar_events}}

## Task notes
{{quick_logs}}
```

## Generated Report Variables

| Variable | Value |
| --- | --- |
| `date`, `start` | Inclusive period start as an ISO date |
| `end` | Inclusive period end |
| `date_range` | Start and end joined by a separator |
| `year` | Period-start year |
| `month` | Period-start month; two digits for monthly reports |
| `task_list` | Lines derived from work records |
| `calendar_events` | Lines derived from imported calendar events |
| `quick_logs` | Lines derived from quick logs |
| `total_hours` | Worked hours formatted to one decimal place |
| `overtime_hours` | Overtime formatted to one decimal place |
| `issues`, `next_plan` | Empty list items for manual completion |

Daily-note template insertion has a smaller context: `date`, `task_list`,
`calendar_events`, `quick_logs`, `total_hours`, `overtime_hours`, `issues`, and
`next_plan`. Its hour totals are empty strings; it is not the report-generation
calculation. Variables available only to reports remain unresolved in a note.

## Extending Templates

Add new variables to the appropriate context builder, document their meaning and
format, and test known and unknown substitutions. Keep translations in the
existing template/translation mechanisms. Do not use generated text as an
instruction to run code or change application configuration.

Relevant implementations:
[rendering](../worklogger/domain/reporting/templates.py),
[report generation](../worklogger/app/use_cases/reports.py),
[note insertion](../worklogger/presentation/viewmodels/notes.py), and
[providers](../worklogger/infrastructure/templates/custom.py).
