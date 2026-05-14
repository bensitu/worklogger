"""gettext-only runtime translation helpers."""

from __future__ import annotations

import gettext
import locale
import os
import sys
import threading
from pathlib import Path

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
    if not language:
        return DEFAULT_LANGUAGE
    normalized = language.replace("-", "_")
    if normalized in SUPPORTED_LANGUAGES:
        return normalized
    prefix = normalized.split("_", 1)[0].lower()
    for candidate in SUPPORTED_LANGUAGES:
        if candidate.lower().startswith(prefix + "_"):
            return candidate
    return DEFAULT_LANGUAGE


def detect_system_language() -> str:
    try:
        detected = locale.getlocale()[0] or locale.getdefaultlocale()[0]
    except Exception:
        detected = None
    return normalize_language(detected)


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


def _(message: str) -> str:
    with _lock:
        return _translation.gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    with _lock:
        return _translation.ngettext(singular, plural, n)


set_language(os.environ.get("WORKLOGGER_LANG"))

