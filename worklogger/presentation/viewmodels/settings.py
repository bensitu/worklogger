"""Settings presentation ViewModel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from worklogger.app.commands.settings_commands import SetSettingCommand
from worklogger.app.queries.settings_queries import GetSettingQuery
from worklogger.config.constants import (
    AI_ASSIST_ENABLED_SETTING_KEY,
    AI_PRIVACY_INCLUDE_CALENDAR_SETTING_KEY,
    AI_PRIVACY_INCLUDE_NOTES_SETTING_KEY,
    AI_PRIVACY_INCLUDE_QUICK_LOGS_SETTING_KEY,
    CUSTOM_THEME_COLOR_SETTING_KEY,
    DARK_MODE_SETTING_KEY,
    DEFAULT_BREAK_HOURS_SETTING_KEY,
    ENABLE_MENU_BAR_SETTING_KEY,
    ENABLE_TRAY_SETTING_KEY,
    EXTERNAL_MODEL_BASE_URL_SETTING_KEY,
    EXTERNAL_MODEL_NAME_SETTING_KEY,
    LANGUAGE_SETTING_KEY,
    LOCAL_MODEL_ENABLED_SETTING_KEY,
    MINIMAL_MODE_SETTING_KEY,
    MONTHLY_TARGET_HOURS_SETTING_KEY,
    NETWORK_PROXY_ADDRESS_SETTING_KEY,
    NETWORK_PROXY_DOMAIN_SETTING_KEY,
    NETWORK_PROXY_ENABLED_SETTING_KEY,
    NETWORK_PROXY_PASSWORD_SETTING_KEY,
    NETWORK_PROXY_PORT_SETTING_KEY,
    NETWORK_PROXY_USERNAME_SETTING_KEY,
    SHOW_HOLIDAYS_SETTING_KEY,
    SHOW_NOTE_MARKERS_SETTING_KEY,
    SHOW_OVERNIGHT_INDICATOR_SETTING_KEY,
    STANDARD_WORK_HOURS_SETTING_KEY,
    THEME_SETTING_KEY,
    WEEK_START_MONDAY_SETTING_KEY,
)
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import normalize_language
from worklogger.presentation.theme import DEFAULT_CUSTOM_COLOR, THEME_KEYS, normalize_hex_color


class SettingsGetHandler(Protocol):
    def handle(self, query: GetSettingQuery) -> Result[str | None]:
        ...


class SettingsSetHandler(Protocol):
    def handle(self, command: SetSettingCommand) -> Result[None]:
        ...


@dataclass(frozen=True)
class SettingsState:
    theme: str
    custom_color: str
    dark_mode: bool
    language: str
    ai_assist_enabled: bool
    ai_privacy_include_notes: bool
    ai_privacy_include_calendar: bool
    ai_privacy_include_quick_logs: bool
    external_model_base_url: str
    external_model_name: str
    minimal_mode: bool
    local_model_enabled: bool
    standard_work_hours: float
    default_break_hours: float
    monthly_target_hours: float
    show_holidays: bool
    show_note_markers: bool
    show_overnight_indicator: bool
    week_start_monday: bool
    enable_tray: bool
    enable_menu_bar: bool
    network_proxy_enabled: bool
    network_proxy_address: str
    network_proxy_port: str
    network_proxy_username: str
    network_proxy_password: str
    network_proxy_domain: str


class SettingsViewModel:
    def __init__(
        self,
        *,
        user_id: int,
        get_handler: SettingsGetHandler,
        set_handler: SettingsSetHandler,
    ) -> None:
        self._user_id = user_id
        self._get_handler = get_handler
        self._set_handler = set_handler

    def load(self) -> Result[SettingsState]:
        values: dict[str, str | None] = {}
        for key, default in _DEFAULTS.items():
            result = self._get_handler.handle(GetSettingQuery(self._user_id, key, default))
            if not result.ok:
                return Result.failure(
                    result.error or ValidationError("settings_load_failed", "settings_load_failed")
                )
            values[key] = result.value
        return Result.success(
            SettingsState(
                theme=_theme(values[THEME_SETTING_KEY]),
                custom_color=normalize_hex_color(values[CUSTOM_THEME_COLOR_SETTING_KEY]),
                dark_mode=_bool(values[DARK_MODE_SETTING_KEY], False),
                language=normalize_language(values[LANGUAGE_SETTING_KEY]),
                ai_assist_enabled=_bool(values[AI_ASSIST_ENABLED_SETTING_KEY], True),
                ai_privacy_include_notes=_bool(
                    values[AI_PRIVACY_INCLUDE_NOTES_SETTING_KEY],
                    True,
                ),
                ai_privacy_include_calendar=_bool(
                    values[AI_PRIVACY_INCLUDE_CALENDAR_SETTING_KEY],
                    True,
                ),
                ai_privacy_include_quick_logs=_bool(
                    values[AI_PRIVACY_INCLUDE_QUICK_LOGS_SETTING_KEY],
                    True,
                ),
                external_model_base_url=_text(
                    values[EXTERNAL_MODEL_BASE_URL_SETTING_KEY],
                    "https://api.openai.com/v1",
                ),
                external_model_name=_text(
                    values[EXTERNAL_MODEL_NAME_SETTING_KEY],
                    "gpt-4o-mini",
                ),
                minimal_mode=_bool(values[MINIMAL_MODE_SETTING_KEY], False),
                local_model_enabled=_bool(values[LOCAL_MODEL_ENABLED_SETTING_KEY], True),
                standard_work_hours=_number(
                    values[STANDARD_WORK_HOURS_SETTING_KEY],
                    8.0,
                    minimum=1.0,
                    maximum=24.0,
                ),
                default_break_hours=_number(
                    values[DEFAULT_BREAK_HOURS_SETTING_KEY],
                    1.0,
                    minimum=0.0,
                    maximum=4.0,
                ),
                monthly_target_hours=_number(
                    values[MONTHLY_TARGET_HOURS_SETTING_KEY],
                    168.0,
                    minimum=0.0,
                    maximum=400.0,
                ),
                show_holidays=_bool(values[SHOW_HOLIDAYS_SETTING_KEY], True),
                show_note_markers=_bool(values[SHOW_NOTE_MARKERS_SETTING_KEY], True),
                show_overnight_indicator=_bool(
                    values[SHOW_OVERNIGHT_INDICATOR_SETTING_KEY],
                    True,
                ),
                week_start_monday=_bool(values[WEEK_START_MONDAY_SETTING_KEY], False),
                enable_tray=_bool(values[ENABLE_TRAY_SETTING_KEY], False),
                enable_menu_bar=_bool(values[ENABLE_MENU_BAR_SETTING_KEY], False),
                network_proxy_enabled=_bool(
                    values[NETWORK_PROXY_ENABLED_SETTING_KEY],
                    False,
                ),
                network_proxy_address=_text(values[NETWORK_PROXY_ADDRESS_SETTING_KEY], ""),
                network_proxy_port=_text(values[NETWORK_PROXY_PORT_SETTING_KEY], "0"),
                network_proxy_username=_text(values[NETWORK_PROXY_USERNAME_SETTING_KEY], ""),
                network_proxy_password=_text(values[NETWORK_PROXY_PASSWORD_SETTING_KEY], ""),
                network_proxy_domain=_text(values[NETWORK_PROXY_DOMAIN_SETTING_KEY], ""),
            )
        )

    def set_theme(self, theme: str) -> Result[None]:
        return self._set(THEME_SETTING_KEY, _theme(theme))

    def set_custom_color(self, color: str) -> Result[None]:
        return self._set(CUSTOM_THEME_COLOR_SETTING_KEY, normalize_hex_color(color))

    def set_language(self, language: str) -> Result[None]:
        return self._set(LANGUAGE_SETTING_KEY, normalize_language(language))

    def set_bool(self, key: str, enabled: bool) -> Result[None]:
        if key not in _BOOLEAN_KEYS:
            return Result.failure(ValidationError("unknown_boolean_setting", "unknown_boolean_setting"))
        return self._set(key, "1" if enabled else "0")

    def set_number(self, key: str, value: float) -> Result[None]:
        limits = _NUMBER_LIMITS.get(key)
        if limits is None:
            return Result.failure(ValidationError("unknown_numeric_setting", "unknown_numeric_setting"))
        minimum, maximum = limits
        numeric = _number(str(value), value, minimum=minimum, maximum=maximum)
        return self._set(key, _format_number(numeric))

    def set_text(self, key: str, value: str) -> Result[None]:
        if key not in _TEXT_KEYS:
            return Result.failure(ValidationError("unknown_text_setting", "unknown_text_setting"))
        cleaned = str(value or "").strip()
        if key == NETWORK_PROXY_PORT_SETTING_KEY:
            cleaned = _proxy_port(cleaned)
        return self._set(key, cleaned)

    def _set(self, key: str, value: str) -> Result[None]:
        result = self._set_handler.handle(
            SetSettingCommand(
                user_id=self._user_id,
                key=key,
                value=value,
            )
        )
        if not result.ok:
            return Result.failure(
                result.error or ValidationError("settings_save_failed", "settings_save_failed")
            )
        return Result.success(None)


_DEFAULTS = {
    THEME_SETTING_KEY: "blue",
    CUSTOM_THEME_COLOR_SETTING_KEY: DEFAULT_CUSTOM_COLOR,
    DARK_MODE_SETTING_KEY: "0",
    LANGUAGE_SETTING_KEY: "en_US",
    AI_ASSIST_ENABLED_SETTING_KEY: "1",
    AI_PRIVACY_INCLUDE_NOTES_SETTING_KEY: "1",
    AI_PRIVACY_INCLUDE_CALENDAR_SETTING_KEY: "1",
    AI_PRIVACY_INCLUDE_QUICK_LOGS_SETTING_KEY: "1",
    EXTERNAL_MODEL_BASE_URL_SETTING_KEY: "https://api.openai.com/v1",
    EXTERNAL_MODEL_NAME_SETTING_KEY: "gpt-4o-mini",
    MINIMAL_MODE_SETTING_KEY: "0",
    LOCAL_MODEL_ENABLED_SETTING_KEY: "1",
    STANDARD_WORK_HOURS_SETTING_KEY: "8.0",
    DEFAULT_BREAK_HOURS_SETTING_KEY: "1.0",
    MONTHLY_TARGET_HOURS_SETTING_KEY: "168.0",
    SHOW_HOLIDAYS_SETTING_KEY: "1",
    SHOW_NOTE_MARKERS_SETTING_KEY: "1",
    SHOW_OVERNIGHT_INDICATOR_SETTING_KEY: "1",
    WEEK_START_MONDAY_SETTING_KEY: "0",
    ENABLE_TRAY_SETTING_KEY: "0",
    ENABLE_MENU_BAR_SETTING_KEY: "0",
    NETWORK_PROXY_ENABLED_SETTING_KEY: "0",
    NETWORK_PROXY_ADDRESS_SETTING_KEY: "",
    NETWORK_PROXY_PORT_SETTING_KEY: "0",
    NETWORK_PROXY_USERNAME_SETTING_KEY: "",
    NETWORK_PROXY_PASSWORD_SETTING_KEY: "",
    NETWORK_PROXY_DOMAIN_SETTING_KEY: "",
}

_BOOLEAN_KEYS = frozenset(
    {
        DARK_MODE_SETTING_KEY,
        AI_ASSIST_ENABLED_SETTING_KEY,
        AI_PRIVACY_INCLUDE_NOTES_SETTING_KEY,
        AI_PRIVACY_INCLUDE_CALENDAR_SETTING_KEY,
        AI_PRIVACY_INCLUDE_QUICK_LOGS_SETTING_KEY,
        MINIMAL_MODE_SETTING_KEY,
        LOCAL_MODEL_ENABLED_SETTING_KEY,
        SHOW_HOLIDAYS_SETTING_KEY,
        SHOW_NOTE_MARKERS_SETTING_KEY,
        SHOW_OVERNIGHT_INDICATOR_SETTING_KEY,
        WEEK_START_MONDAY_SETTING_KEY,
        ENABLE_TRAY_SETTING_KEY,
        ENABLE_MENU_BAR_SETTING_KEY,
        NETWORK_PROXY_ENABLED_SETTING_KEY,
    }
)

_TEXT_KEYS = frozenset(
    {
        EXTERNAL_MODEL_BASE_URL_SETTING_KEY,
        EXTERNAL_MODEL_NAME_SETTING_KEY,
        NETWORK_PROXY_ADDRESS_SETTING_KEY,
        NETWORK_PROXY_PORT_SETTING_KEY,
        NETWORK_PROXY_USERNAME_SETTING_KEY,
        NETWORK_PROXY_PASSWORD_SETTING_KEY,
        NETWORK_PROXY_DOMAIN_SETTING_KEY,
    }
)

_NUMBER_LIMITS = {
    STANDARD_WORK_HOURS_SETTING_KEY: (1.0, 24.0),
    DEFAULT_BREAK_HOURS_SETTING_KEY: (0.0, 4.0),
    MONTHLY_TARGET_HOURS_SETTING_KEY: (0.0, 400.0),
}


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _number(
    value: str | None,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    try:
        numeric = float(str(value))
    except (TypeError, ValueError):
        numeric = default
    return max(minimum, min(maximum, numeric))


def _text(value: str | None, default: str) -> str:
    text = str(value if value is not None else default).strip()
    return text


def _theme(value: str | None) -> str:
    theme = str(value or "blue").strip().lower()
    return theme if theme in THEME_KEYS else "blue"


def _format_number(value: float) -> str:
    return f"{float(value):.2f}".rstrip("0").rstrip(".")


def _proxy_port(value: str) -> str:
    try:
        port = int(str(value or "0").strip())
    except (TypeError, ValueError):
        port = 0
    return str(max(0, min(65535, port)))
