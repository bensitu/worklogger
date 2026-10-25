"""Validation and canonical encoding for writable account preferences."""

import base64
import math

from worklogger.config.constants import (
    CUSTOM_THEME_COLOR_SETTING_KEY, LANGUAGE_SETTING_KEY,
    LOCAL_MODEL_CONTEXT_TOKENS_SETTING_KEY, NETWORK_PROXY_PASSWORD_SETTING_KEY,
    NETWORK_PROXY_PORT_SETTING_KEY, PROFILE_AVATAR_SETTING_KEY, THEME_SETTING_KEY,
    WORK_SCHEDULE_SETTING_KEY,
    WORK_TARGET_MODE_SETTING_KEY,
    WINDOW_CLOSE_ACTION_SETTING_KEY,
)
from worklogger.domain.local_model.preferences import normalize_runtime_context
from worklogger.domain.settings.appearance import normalize_hex_color, normalize_theme
from worklogger.domain.settings.preferences import BOOLEAN_SETTING_KEYS, NUMERIC_SETTING_LIMITS, SETTINGS_DEFAULTS, format_setting_number, normalize_proxy_port
from worklogger.domain.settings.values import setting_bool
from worklogger.domain.shared.languages import normalize_language
from worklogger.domain.settings.work_schedule import WorkSchedule
from worklogger.domain.settings.window_behavior import WindowCloseAction


def normalize_setting(key, value):
    if key not in SETTINGS_DEFAULTS or key == NETWORK_PROXY_PASSWORD_SETTING_KEY:
        raise ValueError("setting_key_invalid")
    if value is None:
        raise ValueError("setting_value_invalid")
    text = str(value).strip()
    if key == WORK_SCHEDULE_SETTING_KEY:
        return WorkSchedule.decode(text).encode()
    if key == WORK_TARGET_MODE_SETTING_KEY:
        if text not in {"manual", "schedule"}:
            raise ValueError("setting_value_invalid")
        return text
    if key == WINDOW_CLOSE_ACTION_SETTING_KEY:
        try:
            return WindowCloseAction(text).value
        except ValueError:
            raise ValueError("setting_value_invalid") from None
    if key in BOOLEAN_SETTING_KEYS:
        if text.lower() not in {"1", "0", "true", "false", "yes", "no", "on", "off"}:
            raise ValueError("setting_value_invalid")
        return "1" if setting_bool(text) else "0"
    if key in NUMERIC_SETTING_LIMITS:
        try:
            number = float(text)
        except ValueError:
            raise ValueError("invalid_numeric_setting") from None
        minimum, maximum = NUMERIC_SETTING_LIMITS[key]
        if not math.isfinite(number) or not minimum <= number <= maximum:
            raise ValueError("invalid_numeric_setting")
        return format_setting_number(number)
    if key == LOCAL_MODEL_CONTEXT_TOKENS_SETTING_KEY:
        return str(normalize_runtime_context(value))
    if key == NETWORK_PROXY_PORT_SETTING_KEY:
        return normalize_proxy_port(text)
    if key == THEME_SETTING_KEY:
        if normalize_theme(text) != text.lower():
            raise ValueError("setting_value_invalid")
        return text.lower()
    if key == CUSTOM_THEME_COLOR_SETTING_KEY:
        return normalize_hex_color(text)
    if key == LANGUAGE_SETTING_KEY:
        return normalize_language(text)
    if key == PROFILE_AVATAR_SETTING_KEY:
        try:
            valid = len(text) <= 512 * 1024 and (not text or base64.b64decode(text, validate=True).startswith(b"\x89PNG\r\n\x1a\n"))
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("avatar_image_invalid")
    elif len(text) > 8192:
        raise ValueError("setting_value_invalid")
    return text
