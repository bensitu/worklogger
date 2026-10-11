"""Reusable surface, calendar, and rendering profiles for theme materials."""

from dataclasses import dataclass, fields, replace
import re
from types import MappingProxyType

from worklogger.config.theme_colors import AccentColors, SurfaceColors, validate_color

_COLOR_ROLES = frozenset(field.name for model in (SurfaceColors, AccentColors) for field in fields(model))
_CALENDAR_STATES = frozenset(("default", "today", "weekend", "holiday"))


def _validate_color_reference(value: str) -> None:
    if value not in _COLOR_ROLES:
        validate_color(value)


@dataclass(frozen=True)
class CalendarColors:
    background: str
    foreground: str
    border: str
    border_width: int = 1
    alpha: int = 255

    def __post_init__(self):
        for value in (self.background, self.foreground, self.border):
            _validate_color_reference(value)
        if type(self.border_width) is not int or self.border_width < 0:
            raise ValueError("Calendar border width must be a nonnegative integer")
        if type(self.alpha) is not int or not 0 <= self.alpha <= 255:
            raise ValueError("Calendar opacity must be between 0 and 255")


@dataclass(frozen=True)
class MaterialProfile:
    light: SurfaceColors
    dark: SurfaceColors
    calendar_light: tuple[tuple[str, CalendarColors], ...]
    calendar_dark: tuple[tuple[str, CalendarColors], ...]
    translucent: bool = False
    refraction: bool = False
    stylesheet_fragments: tuple[str, ...] = ()
    backdrop_light: tuple[str, ...] = ()
    backdrop_dark: tuple[str, ...] = ()
    holiday_foreground: str = "#ef4444"

    def __post_init__(self):
        for entries in (self.calendar_light, self.calendar_dark):
            keys = tuple(key for key, _ in entries)
            if len(keys) != len(_CALENDAR_STATES) or frozenset(keys) != _CALENDAR_STATES:
                raise ValueError("A material must define every calendar state exactly once")
            if any(not isinstance(colors, CalendarColors) for _, colors in entries):
                raise ValueError("Calendar states must use validated colors")
        for stops in (self.backdrop_light, self.backdrop_dark):
            if stops and len(stops) < 2:
                raise ValueError("A backdrop gradient requires at least two colors")
            for color in stops:
                validate_color(color)
        if self.refraction and not (self.translucent and self.backdrop_light and self.backdrop_dark):
            raise ValueError("Refraction requires translucent surfaces and backdrops for both modes")
        if any(not re.fullmatch(r"[a-z_]+\.qss", name) for name in self.stylesheet_fragments):
            raise ValueError("Stylesheet fragments must be local QSS filenames")
        _validate_color_reference(self.holiday_foreground)

    def surfaces(self, dark: bool) -> SurfaceColors:
        return self.dark if dark else self.light

    def calendar(self, key: str, dark: bool) -> CalendarColors:
        for state, colors in (self.calendar_dark if dark else self.calendar_light):
            if state == key:
                return colors
        raise KeyError(key)

    def backdrop(self, dark: bool) -> tuple[str, ...]:
        return self.backdrop_dark if dark else self.backdrop_light


_LIGHT = SurfaceColors(
    background="#f5f7fb", surface="#ffffff", surface_alt="#f8fafc", table_alternate="#ffffff",
    button_hover="#e8ecf8", disabled_text="#9aa3bb", disabled_background="#edf0f5",
    highlighted_text="#ffffff", login_hero_background="#111827", card="#ffffff", card_hover="#f3f7ff",
    border="#dce3ef", border_strong="#c7d0df", text="#1e2035", muted_text="#606888",
    input_background="#ffffff", input_border="#d0d5e8", sidebar_background="#ffffff",
    sidebar_active_background="#eaf2ff", danger="#ef4444", success="#16a34a", warning="#f59e0b",
)
_DARK = SurfaceColors(
    background="#111827", surface="#182033", surface_alt="#202a42", table_alternate="#202a42",
    button_hover="#2c2e50", disabled_text="#6f7699", disabled_background="#111827",
    highlighted_text="#ffffff", login_hero_background="#111827", card="#1b2438", card_hover="#22304b",
    border="#303b56", border_strong="#4b5a78", text="#c8cde8", muted_text="#8890b8",
    input_background="#181928", input_border="#33365a", sidebar_background="#141d2d",
    sidebar_active_background="#172f58", danger="#ff6b6b", success="#45c97a", warning="#ffb84d",
)

_SOLID = MaterialProfile(_LIGHT, _DARK,
    calendar_light=(
        ("default", CalendarColors("#ffffff", "#1e2035", "#dde1ee")),
        ("today", CalendarColors("#fffce0", "#8a6800", "#e0c800", 2)),
        ("weekend", CalendarColors("#eef3ff", "#1e5cc4", "#b8cfff")),
        ("holiday", CalendarColors("#fff0f0", "#cc2222", "#ffaaaa")),
    ),
    calendar_dark=(
        ("default", CalendarColors("#1e2030", "#c0c8e0", "#2d2f4a")),
        ("today", CalendarColors("#2e2a00", "#ffd855", "#aa9500", 2)),
        ("weekend", CalendarColors("#0c1d3c", "#5aafff", "#1a3a6a")),
        ("holiday", CalendarColors("#3c0d0d", "#ff7777", "#802020")),
    ),
)

_GLASS_LIGHT = replace(_LIGHT,
    background="#e5edf1", surface="#f3f7fa", surface_alt="#eaf1f5", card="#f3f7fa", card_hover="#eaf1f5",
    border="#bdced9", border_strong="#a5bac7", text="#182b35", muted_text="#506976",
    input_border="#aabdc9", sidebar_background="#f3f7fa", button_hover="#eaf1f5",
    disabled_text="#7e939f", disabled_background="#e4edf2", danger="#a9243a", success="#166c44", warning="#875900",
)
_GLASS_DARK = replace(_DARK,
    background="#20252a", surface="#252c32", surface_alt="#30383f", card="#252c32", card_hover="#30383f",
    border="#53636c", border_strong="#71838d", text="#e8eef3", muted_text="#b2bdc6",
    input_background="#222a30", input_border="#697b85", sidebar_background="#252c32",
    table_alternate="#30383f", button_hover="#30383f", disabled_text="#8e9ba5", disabled_background="#30383f",
    highlighted_text="#10242a", danger="#ff9baf", success="#87e5ba", warning="#f4d989",
)
_GLASS = MaterialProfile(_GLASS_LIGHT, _GLASS_DARK,
    calendar_light=(
        ("default", CalendarColors("surface", "text", "border", alpha=180)),
        ("today", CalendarColors("#f5f1d5", "text", "border", 2, 180)),
        ("weekend", CalendarColors("accent_dim", "accent", "border", alpha=180)),
        ("holiday", CalendarColors("#f6dce0", "danger", "border", alpha=180)),
    ),
    calendar_dark=(
        ("default", CalendarColors("surface", "text", "border", alpha=180)),
        ("today", CalendarColors("#444230", "text", "border", 2, 180)),
        ("weekend", CalendarColors("accent_dim", "accent", "border", alpha=180)),
        ("holiday", CalendarColors("#5b292e", "danger", "border", alpha=180)),
    ),
    translucent=True, refraction=True, stylesheet_fragments=("materials.qss",),
    backdrop_light=("#d0e0eb", "#eff2f5", "#d3e7df"),
    backdrop_dark=("#26333b", "#343c43", "#24413f"), holiday_foreground="danger",
)

MATERIAL_PROFILES = MappingProxyType({"solid": _SOLID, "glass": _GLASS})


def material_profile(key: str) -> MaterialProfile:
    try:
        return MATERIAL_PROFILES[key]
    except KeyError as error:
        raise ValueError("Unsupported theme material") from error
