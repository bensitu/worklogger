"""Per-device UI language preference available before authentication."""

from __future__ import annotations

import logging
import os

from PySide6.QtCore import QSettings

from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import (
    SUPPORTED_LANGUAGES,
    detect_system_language,
    normalize_language,
    set_language,
)

LOGGER = logging.getLogger(__name__)
_LANGUAGE_KEY = "ui/language"


class LanguagePreferences:
    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = settings if settings is not None else QSettings(
            QSettings.Format.NativeFormat, QSettings.Scope.UserScope,
            "WorkLogger", "WorkLogger",
        )
        self._settings.setFallbacksEnabled(False)

    def load(self) -> str | None:
        try:
            self._settings.sync()
            if self._settings.status() != QSettings.Status.NoError:
                LOGGER.warning("login_language_read_failed")
                return None
            value = self._settings.value(_LANGUAGE_KEY)
            return value if isinstance(value, str) and value in SUPPORTED_LANGUAGES else None
        except Exception:
            LOGGER.warning("login_language_read_failed")
            return None

    def save(self, language: str) -> Result[None]:
        try:
            self._settings.setValue(_LANGUAGE_KEY, normalize_language(language))
            self._settings.sync()
            if self._settings.status() == QSettings.Status.NoError:
                return Result.success(None)
        except Exception:
            pass
        LOGGER.warning("login_language_save_failed")
        return Result.failure(InfrastructureError("settings_save_failed", "settings_save_failed"))


def initialize_language(preferences: LanguagePreferences) -> str:
    """Keep the explicit developer override; otherwise prefer the last choice."""
    language = os.environ.get("WORKLOGGER_LANG", "").strip()
    return set_language(language or preferences.load() or detect_system_language())
