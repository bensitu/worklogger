"""Built-in Markdown templates."""

from __future__ import annotations

from worklogger.domain.shared.result import Result


class BuiltInTemplateProvider:
    def get_template(
        self,
        language: str,
        template_type: str,
        user_id: int | None = None,
    ) -> Result[str]:
        del user_id
        language_key = _language_key(language)
        template_key = str(template_type or "").strip().lower()
        template = _TEMPLATES.get((language_key, template_key))
        if template is None:
            template = _TEMPLATES.get(("en_US", template_key), "")
        return Result.success(template)


def _language_key(language: str) -> str:
    cleaned = str(language or "en_US").replace("-", "_")
    return cleaned if cleaned in _LANGUAGES else "en_US"


_LANGUAGES = frozenset({"en_US", "ja_JP", "ko_KR", "zh_CN", "zh_TW"})

_WEEKLY = """# Weekly Work Report  {{date_range}}

## Work Completed
{{task_list}}

## Calendar Events
{{calendar_events}}

## Quick Logs
{{quick_logs}}

## Hours Summary
- Total: {{total_hours}}h
- Overtime: {{overtime_hours}}h

## Issues / Risks
{{issues}}

## Plan for Next Week
{{next_plan}}
"""

_MONTHLY = """# Monthly Work Report  {{year}}-{{month}}

## Summary of Work
{{task_list}}

## Calendar Events
{{calendar_events}}

## Quick Logs
{{quick_logs}}

## Hours Summary
- Total: {{total_hours}}h
- Overtime: {{overtime_hours}}h

## Issues / Risks
{{issues}}

## Plan for Next Month
{{next_plan}}
"""

_DAILY = """# Daily Report ({{date}})

## Today's work
{{task_list}}

## Calendar Events
{{calendar_events}}

## Quick Logs
{{quick_logs}}

## Hours
- Total: {{total_hours}}h
- Overtime: {{overtime_hours}}h

## Issues / Risks
{{issues}}

## Plan for tomorrow
{{next_plan}}
"""

_TEMPLATES = {
    (language, "daily"): _DAILY
    for language in _LANGUAGES
} | {
    (language, "weekly"): _WEEKLY
    for language in _LANGUAGES
} | {
    (language, "monthly"): _MONTHLY
    for language in _LANGUAGES
}
