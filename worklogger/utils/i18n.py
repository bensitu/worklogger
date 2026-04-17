"""Gettext runtime i18n helpers."""

from __future__ import annotations

import gettext
import locale
import os
import threading
from functools import lru_cache
from pathlib import Path

LANG_NAMES = {
    "en_US": "English",
    "ja_JP": "日本語",
    "ko_KR": "한국어",
    "zh_CN": "简体中文",
    "zh_TW": "繁體中文",
}

LOCALE_CODE_MAP = {
    "en_US": "en_US",
    "ja_JP": "ja_JP",
    "ko_KR": "ko_KR",
    "zh_CN": "zh_CN",
    "zh_TW": "zh_TW",
}

DOMAIN = "messages"
LOCALES_DIR = Path(__file__).resolve().parents[1] / "locales"

# Canonical key -> English fallback msgid.
MSG_DEFAULTS = {
    "ai_btn": "✨ AI Assist",
    "ai_err_api_key_missing": "API Key is not set.",
    "ai_err_api_key_missing_detail": "Please enter your API Key in Settings → AI.",
    "ai_err_baseurl_missing": "API Base URL is not set.",
    "ai_err_baseurl_missing_detail": "Please enter the API Base URL in Settings → AI.",
    "ai_err_model_missing": "Model name is not set.",
    "ai_err_model_missing_detail": "Please enter a model name in Settings → AI.",
    "ai_err_no_fallback_detail": (
        "Local model failed and no external API key / URL / model name is configured. "
        "Please configure an external model in Settings → AI."
    ),
    "ai_generated": "AI Generated Content",
    "ai_init": "Initializing AI request...",
    "ai_result_title": "AI Generated Result",
    "ai_success": "✓ Request successful.",
    "ai_timeout_warning": "⚠️ Request exceeded 30 seconds, processing may take a while. Please continue waiting...",
    "ai_assist.local_model_not_running": "Local model unavailable - using external model instead.",
    "ai_assist_local_model_not_running": "Local model unavailable - using external model instead.",
    "apply": "Apply",
    "btn_cancel": "Cancel",
    "btn_regenerate": "Regenerate",
    "cal_imported": "Imported {} calendar events.",
    "enable_menu_bar": "Enable menu bar icon",
    "enable_tray": "Enable tray icon",
    "end_now": "End now",
    "local_model_fallback_toast": "Local model unavailable - using external model instead",
    "local_model_hint": "When enabled, text processing uses the local model first - no data is sent to external services.",
    "local_model_import_error": "llama-cpp-python not installed - run: pip install llama-cpp-python",
    "local_model_load_fail": "Local model failed to load",
    "local_model_installing_deps": "Installing local model dependencies...",
    "local_model_loading": "Loading local model...",
    "local_model_loaded": "Local model loaded.",
    "local_model_generating": "Generating with local model...",
    "local_model_downloading": "Downloading local model...",
    "local_model_verifying": "Verifying local model file...",
    "local_model_hash_ok": "Model hash verified.",
    "local_model_download_ok": "Model download completed.",
    "local_model_not_downloaded": "Local model not downloaded - go to Settings -> AI",
    "local_model_inactive": "Local model is inactive",
    "local_model_state_active": "Active",
    "local_model_state_inactive": "Inactive",
    "local_model_verify_timeout": "Local model verification timed out.",
    "local_model_verify_cancelled": "Local model verification was cancelled.",
    "local_model_verify_permission_denied": "Permission denied while verifying local model file.",
    "local_model_verify_failed": "Local model verification failed. Please re-download or switch model.",
    "local_model_switch_confirm": "A different model is already downloaded. It will be deleted before the new one downloads. Continue?",
    "original_content": "Original Content",
    "quick_log_add": "Add",
    "quick_log_delete": "Delete",
    "report_copy": "Copy",
    "report_copied": "Copied!",
    "report_download": "Download .md",
    "report_monthly": "Monthly Report",
    "report_weekly": "Weekly Report",
    "settings_ai_local_model_disabled_tooltip": "Local model is disabled.",
    "start_now": "Start now",
    "wt_business": "Business trip",
    "wt_comp": "Comp leave",
    "wt_normal": "Normal",
    "wt_paid": "Paid leave",
    "wt_remote": "Remote work",
    "wt_sick": "Sick leave",
}

_lang_state = threading.local()
_lang_state.current = "en_US"


def _normalize_lang(lang: str | None) -> str:
    if not lang:
        return "en_US"
    compact = str(lang).strip()
    if compact in LANG_NAMES:
        return compact
    aliases = {
        "en": "en_US",
        "ja": "ja_JP",
        "ko": "ko_KR",
        "zh": "zh_CN",
        "zh_tw": "zh_TW",
        "zh-hant": "zh_TW",
        "zh_hant": "zh_TW",
        "zh-cn": "zh_CN",
        "zh_cn": "zh_CN",
        "zh-tw": "zh_TW",
        "ja-jp": "ja_JP",
        "ko-kr": "ko_KR",
        "en-us": "en_US",
    }
    low = compact.lower().replace(".", "_")
    if low in aliases:
        return aliases[low]
    if low.startswith("zh_tw") or low.startswith("zh-hant"):
        return "zh_TW"
    if low.startswith("zh"):
        return "zh_CN"
    if low.startswith("ja"):
        return "ja_JP"
    if low.startswith("ko"):
        return "ko_KR"
    if low.startswith("en"):
        return "en_US"
    return "en_US"


def _default_lang() -> str:
    try:
        loc = locale.getlocale()[0] or locale.getdefaultlocale()[0]  # type: ignore[index]
    except Exception:
        loc = None
    return _normalize_lang(loc)


def _apply_locale_env(lang: str) -> None:
    locale_code = LOCALE_CODE_MAP.get(lang, LOCALE_CODE_MAP["en_US"])
    os.environ["LANGUAGE"] = locale_code
    os.environ["LANG"] = f"{locale_code}.UTF-8"
    os.environ["LC_ALL"] = f"{locale_code}.UTF-8"


@lru_cache(maxsize=16)
def _load_translation(lang: str) -> gettext.NullTranslations:
    locale_code = LOCALE_CODE_MAP.get(lang, LOCALE_CODE_MAP["en_US"])
    try:
        return gettext.translation(
            DOMAIN,
            str(LOCALES_DIR),
            languages=[locale_code],
            fallback=True,
        )
    except Exception:
        return gettext.NullTranslations()


def get_language() -> str:
    return _normalize_lang(getattr(_lang_state, "current", _default_lang()))


def set_language(lang: str | None) -> str:
    norm = _normalize_lang(lang)
    _apply_locale_env(norm)
    _lang_state.current = norm
    return norm


def get_translator(lang: str | None = None) -> gettext.NullTranslations:
    return _load_translation(_normalize_lang(lang) if lang else get_language())


def _(message: str) -> str:
    return get_translator().gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    return get_translator().ngettext(singular, plural, n)


def msg(key: str, default: str | None = None, **kwargs) -> str:
    template = default if default is not None else MSG_DEFAULTS.get(key, key)
    text = _(template)
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text


def setup_i18n(lang: str | None = None):
    set_language(lang or _default_lang())
    return _


setup_i18n()
