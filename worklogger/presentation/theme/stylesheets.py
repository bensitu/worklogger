"""Cached stylesheet loading and strict token substitution."""

from dataclasses import fields
from functools import lru_cache
from pathlib import Path
import re
from types import MappingProxyType

from worklogger.presentation.theme.models import ColorPalette
from worklogger.presentation.theme.materials import MATERIAL_PROFILES
from worklogger.presentation.theme.component_tokens import component_tokens

_QSS_ROOT = Path(__file__).with_name("qss")
_QSS_TOKEN_RE = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
COMMON_TEMPLATES = (
    "surfaces.qss", "typography.qss", "buttons.qss", "navigation.qss",
    "inputs.qss", "selection_controls.qss", "item_views.qss", "scrollbars.qss", "popups.qss", "tabs.qss",
    "tool_buttons.qss", "calendar.qss", "recording.qss", "authentication.qss", "date_controls.qss",
    "reports.qss", "analytics.qss", "interaction_states.qss", "disabled.qss", "background_images.qss",
)
MATERIAL_TEMPLATES = MappingProxyType({key: profile.stylesheet_fragments for key, profile in MATERIAL_PROFILES.items()})


def _read_qss_template(material: str) -> str:
    if material not in MATERIAL_TEMPLATES:
        raise ValueError("Unsupported stylesheet material")
    return _read_qss_fragments((*COMMON_TEMPLATES, *MATERIAL_TEMPLATES[material]))


@lru_cache(maxsize=32)
def _read_qss_fragments(names: tuple[str, ...]) -> str:
    return "\n".join((_QSS_ROOT / name).read_text(encoding="utf-8") for name in names)


@lru_cache(maxsize=32)
def application_stylesheet(palette: ColorPalette) -> str:
    tokens = {field.name: value for field in fields(palette)
              if isinstance(value := getattr(palette, field.name), str)}
    tokens["icons_root"] = (Path(__file__).resolve().parents[2] / "assets" / "icons" / "ui").as_posix()
    tokens.update(component_tokens(palette))
    return _render_qss(_read_qss_template(palette.material), tokens)


def _render_qss(template: str, replacements: dict[str, str]) -> str:
    def replace(match):
        name = match.group(1)
        if name not in replacements:
            raise ValueError(f"Unknown stylesheet token: {name}")
        return replacements[name]
    return _QSS_TOKEN_RE.sub(replace, template)
