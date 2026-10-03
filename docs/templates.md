# Report Templates

## Storage and Selection

`BuiltInTemplateProvider` supplies daily, weekly, and monthly Markdown templates
for all supported interface languages. `UserTemplateProvider` first looks for an
account-specific template in SQLite, then uses a built-in template. Saved custom
templates are identified by account, language, and report type.

Reset removes the custom template for that selection; it does not delete existing
reports. Changes affect subsequent generation, not previously saved content.

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
