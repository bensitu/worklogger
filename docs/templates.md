# Report Templates

## Editing

Open Templates from Reports. Select the report type and language, edit the
template, and use Save and apply. Templates belong to an account, language, and
daily/weekly/monthly report type. Reset removes that custom template and uses the
built-in one; it does not delete saved reports.

Generation replaces the visible draft only after any required confirmation.
Changing a template affects subsequent generation, not saved report text.
Review the generated draft before saving.

## Syntax

Variables use double braces. Whitespace around a name is ignored.
Unknown variables remain visible as double-braced text.
Rendering substitutes values; it does not execute Python, expressions, or loops.

```markdown
# Work summary: {{date_range}}

Prepared by: {{display_name}}
Worked hours: {{total_hours}}
Overtime: {{overtime_hours}}

## Work
{{task_list}}

## Calendar
{{calendar_events}}

## Projects
{{projects_summary}}
```

## Variables

| Variable | Value |
| --- | --- |
| `date`, `start` | Inclusive period start as an ISO date |
| `end` | Inclusive period end |
| `date_range` | Start and end joined by a separator |
| `year` | Period-start year |
| `month` | Period-start month; two digits for monthly reports |
| `display_name` | Preferred display name, falling back to login ID |
| `task_list` | Work-record content |
| `calendar_events` | Imported events in the period |
| `quick_logs` | Retained previous entries |
| `total_hours` | Worked hours to one decimal place |
| `overtime_hours` | Overtime to one decimal place |
| `projects_summary` | Worked hours grouped by saved project identity/label |
| `issues`, `next_plan` | Empty list items for manual completion |

Rest and leave do not contribute worked hours to project summaries.
The author name is read during generation; changing a profile does not rewrite
existing drafts, saved reports, or exports.
Notes included in a report must have the corresponding sharing approval.

## Contributor Contract

Rendering lives in `domain/reporting/templates.py`; generation constructs its
context in the report use cases. Providers select account templates before
built-in templates. Add variables to the appropriate context builder, document
their meaning, and test known/unknown substitutions.
Treat template and generated content as text, never as executable instructions.
