"""Cached stylesheet loading and strict token substitution."""

from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
import re

from PySide6.QtGui import QColor

from worklogger.presentation.theme.models import ColorPalette

_QSS_ROOT = Path(__file__).with_name("qss")
_QSS_TOKEN_RE = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


@lru_cache(maxsize=1)
def _read_qss_template() -> str:
    return "\n".join((_QSS_ROOT / name).read_text(encoding="utf-8")
                     for name in ("application.qss", "background_images.qss"))


@lru_cache(maxsize=32)
def application_stylesheet(palette: ColorPalette) -> str:
    tokens = {name: color for name, color in asdict(palette).items() if isinstance(color, str)}
    tokens["icons_root"] = (Path(__file__).resolve().parents[2] / "assets" / "icons" / "ui").as_posix()
    template = _read_qss_template()
    if palette.material == "glass":
        for name, color, alpha in (("glass_fill", palette.input_background, 200),
                                   ("glass_border", palette.border_strong, 115),
                                   ("glass_hover", palette.button_hover, 225)):
            red, green, blue, _alpha = QColor(color).getRgb()
            tokens[name] = f"rgba({red}, {green}, {blue}, {alpha})"
        template += "\n" + (_QSS_ROOT / "liquid_glass.qss").read_text(encoding="utf-8")
    return _render_qss(template, tokens)


def _render_qss(template: str, replacements: dict[str, str]) -> str:
    return _QSS_TOKEN_RE.sub(lambda match: replacements[match.group(1)], template)
