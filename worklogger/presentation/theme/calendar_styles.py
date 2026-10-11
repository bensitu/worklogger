"""Calendar state styling independent of theme identifiers."""

from PySide6.QtGui import QColor

from worklogger.domain.worklog.models import CustomWorkType, WorkType
from worklogger.presentation.theme.models import CalendarCellStyle, ColorPalette

STYLE_PRIORITY = ("weekend", "holiday", "today", "selected")

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


def calendar_cell_style(flags: set[str], palette: ColorPalette) -> CalendarCellStyle:
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
        background, foreground, border, width = _CELL_COLORS[palette.dark][key]
        if palette.material == "glass":
            background = QColor(palette.surface)
            if key == "holiday":
                background = QColor("#5b292e" if palette.dark else "#f6dce0")
            elif key == "weekend":
                background = QColor(palette.accent_dim)
            elif key == "today":
                background = QColor("#444230" if palette.dark else "#f5f1d5")
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
        holiday_foreground=palette.danger if palette.material == "glass" else "#ef4444",
        highlighted_foreground=palette.highlighted_text,
    )


def work_type_marker_color(work_type: WorkType | CustomWorkType | str, *, dark: bool = False) -> str | None:
    if isinstance(work_type, CustomWorkType):
        value = WorkType.PAID_LEAVE.value if work_type.category == "leave" else WorkType.NORMAL.value
    else:
        value = work_type.value if isinstance(work_type, WorkType) else str(work_type)
    return _WORK_TYPE_MARKERS[bool(dark)].get(value)
