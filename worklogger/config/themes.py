"""Immutable theme definitions shared by settings and presentation."""

from dataclasses import dataclass
import re
from types import MappingProxyType

from worklogger.config.theme_colors import AccentColors as AccentColors, SurfaceOverrides as SurfaceOverrides


def N_(message: str) -> str:
    """Mark a label for gettext extraction without translating it at import time."""
    return message


@dataclass(frozen=True)
class ThemeDefinition:
    key: str
    label: str
    light: AccentColors | None = None
    dark: AccentColors | None = None
    material: str = "solid"
    light_overrides: SurfaceOverrides | None = None
    dark_overrides: SurfaceOverrides | None = None

    def __post_init__(self):
        if not re.fullmatch(r"[a-z][a-z0-9_]*", self.key) or not self.label.strip():
            raise ValueError("A theme requires a stable key and display label")
        if self.material not in ("solid", "glass"):
            raise ValueError("Unsupported theme material")
        if (self.light is None) != (self.dark is None):
            raise ValueError("A theme must define both light and dark accent colors")
        if any(value is not None and not isinstance(value, SurfaceOverrides)
               for value in (self.light_overrides, self.dark_overrides)):
            raise ValueError("Theme surface overrides must use validated colors")

    @property
    def customizable(self) -> bool:
        return self.light is None


_DEFINITIONS = (
    ThemeDefinition("blue", N_("Blue"),
        AccentColors("#4f8ef7", "#3070d8", "#e8f0fe", "#eef2ff", "#cdd5f0"),
        AccentColors("#5a9ff5", "#3d87e8", "#1a3058", "#1a1e3a", "#2d3360")),
    ThemeDefinition("pink", N_("Pink"),
        AccentColors("#e05888", "#c03868", "#fce8f0", "#fff0f7", "#f0c8dc"),
        AccentColors("#f07aaa", "#d85888", "#3a1028", "#2a1020", "#501838")),
    ThemeDefinition("green", N_("Green"),
        AccentColors("#2daa7a", "#1a8a58", "#e0f5ec", "#edfaf4", "#bce8d4"),
        AccentColors("#3dcc8a", "#2aaa68", "#0e3028", "#0a2820", "#1a5040")),
    ThemeDefinition("purple", N_("Purple"),
        AccentColors("#7c55d6", "#5c38b8", "#ede8ff", "#f2efff", "#cfc8f0"),
        AccentColors("#9a78f0", "#7c55d6", "#261852", "#1a1038", "#3a2868")),
    ThemeDefinition("liquid_glass", N_("Liquid Glass"),
        AccentColors("#146c76", "#0f5660", "#dceff0", "#edf4f5", "#bfd6da"),
        AccentColors("#82d1d8", "#9fe0e5", "#203a3e", "#242e33", "#4e6066"), "glass"),
    ThemeDefinition("custom", N_("Custom")),
)
THEME_DEFINITIONS = tuple(sorted(_DEFINITIONS, key=lambda definition: definition.customizable))
THEME_CATALOG = MappingProxyType({definition.key: definition for definition in THEME_DEFINITIONS})
if len(THEME_CATALOG) != len(THEME_DEFINITIONS):
    raise ValueError("Theme keys must be unique")
THEME_KEYS = tuple(THEME_CATALOG)


def get_theme(value: str | None) -> ThemeDefinition:
    key = str(value or "blue").strip().lower()
    return THEME_CATALOG.get(key, THEME_CATALOG["blue"])


def normalize_theme(value: str | None) -> str:
    return get_theme(value).key
