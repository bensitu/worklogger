"""Stored appearance choices and color validation independent of Qt."""

import re

from worklogger.config.themes import THEME_KEYS as THEME_KEYS, normalize_theme as normalize_theme

DEFAULT_CUSTOM_COLOR = "#4f8ef7"


def normalize_hex_color(value: str | None) -> str:
    raw = str(value or "").strip()
    return "#" + raw.lstrip("#").lower() if re.fullmatch(r"#?[0-9a-fA-F]{6}", raw) else DEFAULT_CUSTOM_COLOR
