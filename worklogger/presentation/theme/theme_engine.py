"""Theme data and stylesheet generation for presentation components."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from functools import lru_cache
import re

from PySide6.QtGui import QColor, QPalette

from worklogger.domain.worklog.models import CustomWorkType, WorkType

from worklogger.domain.settings.appearance import DEFAULT_CUSTOM_COLOR, THEME_KEYS, normalize_hex_color
STYLE_PRIORITY = ("weekend", "holiday", "today", "selected")
_QSS_ROOT = Path(__file__).with_name("qss")
_QSS_TOKEN_RE = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")

_THEMES: dict[str, dict[bool, tuple[str, str, str, str, str]]] = {
    "blue": {
        False: ("#4f8ef7", "#3070d8", "#e8f0fe", "#eef2ff", "#cdd5f0"),
        True: ("#5a9ff5", "#3d87e8", "#1a3058", "#1a1e3a", "#2d3360"),
    },
    "pink": {
        False: ("#e05888", "#c03868", "#fce8f0", "#fff0f7", "#f0c8dc"),
        True: ("#f07aaa", "#d85888", "#3a1028", "#2a1020", "#501838"),
    },
    "green": {
        False: ("#2daa7a", "#1a8a58", "#e0f5ec", "#edfaf4", "#bce8d4"),
        True: ("#3dcc8a", "#2aaa68", "#0e3028", "#0a2820", "#1a5040"),
    },
    "purple": {
        False: ("#7c55d6", "#5c38b8", "#ede8ff", "#f2efff", "#cfc8f0"),
        True: ("#9a78f0", "#7c55d6", "#261852", "#1a1038", "#3a2868"),
    },
    "liquid_glass": {
        False: ("#146c76", "#0f5660", "#dceff0", "#edf4f5", "#bfd6da"),
        True: ("#82d1d8", "#9fe0e5", "#203a3e", "#242e33", "#4e6066"),
    },
}

_CELL_COLORS: dict[bool, dict[str, tuple[str, str, str, str]]] = {
    False: {
        "default": ("#ffffff", "#1e2035", "#dde1ee", "1"),
        "today": ("#fffce0", "#8a6800", "#e0c800", "2"),
        "weekend": ("#eef3ff", "#1e5cc4", "#b8cfff", "1"),
        "holiday": ("#fff0f0", "#cc2222", "#ffaaaa", "1"),
    },
    True: {
        "default": ("#1e2030", "#c0c8e0", "#2d2f4a", "1"),
        "today": ("#2e2a00", "#ffd855", "#aa9500", "2"),
        "weekend": ("#0c1d3c", "#5aafff", "#1a3a6a", "1"),
        "holiday": ("#3c0d0d", "#ff7777", "#802020", "1"),
    },
}

_WORK_TYPE_MARKERS: dict[bool, dict[str, str | None]] = {
    False: {
        WorkType.NORMAL.value: None,
        WorkType.REMOTE.value: None,
        WorkType.BUSINESS_TRIP.value: "#e07800",
        WorkType.PAID_LEAVE.value: "#2a9a2a",
        WorkType.COMP_LEAVE.value: "#8844cc",
        WorkType.SICK_LEAVE.value: "#cc3333",
    },
    True: {
        WorkType.NORMAL.value: None,
        WorkType.REMOTE.value: None,
        WorkType.BUSINESS_TRIP.value: "#ffaa44",
        WorkType.PAID_LEAVE.value: "#66cc66",
        WorkType.COMP_LEAVE.value: "#bb88ff",
        WorkType.SICK_LEAVE.value: "#ff6666",
    },
}


@dataclass(frozen=True)
class ColorPalette:
    theme: str
    dark: bool
    accent: str
    hover: str
    accent_dim: str
    stat_background: str
    stat_border: str
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


class ThemeEngine:
    def palette(
        self,
        theme: str = "blue",
        *,
        dark: bool = False,
        custom_color: str | None = None,
    ) -> ColorPalette:
        theme_key = _normalize_theme(theme)
        accent = normalize_hex_color(custom_color or DEFAULT_CUSTOM_COLOR) if theme_key == "custom" else None
        return _color_palette(theme_key, bool(dark), accent)

    def calendar_cell_style(
        self,
        flags: set[str],
        *,
        theme: str = "blue",
        dark: bool = False,
        custom_color: str | None = None,
    ) -> CalendarCellStyle:
        palette = self.palette(theme, dark=dark, custom_color=custom_color)
        key = "default"
        for candidate in STYLE_PRIORITY:
            if candidate in flags:
                key = candidate
        if key == "selected":
            background, foreground, border, width = (
                palette.accent,
                palette.highlighted_text,
                palette.accent,
                "2",
            )
        else:
            background, foreground, border, width = _CELL_COLORS[bool(dark)][key]
            if palette.theme == "liquid_glass":
                background = QColor(palette.surface)
                if key == "holiday":
                    background = QColor("#5b292e" if dark else "#f6dce0")
                elif key == "weekend":
                    background = QColor(palette.accent_dim)
                elif key == "today":
                    background = QColor("#444230" if dark else "#f5f1d5")
                background.setAlpha(180)
                background = background.name(QColor.NameFormat.HexArgb)
                foreground = palette.accent if key == "weekend" else palette.danger if key == "holiday" else palette.text
                border = palette.border
        return CalendarCellStyle(
            key=key,
            background=background,
            foreground=foreground,
            border=border,
            border_width=int(width),
            hover_border=palette.hover,
            holiday_foreground=palette.danger if palette.theme == "liquid_glass" else "#ef4444",
            highlighted_foreground=palette.highlighted_text,
        )

    def work_type_marker_color(
        self,
        work_type: WorkType | CustomWorkType | str,
        *,
        dark: bool = False,
    ) -> str | None:
        if isinstance(work_type, CustomWorkType):
            value = WorkType.PAID_LEAVE.value if work_type.category == "leave" else WorkType.NORMAL.value
        else:
            value = work_type.value if isinstance(work_type, WorkType) else str(work_type)
        return _WORK_TYPE_MARKERS[bool(dark)].get(value)

    def application_stylesheet(
        self,
        theme: str = "blue",
        *,
        dark: bool = False,
        custom_color: str | None = None,
    ) -> str:
        return _application_stylesheet(self.palette(theme, dark=dark, custom_color=custom_color))

    def qt_palette(
        self,
        theme: str = "blue",
        *,
        dark: bool = False,
        custom_color: str | None = None,
    ) -> QPalette:
        palette = self.palette(theme, dark=dark, custom_color=custom_color)
        qt_palette = QPalette()

        _set_palette_color(qt_palette, QPalette.ColorRole.Window, palette.background)
        _set_palette_color(qt_palette, QPalette.ColorRole.WindowText, palette.text)
        _set_palette_color(qt_palette, QPalette.ColorRole.Base, palette.input_background)
        _set_palette_color(qt_palette, QPalette.ColorRole.AlternateBase, palette.table_alternate)
        _set_palette_color(qt_palette, QPalette.ColorRole.Text, palette.text)
        _set_palette_color(qt_palette, QPalette.ColorRole.Button, palette.surface)
        _set_palette_color(qt_palette, QPalette.ColorRole.ButtonText, palette.text)
        _set_palette_color(qt_palette, QPalette.ColorRole.Highlight, palette.accent)
        _set_palette_color(qt_palette, QPalette.ColorRole.HighlightedText, palette.highlighted_text)
        _set_palette_color(qt_palette, QPalette.ColorRole.Link, palette.accent)
        qt_palette.setColor(
            QPalette.ColorGroup.Disabled,
            QPalette.ColorRole.WindowText,
            QColor(palette.disabled_text),
        )
        qt_palette.setColor(
            QPalette.ColorGroup.Disabled,
            QPalette.ColorRole.Text,
            QColor(palette.disabled_text),
        )
        qt_palette.setColor(
            QPalette.ColorGroup.Disabled,
            QPalette.ColorRole.ButtonText,
            QColor(palette.disabled_text),
        )
        return qt_palette


@lru_cache(maxsize=32)
def _color_palette(theme_key: str, dark: bool, custom_color: str | None) -> ColorPalette:
    colors = _theme_colors(theme_key, dark, custom_color)
    accent, hover, accent_dim, stat_background, stat_border = colors
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
    if theme_key == "liquid_glass":
        background, surface, surface_alt = (("#20252a", "#252c32", "#30383f") if dark else
                                          ("#e5edf1", "#f3f7fa", "#eaf1f5"))
        card, card_hover = surface, surface_alt
        border, border_strong = (("#53636c", "#71838d") if dark else ("#bdced9", "#a5bac7"))
        text, muted = (("#e8eef3", "#b2bdc6") if dark else ("#182b35", "#506976"))
        input_background, input_border = (("#222a30", "#697b85") if dark else ("#ffffff", "#aabdc9"))
        sidebar_background, sidebar_active = surface, accent_dim
        table_alternate, button_hover = surface_alt, surface_alt
        disabled_text, disabled_background = (("#8e9ba5", "#30383f") if dark else ("#7e939f", "#e4edf2"))
        danger, success, warning = (("#ff9baf", "#87e5ba", "#f4d989") if dark else
                                    ("#a9243a", "#166c44", "#875900"))
    return ColorPalette(
        theme=theme_key,
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
        highlighted_text="#10242a" if theme_key == "liquid_glass" and dark else "#ffffff",
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


def _normalize_theme(theme: str) -> str:
    value = str(theme or "blue").strip().lower()
    return value if value in THEME_KEYS else "blue"


def _theme_colors(
    theme: str,
    dark: bool,
    custom_color: str | None,
) -> tuple[str, str, str, str, str]:
    if theme == "custom":
        return _custom_palette(custom_color or DEFAULT_CUSTOM_COLOR)[bool(dark)]
    return _THEMES.get(theme, _THEMES["blue"])[bool(dark)]


@lru_cache(maxsize=1)
def _read_qss_template() -> str:
    return "\n".join((_QSS_ROOT / name).read_text(encoding="utf-8")
                     for name in ("application.qss", "background_images.qss"))


@lru_cache(maxsize=32)
def _application_stylesheet(palette: ColorPalette) -> str:
    tokens = {name: color for name, color in asdict(palette).items() if isinstance(color, str)}
    tokens["icons_root"] = (Path(__file__).resolve().parents[2] / "assets" / "icons" / "ui").as_posix()
    template = _read_qss_template()
    if palette.theme == "liquid_glass":
        for name, color, alpha in (("glass_fill", palette.input_background, 200),
                                   ("glass_border", palette.border_strong, 115),
                                   ("glass_hover", palette.button_hover, 225)):
            red, green, blue, _alpha = QColor(color).getRgb()
            tokens[name] = f"rgba({red}, {green}, {blue}, {alpha})"
        template += "\n" + (_QSS_ROOT / "liquid_glass.qss").read_text(encoding="utf-8")
    return _render_qss(template, tokens)


def contrasting_text_color(background: QColor) -> QColor:
    def linear(channel):
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
    luminance = sum(weight * linear(channel) for weight, channel in zip(
        (0.2126, 0.7152, 0.0722), (background.redF(), background.greenF(), background.blueF())))
    return QColor("#000000" if luminance > 0.179 else "#ffffff")


def _render_qss(template: str, replacements: dict[str, str]) -> str:
    return _QSS_TOKEN_RE.sub(lambda match: replacements[match.group(1)], template)


def _set_palette_color(qt_palette: QPalette, role: QPalette.ColorRole, color: str) -> None:
    qt_palette.setColor(role, QColor(color))


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
