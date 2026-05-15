"""Theme data and stylesheet generation for presentation components."""

from __future__ import annotations

from dataclasses import dataclass
import re

from worklogger.domain.worklog.models import WorkType

DEFAULT_CUSTOM_COLOR = "#4f8ef7"
THEME_KEYS = ("blue", "pink", "green", "purple", "custom")
STYLE_PRIORITY = ("weekend", "today", "holiday", "selected")
_HEX_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")

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
    border: str
    text: str
    muted_text: str
    input_background: str
    input_border: str


@dataclass(frozen=True)
class CalendarCellStyle:
    key: str
    background: str
    foreground: str
    border: str
    border_width: int
    hover_border: str


class ThemeEngine:
    def palette(
        self,
        theme: str = "blue",
        *,
        dark: bool = False,
        custom_color: str | None = None,
    ) -> ColorPalette:
        theme_key = _normalize_theme(theme)
        colors = _theme_colors(theme_key, dark, custom_color)
        accent, hover, accent_dim, stat_background, stat_border = colors
        if dark:
            background, surface, border = "#13141d", "#1c1d2b", "#2d2f48"
            text, muted = "#c8cde8", "#8890b8"
            input_background, input_border = "#181928", "#33365a"
        else:
            background, surface, border = "#f0f2f7", "#ffffff", "#dde1ee"
            text, muted = "#1e2035", "#606888"
            input_background, input_border = "#ffffff", "#d0d5e8"
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
            border=border,
            text=text,
            muted_text=muted,
            input_background=input_background,
            input_border=input_border,
        )

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
                "#ffffff",
                palette.accent,
                "2",
            )
        else:
            background, foreground, border, width = _CELL_COLORS[bool(dark)][key]
        return CalendarCellStyle(
            key=key,
            background=background,
            foreground=foreground,
            border=border,
            border_width=int(width),
            hover_border=palette.hover,
        )

    def work_type_marker_color(
        self,
        work_type: WorkType | str,
        *,
        dark: bool = False,
    ) -> str | None:
        value = work_type.value if isinstance(work_type, WorkType) else str(work_type)
        return _WORK_TYPE_MARKERS[bool(dark)].get(value)

    def application_stylesheet(
        self,
        theme: str = "blue",
        *,
        dark: bool = False,
        custom_color: str | None = None,
    ) -> str:
        palette = self.palette(theme, dark=dark, custom_color=custom_color)
        button_background = "#232438" if dark else "#f4f5fa"
        button_hover = "#2c2e50" if dark else "#e8ecf8"
        disabled_text = "#6f7699" if dark else "#9aa3bb"
        return (
            "QWidget{"
            f"background-color:{palette.background};"
            f"color:{palette.text};"
            "font-size:13px;"
            "font-family:-apple-system,\"Segoe UI\",\"Noto Sans\",sans-serif;"
            "}"
            "QFrame#stat_card_frame{"
            f"background-color:{palette.stat_background};"
            f"border:1px solid {palette.stat_border};"
            "border-radius:12px;"
            "}"
            "QPushButton{"
            f"background:{button_background};"
            f"border:1px solid {palette.border};"
            f"color:{palette.text};"
            "border-radius:8px;padding:7px 14px;"
            "}"
            f"QPushButton:hover{{background:{button_hover};border-color:{palette.accent};}}"
            f"QPushButton:disabled{{color:{disabled_text};}}"
            "QPushButton[variant=\"primary\"]{"
            f"background:{palette.accent};color:#ffffff;border:none;font-weight:600;"
            "}"
            f"QPushButton[variant=\"primary\"]:hover{{background:{palette.hover};}}"
            "QLineEdit,QTextEdit,QPlainTextEdit{"
            f"background:{palette.input_background};"
            f"border:1px solid {palette.input_border};"
            f"color:{palette.text};"
            "border-radius:8px;padding:4px 8px;"
            "}"
        )


def normalize_hex_color(accent_hex: str | None) -> str:
    raw = str(accent_hex or "").strip()
    if not _HEX_RE.match(raw):
        return DEFAULT_CUSTOM_COLOR
    if not raw.startswith("#"):
        raw = f"#{raw}"
    return raw.lower()


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
