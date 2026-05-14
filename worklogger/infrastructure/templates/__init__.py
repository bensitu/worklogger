"""Template infrastructure adapters."""

from worklogger.infrastructure.templates.builtin import BuiltInTemplateProvider
from worklogger.infrastructure.templates.custom import UserTemplateProvider

__all__ = ["BuiltInTemplateProvider", "UserTemplateProvider"]
