"""Report template rendering helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from collections.abc import Mapping

_PLACEHOLDER_PATTERN = re.compile(r"\{\{(.*?)\}\}")
TEMPLATE_TYPES = frozenset({"daily", "weekly", "monthly"})


@dataclass(frozen=True)
class ReportTemplate:
    id: int | None
    user_id: int
    language: str
    template_type: str
    content: str
    updated_at: datetime | None = None


def render_template(template: str, values: Mapping[str, object]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        if key not in values:
            return "{{" + key + "}}"
        return str(values[key])

    return _PLACEHOLDER_PATTERN.sub(replace, template)


def normalize_template_type(template_type: str) -> str:
    if not isinstance(template_type, str):
        raise TypeError("template_type_must_be_string")
    normalized = template_type.strip().lower()
    if normalized not in TEMPLATE_TYPES:
        raise ValueError("invalid_template_type")
    return normalized


def normalize_template_language(language: str) -> str:
    cleaned = str(language or "en_US").strip().replace("-", "_")
    return cleaned or "en_US"
