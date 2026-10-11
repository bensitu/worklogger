"""Validated, immutable theme colors without GUI dependencies."""

from dataclasses import dataclass, fields
import re


def validate_color(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError("Theme colors must use six-digit hexadecimal notation")


@dataclass(frozen=True)
class AccentColors:
    accent: str
    hover: str
    accent_dim: str
    stat_background: str
    stat_border: str

    def __post_init__(self):
        for field in fields(AccentColors):
            validate_color(getattr(self, field.name))


@dataclass(frozen=True)
class SurfaceColors:
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

    def __post_init__(self):
        for field in fields(SurfaceColors):
            validate_color(getattr(self, field.name))


@dataclass(frozen=True, init=False)
class SurfaceOverrides:
    colors: tuple[tuple[str, str], ...]

    def __init__(self, **colors: str):
        allowed = {field.name for field in fields(SurfaceColors)}
        if colors.keys() - allowed:
            raise ValueError("Unknown theme surface color")
        for value in colors.values():
            validate_color(value)
        object.__setattr__(self, "colors", tuple(sorted(colors.items())))
