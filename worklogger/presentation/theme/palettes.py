"""Resolve accent definitions against reusable material color profiles."""

from functools import lru_cache
from dataclasses import asdict, replace

from worklogger.config.themes import AccentColors, ThemeDefinition
from worklogger.domain.settings.appearance import DEFAULT_CUSTOM_COLOR, normalize_hex_color
from worklogger.presentation.theme.models import ColorPalette
from worklogger.presentation.theme.materials import material_profile


@lru_cache(maxsize=32)
def build_palette(definition: ThemeDefinition, dark: bool, custom_color: str | None) -> ColorPalette:
    colors = (AccentColors(*_custom_palette(custom_color or DEFAULT_CUSTOM_COLOR)[dark])
              if definition.customizable else definition.dark if dark else definition.light)
    accent, hover, accent_dim, stat_background, stat_border = (
        colors.accent, colors.hover, colors.accent_dim, colors.stat_background, colors.stat_border)
    profile = material_profile(definition.material)
    surfaces = profile.surfaces(dark)
    if profile.translucent:
        surfaces = replace(surfaces, sidebar_active_background=accent_dim)
    overrides = definition.dark_overrides if dark else definition.light_overrides
    if overrides is not None:
        surfaces = replace(surfaces, **dict(overrides.colors))
    return ColorPalette(
        theme=definition.key,
        material=definition.material,
        dark=bool(dark),
        accent=accent,
        hover=hover,
        accent_dim=accent_dim,
        stat_background=stat_background,
        stat_border=stat_border,
        **asdict(surfaces),
    )


def _custom_palette(accent_hex: str) -> dict[bool, tuple[str, str, str, str, str]]:
    accent = normalize_hex_color(accent_hex)
    return {
        False: (
            accent,
            _scale(accent, 0.82),
            _mix(accent, "#ffffff", 0.86),
            _mix(accent, "#ffffff", 0.93),
            _mix(accent, "#ffffff", 0.66),
        ),
        True: (
            _mix(accent, "#ffffff", 0.12),
            accent,
            _mix(accent, "#000000", 0.68),
            _mix(accent, "#000000", 0.78),
            _mix(accent, "#000000", 0.52),
        ),
    }


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    color = normalize_hex_color(hex_color).lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    r, g, b = (max(0, min(255, int(value))) for value in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _mix(hex_color: str, other: str, amount: float) -> str:
    r1, g1, b1 = _hex_to_rgb(hex_color)
    r2, g2, b2 = _hex_to_rgb(other)
    t = max(0.0, min(1.0, amount))
    return _rgb_to_hex(
        (
            round(r1 + (r2 - r1) * t),
            round(g1 + (g2 - g1) * t),
            round(b1 + (b2 - b1) * t),
        )
    )


def _scale(hex_color: str, factor: float) -> str:
    r, g, b = _hex_to_rgb(hex_color)
    return _rgb_to_hex((round(r * factor), round(g * factor), round(b * factor)))
