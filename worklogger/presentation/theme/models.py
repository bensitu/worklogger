"""Resolved theme colors and calendar appearance values."""

from dataclasses import dataclass

@dataclass(frozen=True)
class ColorPalette:
    theme: str
    dark: bool
    accent: str
    hover: str
    accent_dim: str
    stat_background: str
    stat_border: str
    background: str
    surface: str
    surface_alt: str
    table_alternate: str
    button_hover: str
    disabled_text: str
    disabled_background: str
    highlighted_text: str
    login_hero_background: str
    card: str
    card_hover: str
    border: str
    border_strong: str
    text: str
    muted_text: str
    input_background: str
    input_border: str
    sidebar_background: str
    sidebar_active_background: str
    danger: str
    success: str
    warning: str
    material: str = "solid"


@dataclass(frozen=True)
class CalendarCellStyle:
    key: str
    background: str
    foreground: str
    border: str
    border_width: int
    hover_border: str
    holiday_foreground: str = "#ef4444"
    highlighted_foreground: str = "#ffffff"
