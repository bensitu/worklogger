"""Presentation theme helpers."""

from worklogger.presentation.theme.fonts import install_bundled_fonts
from worklogger.presentation.theme.platform_style import configure_application_style
from worklogger.presentation.theme.theme_engine import (
    CalendarCellStyle,
    ColorPalette,
    DEFAULT_CUSTOM_COLOR,
    THEME_KEYS,
    ThemeEngine,
    normalize_hex_color,
)

__all__ = [
    "CalendarCellStyle",
    "ColorPalette",
    "DEFAULT_CUSTOM_COLOR",
    "THEME_KEYS",
    "ThemeEngine",
    "configure_application_style",
    "install_bundled_fonts",
    "normalize_hex_color",
]
