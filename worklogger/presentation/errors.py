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
    if error is not None and error.code == "report_not_found":
        return _("The saved report is no longer available. Reload the reports and try again.")
    if error is not None and error.code == "report_save_failed":
        return _("Unable to save the report. Your changes have been retained.")
    return _(error.message) if error is not None else _("Unknown error")
