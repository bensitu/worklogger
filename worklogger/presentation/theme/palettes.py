"""Resolve accent definitions against reusable material color profiles."""

from functools import lru_cache

from worklogger.config.themes import AccentColors, ThemeDefinition
from worklogger.domain.settings.appearance import DEFAULT_CUSTOM_COLOR, normalize_hex_color
from worklogger.presentation.theme.models import ColorPalette


@lru_cache(maxsize=32)
def build_palette(definition: ThemeDefinition, dark: bool, custom_color: str | None) -> ColorPalette:
    colors = (AccentColors(*_custom_palette(custom_color or DEFAULT_CUSTOM_COLOR)[dark])
              if definition.customizable else definition.dark if dark else definition.light)
    accent, hover, accent_dim, stat_background, stat_border = (
        colors.accent, colors.hover, colors.accent_dim, colors.stat_background, colors.stat_border)
    if dark:
        background, surface, surface_alt = "#111827", "#182033", "#202a42"
        card, card_hover = "#1b2438", "#22304b"
        border, border_strong = "#303b56", "#4b5a78"
        text, muted = "#c8cde8", "#8890b8"
        input_background, input_border = "#181928", "#33365a"
        sidebar_background, sidebar_active = "#141d2d", "#172f58"
        danger, success, warning = "#ff6b6b", "#45c97a", "#ffb84d"
        table_alternate, button_hover = surface_alt, "#2c2e50"
        disabled_text, disabled_background = "#6f7699", background
    else:
        background, surface, surface_alt = "#f5f7fb", "#ffffff", "#f8fafc"
        card, card_hover = "#ffffff", "#f3f7ff"
        border, border_strong = "#dce3ef", "#c7d0df"
        text, muted = "#1e2035", "#606888"
        input_background, input_border = "#ffffff", "#d0d5e8"
        sidebar_background, sidebar_active = "#ffffff", "#eaf2ff"
        danger, success, warning = "#ef4444", "#16a34a", "#f59e0b"
        table_alternate, button_hover = surface, "#e8ecf8"
        disabled_text, disabled_background = "#9aa3bb", "#edf0f5"
    if definition.material == "glass":
        background, surface, surface_alt = (("#20252a", "#252c32", "#30383f") if dark else
                                          ("#e5edf1", "#f3f7fa", "#eaf1f5"))
        card, card_hover = surface, surface_alt
        border, border_strong = (("#53636c", "#71838d") if dark else ("#bdced9", "#a5bac7"))
        text, muted = (("#e8eef3", "#b2bdc6") if dark else ("#182b35", "#506976"))
        input_background, input_border = (("#222a30", "#697b85") if dark else ("#ffffff", "#aabdc9"))
        sidebar_background, sidebar_active = surface, accent_dim
        table_alternate, button_hover = surface_alt if dark else input_background, surface_alt
        disabled_text, disabled_background = (("#8e9ba5", "#30383f") if dark else ("#7e939f", "#e4edf2"))
        danger, success, warning = (("#ff9baf", "#87e5ba", "#f4d989") if dark else
                                    ("#a9243a", "#166c44", "#875900"))
    return ColorPalette(
        theme=definition.key,
        material=definition.material,
        dark=bool(dark),
        accent=accent,
        hover=hover,
        accent_dim=accent_dim,
        stat_background=stat_background,
        stat_border=stat_border,
        background=background,
        surface=surface,
        surface_alt=surface_alt,
        table_alternate=table_alternate,
        button_hover=button_hover,
        disabled_text=disabled_text,
        disabled_background=disabled_background,
        highlighted_text="#10242a" if definition.material == "glass" and dark else "#ffffff",
        login_hero_background="#111827",
        card=card,
        card_hover=card_hover,
        border=border,
        border_strong=border_strong,
        text=text,
        muted_text=muted,
        input_background=input_background,
        input_border=input_border,
        sidebar_background=sidebar_background,
        sidebar_active_background=sidebar_active,
        danger=danger,
        success=success,
        warning=warning,
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
