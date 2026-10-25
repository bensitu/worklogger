"""Platform-specific desktop integration preferences."""

import sys

from worklogger.config.constants import ENABLE_MENU_BAR_SETTING_KEY, ENABLE_TRAY_SETTING_KEY


def residency_setting_key(platform: str | None = None) -> str | None:
    value = str(platform or sys.platform).lower()
    if value.startswith(("win", "linux")):
        return ENABLE_TRAY_SETTING_KEY
    if value == "darwin":
        return ENABLE_MENU_BAR_SETTING_KEY
    return None
