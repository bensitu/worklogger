"""Localized built-in Markdown templates with shared report structure."""

from worklogger.domain.shared.languages import normalize_language
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import _


class BuiltInTemplateProvider:
    def get_template(self, language: str, template_type: str,
                     user_id: int | None = None) -> Result[str]:
        language = normalize_language(language)
        titles = {
            "daily": _("Daily Report", language=language),
            "weekly": _("Weekly Report", language=language),
            "monthly": _("Monthly Report", language=language),
        }
        template_type = str(template_type or "").strip().lower()
        title = titles.get(template_type)
        if title is None:
            return Result.success("")
        period = "{{date}}" if template_type == "daily" else "{{year}}-{{month}}" if template_type == "monthly" else "{{date_range}}"
        return Result.success(
            f"# {title} ({period})\n\n"
            f"## {_('Work records', language=language)}\n{{{{work_records}}}}\n\n"
            "{{notes_section}}{{calendar_section}}{{projects_section}}"
            f"## {_('Hours summary', language=language)}\n"
            f"- {_('Total', language=language)}: {{{{total_hours}}}}h\n"
            f"- {_('Overtime', language=language)}: {{{{overtime_hours}}}}h\n"
        )
