"""Cached stylesheet loading and strict token substitution."""

from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
import re
from types import MappingProxyType

from worklogger.presentation.theme.models import ColorPalette
from worklogger.presentation.theme.materials import MATERIAL_PROFILES, material_profile

_QSS_ROOT = Path(__file__).with_name("qss")
_QSS_TOKEN_RE = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
COMMON_TEMPLATES = (
    "surfaces.qss", "calendar.qss", "typography.qss", "buttons.qss",
    "inputs.qss", "scrolling.qss", "settings.qss", "date_picker.qss",
    "reporting.qss", "disabled.qss", "background_images.qss",
)
MATERIAL_TEMPLATES = MappingProxyType({key: profile.stylesheet_fragments for key, profile in MATERIAL_PROFILES.items()})


@lru_cache(maxsize=len(MATERIAL_TEMPLATES))
def _read_qss_template(material: str) -> str:
    if material not in MATERIAL_TEMPLATES:
        raise ValueError("Unsupported stylesheet material")
    return "\n".join((_QSS_ROOT / name).read_text(encoding="utf-8")
                     for name in (*COMMON_TEMPLATES, *MATERIAL_TEMPLATES[material]))


@lru_cache(maxsize=32)
def application_stylesheet(palette: ColorPalette) -> str:
    tokens = {name: color for name, color in asdict(palette).items() if isinstance(color, str)}
    tokens["icons_root"] = (Path(__file__).resolve().parents[2] / "assets" / "icons" / "ui").as_posix()
    tokens.update(_surface_tokens(palette))
    return _render_qss(_read_qss_template(palette.material), tokens)


def _surface_tokens(colors: ColorPalette) -> dict[str, str]:
    glass = material_profile(colors.material).translucent
    fill = _rgba(colors.input_background, 200) if glass else colors.surface
    border = _rgba(colors.border_strong, 115) if glass else colors.border
    hover = _rgba(colors.button_hover, 225) if glass else colors.button_hover
    return {
        "page_fill": "transparent" if glass else colors.surface,
        "card_fill": "transparent" if glass else colors.card,
        "card_hover_fill": "transparent" if glass else colors.card_hover,
        "panel_border": border,
        "sidebar_fill": "transparent" if glass else colors.sidebar_background,
        "navigation_fill": "transparent" if glass else colors.surface,
        "navigation_hover_fill": hover if glass else colors.surface_alt,
        "button_fill": fill,
        "button_border": border if glass else colors.border_strong,
        "button_hover_fill": hover,
        "input_fill": fill if glass else colors.input_background,
        "field_border": border if glass else colors.input_border,
        "readonly_fill": fill if glass else colors.surface_alt,
        "row_fill": fill,
        "row_border": border,
        "row_hover_fill": hover if glass else colors.card_hover,
        "record_selected_fill": colors.accent_dim if glass else colors.card_hover,
        "table_fill": colors.input_background if glass else colors.surface,
        "table_border": border,
    }


def _rgba(color: str, alpha: int) -> str:
    red, green, blue = (int(color[index:index + 2], 16) for index in (1, 3, 5))
    return f"rgba({red}, {green}, {blue}, {alpha})"


def _render_qss(template: str, replacements: dict[str, str]) -> str:
    def replace(match):
        name = match.group(1)
        if name not in replacements:
            raise ValueError(f"Unknown stylesheet token: {name}")
        return replacements[name]
    return _QSS_TOKEN_RE.sub(replace, template)
