"""Presentation helpers for user-visible error messages."""

from __future__ import annotations

import logging

from worklogger.config.constants import PASSWORD_MIN_LENGTH
from worklogger.domain.shared.errors import AppError, CancellationError
from worklogger.infrastructure.i18n import _
from worklogger.presentation.error_messages import DEFAULT_ERROR_MESSAGE, ERROR_MESSAGES

LOGGER = logging.getLogger(__name__)


def display_error_message(error: AppError | None) -> str:
    """Return a translated message safe for direct UI display."""

    if isinstance(error, CancellationError):
        if error.code == "identity_authorization_cancelled":
            return display_error_code(error.code)
        return _("Operation cancelled.")
    if error is not None and logging.getLogger().handlers:
        LOGGER.error("app_error_displayed", extra={"error_code": error.code})
    if error is not None and error.code == "account_locked":
        return _(ERROR_MESSAGES[error.code]).format(seconds=max(1, int(error.details.get("seconds", 1))))
    return display_error_code(error.code) if error is not None else _("Unknown error")


def display_error_code(code: str) -> str:
    """Translate known codes without displaying raw diagnostics."""
    message = _(ERROR_MESSAGES.get(code, DEFAULT_ERROR_MESSAGE))
    if code == "password_too_short":
        return message.format(length=PASSWORD_MIN_LENGTH)
    return message
