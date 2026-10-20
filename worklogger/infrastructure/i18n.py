"""gettext-only runtime translation helpers."""

from __future__ import annotations

import gettext
import logging
import struct
from functools import lru_cache
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QLocale

DOMAIN = "messages"
from worklogger.domain.shared.languages import SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE, normalize_language, match_language as _match_language

_lock = threading.RLock()
_current_language = DEFAULT_LANGUAGE
_translation: gettext.NullTranslations = gettext.NullTranslations()
_explicit_catalogs: dict[tuple[str, str], gettext.NullTranslations] = {}


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
        _explicit_catalogs.clear()
        _current_language = normalized
        _translation = _catalog(normalized)
    return normalized


def get_language() -> str:
    with _lock:
        return _current_language


def available_languages() -> tuple[str, ...]:
    return SUPPORTED_LANGUAGES


def _catalog(language: str) -> gettext.NullTranslations:
    path = locales_dir() / language / "LC_MESSAGES" / f"{DOMAIN}.mo"
    try:
        stat = path.stat()
    except OSError:
        return gettext.NullTranslations()
    return _read_catalog(str(path), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=32)
def _read_catalog(path: str, modified: int, size: int) -> gettext.NullTranslations:
    try:
        with Path(path).open("rb") as source:
            return gettext.GNUTranslations(source)
    except (OSError, EOFError, struct.error, UnicodeError, ValueError):
        logging.getLogger(__name__).warning("translation_catalog_invalid")
        return gettext.NullTranslations()


def _(message: str, *, language: str | None = None) -> str:
    if not message:
        return message
    with _lock:
        if language is None:
            translation = _translation
        else:
            normalized = normalize_language(language)
            key = (str(locales_dir()), normalized)
            if key not in _explicit_catalogs:
                _explicit_catalogs[key] = _catalog(normalized)
            translation = _explicit_catalogs[key]
        return translation.gettext(message) or message


def ngettext(singular: str, plural: str, n: int) -> str:
    with _lock:
        return _translation.ngettext(singular, plural, n) or (singular if n == 1 else plural)
