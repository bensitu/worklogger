"""Resolved theme colors and calendar appearance values."""

from dataclasses import dataclass
from worklogger.config.theme_colors import SurfaceColors


@dataclass(frozen=True)
class ColorPalette(SurfaceColors):
    theme: str
    dark: bool
    accent: str
    hover: str
    accent_dim: str
    stat_background: str
    stat_border: str
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
