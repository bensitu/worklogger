"""Gettext runtime i18n helpers."""

from __future__ import annotations

import gettext
import locale
import os
import sys
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
_DEV_LOCALES_DIR = Path(__file__).resolve().parents[1] / "locales"
LOCALES_DIR = _DEV_LOCALES_DIR

# Canonical key -> English fallback msgid.
MSG_DEFAULTS = {
    "ai_btn": "✨ AI Assist",
    "ai_ext_model_description": "OpenAI-compatible models are supported, including ChatGPT, Claude, Qwen, and DeepSeek.",
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
    "ai_status_start": "Preparing your AI request...",
    "ai_status_build": "Preparing request for {model}...",
    "ai_status_connect": "Contacting AI provider for {model}...",
    "ai_status_wait": "Waiting for AI response...",
    "ai_status_parse": "Processing AI response...",
    "ai_status_done": "Done.",
    "ai_status_error": "Error:",
    "ai_result_title": "AI Generated Result",
    "ai_success": "✓ Request successful.",
    "ai_timeout_warning": "⚠️ Request exceeded 30 seconds, processing may take a while. Please continue waiting...",
    "ai_assist.local_model_not_running": "Local model unavailable - using external model instead.",
    "ai_assist_local_model_not_running": "Local model unavailable - using external model instead.",
    "apply": "Apply",
    "analytics_average": "Average",
    "analytics_bar": "Bar",
    "analytics_chart_label": "Chart:",
    "analytics_line": "Line",
    "analytics_leave_hours": "Leave Hours",
    "analytics_metric_label": "Metric:",
    "analytics_show_leave": "Show leave",
    "analytics_work_hours": "Work hours",
    "backup_data": "Backup Data",
    "backup_description": "Back up your database regularly to protect your local work logs, reports, settings, and account data.",
    "backup_reminder": "You haven't backed up in {days} days. Please back up your data.",
    "btn_cancel": "Cancel",
    "btn_regenerate": "Regenerate",
    "cal_imported": "Imported {} calendar events.",
    "choose_custom_color": "Choose custom color",
    "csv_data_management": "CSV Data Management",
    "csv_description": "Import or export worklog records as CSV files for backup, migration, or spreadsheet analysis.",
    "custom_theme_color": "Custom theme color",
    "enable_menu_bar": "Enable menu bar icon",
    "enable_tray": "Enable tray icon",
    "end_now": "End now",
    "features_overview_v3": """Work Logger is a privacy-first desktop app for recording work time, notes, quick logs, calendar context, and recurring reports without sending your data to a cloud service by default.

Daily logging:
- Enter start, end, break, work type, and notes for each date.
- Use Auto Record buttons for start, end, and break checkpoints.
- Capture lightweight task details with Quick Log and merge them into reports.
- Navigate by calendar, month, week, or minimal-mode day controls.

Accounts and security:
- Multiple local users are supported, and each user's worklogs, settings, reports, reminders, and backups are isolated.
- Passwords and recovery keys are stored as secure hashes.
- Administrators can reset user passwords and regenerate recovery keys when needed.
- Remember-me login uses the operating system credential manager when available.

Reports and templates:
- Generate daily notes, weekly reports, and monthly reports from saved data.
- Weekly and monthly reports are tied to the selected calendar period and can be saved for later editing.
- Built-in and custom templates help standardize recurring note and report formats.

Analytics and exports:
- Review work hours, averages, overtime, targets, leave markers, and trend charts.
- Export chart data to CSV and charts to PDF.
- Import/export worklogs as CSV and calendar events as ICS.
- Back up and restore the local database with reminders for stale backups.

Customization and AI:
- Switch languages, themes, custom accent colors, dark mode, and minimal mode.
- Use local-model assistance when configured, or connect to OpenAI-compatible external providers such as ChatGPT, Claude, Qwen, and DeepSeek.
- Supported UI languages include English, Japanese, Korean, Simplified Chinese, and Traditional Chinese.""",
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
    "analytics_leave": "Leave",
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
    "minimal_mode": "Minimal mode",
    "minimal_mode_restart_required": "Restart required to apply minimal mode.",
    "minimal_mode_toggle_restart": "Minimal mode toggle will take effect after restarting the application.",
    "open_color_picker": "Open color picker",
    "original_content": "Original Content",
    "period": "Period",
    "previous_day": "Previous day",
    "next_day": "Next day",
    "quick_log_add": "Add",
    "quick_log_delete": "Delete",
    "report_copy": "Copy",
    "report_copied": "Copied!",
    "report_download": "Download .md",
    "report_monthly": "Monthly Report",
    "report_weekly": "Weekly Report",
    "restore_data": "Restore Data",
    "settings_database_backup": "Database Backup",
    "restart_required": "Restart Required",
    "settings_ai_local_model_disabled_tooltip": "Local model is disabled.",
    "selected_color": "Selected color",
    "start_now": "Start now",
    "template_daily": "Daily",
    "template_default": "Default",
    "template_invoice": "Invoice",
    "template_monthly": "Monthly",
    "template_sample": "Sample Template",
    "template_timesheet": "Timesheet",
    "template_weekly": "Weekly",
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


def detect_system_language() -> str | None:
    try:
        loc = locale.getdefaultlocale()[0]  # type: ignore[index]
    except Exception:
        return None
    if not loc:
        return None

    low = str(loc).strip().replace("-", "_").split(".", 1)[0].lower()
    if low.startswith(("zh_tw", "zh_hant", "zh_hk", "zh_mo")):
        return "zh_TW"
    if low.startswith("zh"):
        return "zh_CN"
    if low.startswith("ja"):
        return "ja_JP"
    if low.startswith("ko"):
        return "ko_KR"
    if low.startswith("en"):
        return "en_US"
    return None


def _default_lang() -> str:
    return detect_system_language() or "en_US"


def _messages_catalog_path(locales_dir: Path, locale_code: str) -> Path:
    return locales_dir / locale_code / "LC_MESSAGES" / f"{DOMAIN}.mo"


def _is_readable_file(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        with path.open("rb"):
            return True
    except OSError:
        return False


def _frozen_root_candidates() -> list[Path]:
    roots: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
    if getattr(sys, "frozen", False):
        try:
            exe_dir = Path(sys.executable).resolve().parent
            roots.append(exe_dir)
            roots.append(exe_dir.parent / "Resources")
        except Exception:
            pass
    return roots


def _candidate_locales_dirs() -> list[Path]:
    candidates: list[Path] = [_DEV_LOCALES_DIR]
    for root in _frozen_root_candidates():
        candidates.append(root / "locales")
        # Backward-compatible fallback for older bundles.
        candidates.append(root / "worklogger" / "locales")

    deduped: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = os.path.normcase(str(path.resolve(strict=False)))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _resolve_locales_dir(lang: str | None = None) -> Path:
    locale_code = LOCALE_CODE_MAP.get(_normalize_lang(lang), LOCALE_CODE_MAP["en_US"])
    candidates = _candidate_locales_dirs()

    for candidate in candidates:
        if _is_readable_file(_messages_catalog_path(candidate, locale_code)):
            return candidate
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _set_process_locale(lang: str) -> None:
    locale_code = LOCALE_CODE_MAP.get(lang, LOCALE_CODE_MAP["en_US"])
    candidates = [
        f"{locale_code}.UTF-8",
        f"{locale_code}.utf8",
        locale_code,
    ]
    normalized = locale.normalize(f"{locale_code}.UTF-8")
    if normalized and normalized not in candidates:
        candidates.append(normalized)
    if os.name == "nt":
        windows_fallbacks = {
            "en_US": ("English_United States.1252",),
            "ja_JP": ("Japanese_Japan.932",),
            "ko_KR": ("Korean_Korea.949",),
            "zh_CN": ("Chinese_China.936",),
            "zh_TW": ("Chinese_Taiwan.950",),
        }
        candidates.extend(windows_fallbacks.get(locale_code, ()))

    for candidate in candidates:
        try:
            locale.setlocale(locale.LC_ALL, candidate)
            return
        except locale.Error:
            continue


def _bind_gettext_runtime(lang: str, locales_dir: Path) -> None:
    _apply_locale_env(lang)
    try:
        gettext.bindtextdomain(DOMAIN, str(locales_dir))
    except Exception:
        pass
    try:
        gettext.textdomain(DOMAIN)
    except Exception:
        pass
    _set_process_locale(lang)


def _apply_locale_env(lang: str) -> None:
    locale_code = LOCALE_CODE_MAP.get(lang, LOCALE_CODE_MAP["en_US"])
    os.environ["LANGUAGE"] = locale_code
    os.environ["LANG"] = f"{locale_code}.UTF-8"
    os.environ["LC_ALL"] = f"{locale_code}.UTF-8"


@lru_cache(maxsize=32)
def _load_translation(lang: str, locales_dir: str) -> gettext.NullTranslations:
    locale_code = LOCALE_CODE_MAP.get(lang, LOCALE_CODE_MAP["en_US"])
    try:
        return gettext.translation(
            DOMAIN,
            locales_dir,
            languages=[locale_code],
            fallback=True,
        )
    except Exception:
        return gettext.NullTranslations()


def get_language() -> str:
    return _normalize_lang(getattr(_lang_state, "current", _default_lang()))


def set_language(lang: str | None) -> str:
    global LOCALES_DIR
    norm = _normalize_lang(lang)
    locales_dir = _resolve_locales_dir(norm)
    if LOCALES_DIR != locales_dir:
        _load_translation.cache_clear()
    LOCALES_DIR = locales_dir
    _bind_gettext_runtime(norm, locales_dir)
    _lang_state.current = norm
    return norm


def get_translator(lang: str | None = None) -> gettext.NullTranslations:
    norm = _normalize_lang(lang) if lang else get_language()
    locales_dir = _resolve_locales_dir(norm)
    return _load_translation(norm, str(locales_dir))


def get_i18n_diagnostics(lang: str | None = None) -> dict[str, object]:
    norm = _normalize_lang(lang) if lang else get_language()
    locale_code = LOCALE_CODE_MAP.get(norm, LOCALE_CODE_MAP["en_US"])
    selected = _resolve_locales_dir(norm)
    mo_path = _messages_catalog_path(selected, locale_code)
    candidates = _candidate_locales_dirs()
    return {
        "language": norm,
        "locale_code": locale_code,
        "domain": DOMAIN,
        "sys_frozen": bool(getattr(sys, "frozen", False)),
        "sys_meipass": str(getattr(sys, "_MEIPASS", "")),
        "selected_locales_dir": str(selected),
        "selected_exists": selected.exists(),
        "catalog_path": str(mo_path),
        "catalog_exists": mo_path.exists(),
        "catalog_readable": _is_readable_file(mo_path),
        "candidate_locales_dirs": [str(path) for path in candidates],
    }


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
