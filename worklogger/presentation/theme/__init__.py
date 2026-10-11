"""Presentation theme helpers."""

from worklogger.presentation.theme.theme_engine import (
    CalendarCellStyle,
    ColorPalette,
    DEFAULT_CUSTOM_COLOR,
    THEME_KEYS,
    ThemeEngine,
    normalize_hex_color,
)


def install_bundled_fonts() -> None:
    from worklogger.presentation.theme.fonts import install_bundled_fonts as install
    install()


def configure_application_style() -> None:
    from worklogger.presentation.theme.platform_style import configure_application_style as configure
    configure()

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
