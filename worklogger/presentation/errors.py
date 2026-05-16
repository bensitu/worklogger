"""Presentation helpers for user-visible error messages."""

from __future__ import annotations

import logging

from worklogger.domain.shared.errors import AppError
from worklogger.infrastructure.i18n import _

LOGGER = logging.getLogger(__name__)


def display_error_message(error: AppError | None) -> str:
    """Return a translated message safe for direct UI display."""

    if error is not None and logging.getLogger().handlers:
        LOGGER.error("app_error_displayed", extra={"error_code": error.code})
    return _(error.message) if error is not None else _("Unknown error")
