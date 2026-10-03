"""gettext-only runtime translation helpers."""

from __future__ import annotations

import gettext
import os
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QLocale

DOMAIN = "messages"
SUPPORTED_LANGUAGES = ("en_US", "ja_JP", "ko_KR", "zh_CN", "zh_TW")
DEFAULT_LANGUAGE = "en_US"

_lock = threading.RLock()
_current_language = DEFAULT_LANGUAGE
_translation: gettext.NullTranslations = gettext.NullTranslations()


def locales_dir() -> Path:
    """Return the active locale directory for source or frozen builds."""

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        root_locales = Path(meipass) / "locales"
        if root_locales.exists():
            return root_locales
        compat_locales = Path(meipass) / "worklogger" / "locales"
        if compat_locales.exists():
            return compat_locales
    return Path(__file__).resolve().parents[1] / "locales"


def normalize_language(language: str | None) -> str:
    return _match_language(language) or DEFAULT_LANGUAGE


def _match_language(language: str | None) -> str | None:
    if not language:
        return None
    parts = language.strip().split(".", 1)[0].split("@", 1)[0].replace("-", "_").lower().split("_")
    prefix = parts[0]
    if prefix == "zh":
        # Explicit script takes precedence over the territory.
        if "hant" in parts:
            return "zh_TW"
        if "hans" in parts:
            return "zh_CN"
        return "zh_TW" if any(region in parts for region in ("tw", "hk", "mo")) else "zh_CN"
    for candidate in SUPPORTED_LANGUAGES:
        if candidate.lower().startswith(prefix + "_"):
            return candidate
    return None


def detect_system_language() -> str:
    try:
        system_locale = QLocale.system()
        languages = system_locale.uiLanguages() or [system_locale.name()]
        for language in languages:
            matched = _match_language(language)
            if matched is not None:
                return matched
    except Exception:
        pass
    return DEFAULT_LANGUAGE


def set_language(language: str | None) -> str:
    """Activate a gettext catalog and return the normalized language code."""

    global _current_language, _translation
    normalized = normalize_language(language)
    with _lock:
        _current_language = normalized
        _translation = gettext.translation(
            DOMAIN,
            localedir=str(locales_dir()),
            languages=[normalized],
            fallback=True,
        )
    return normalized


def get_language() -> str:
    with _lock:
        return _current_language


def available_languages() -> tuple[str, ...]:
    return SUPPORTED_LANGUAGES


def _(message: str, *, language: str | None = None) -> str:
    with _lock:
        translation = _translation if language is None else gettext.translation(
            DOMAIN, localedir=str(locales_dir()),
            languages=[normalize_language(language)], fallback=True,
        )
        return translation.gettext(message) or message


def ngettext(singular: str, plural: str, n: int) -> str:
    with _lock:
        return _translation.ngettext(singular, plural, n) or (singular if n == 1 else plural)


set_language(os.environ.get("WORKLOGGER_LANG"))

