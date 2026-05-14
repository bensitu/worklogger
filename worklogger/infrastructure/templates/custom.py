"""Custom template provider with built-in fallback."""

from __future__ import annotations

from typing import Protocol

from worklogger.domain.reporting.repositories import ReportTemplateRepository
from worklogger.domain.reporting.templates import normalize_template_language, normalize_template_type
from worklogger.domain.shared.result import Result


class FallbackTemplateProvider(Protocol):
    def get_template(
        self,
        language: str,
        template_type: str,
        user_id: int | None = None,
    ) -> Result[str]:
        ...


class UserTemplateProvider:
    def __init__(
        self,
        repository: ReportTemplateRepository,
        fallback: FallbackTemplateProvider,
    ) -> None:
        self._repository = repository
        self._fallback = fallback

    def get_template(
        self,
        language: str,
        template_type: str,
        user_id: int | None = None,
    ) -> Result[str]:
        normalized_language = normalize_template_language(language)
        normalized_type = normalize_template_type(template_type)
        if user_id is not None:
            template = self._repository.get(user_id, normalized_language, normalized_type)
            if template is not None:
                return Result.success(template.content)
        return self._fallback.get_template(normalized_language, normalized_type, user_id=user_id)

