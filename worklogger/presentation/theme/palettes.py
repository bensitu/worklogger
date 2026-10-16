"""Resolve accent definitions against reusable material color profiles."""

from functools import lru_cache
from dataclasses import asdict, replace

from worklogger.config.themes import AccentColors, ThemeDefinition
from worklogger.domain.settings.appearance import DEFAULT_CUSTOM_COLOR, normalize_hex_color
from worklogger.presentation.theme.models import ColorPalette
from worklogger.presentation.theme.materials import material_profile
from worklogger.presentation.theme.color_contrast import mix_colors, scale_color


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
            scale_color(accent, 0.82),
            mix_colors(accent, "#ffffff", 0.86),
            mix_colors(accent, "#ffffff", 0.93),
            mix_colors(accent, "#ffffff", 0.66),
        ),
        True: (
            mix_colors(accent, "#ffffff", 0.12),
            accent,
            mix_colors(accent, "#000000", 0.68),
            mix_colors(accent, "#000000", 0.78),
            mix_colors(accent, "#000000", 0.52),
        ),
    }
