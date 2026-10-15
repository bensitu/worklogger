"""Calendar state styling independent of theme identifiers."""

from worklogger.domain.worklog.models import CustomWorkType, WorkType
from worklogger.presentation.theme.models import CalendarCellStyle, ColorPalette
from worklogger.presentation.theme.materials import material_profile

STYLE_PRIORITY = ("weekend", "holiday", "today", "selected")

_WORK_TYPE_MARKERS: dict[bool, dict[str, str | None]] = {
    False: {
        WorkType.NORMAL.value: None,
        WorkType.REMOTE.value: "#168a9b",
        WorkType.BUSINESS_TRIP.value: "#e07800",
        WorkType.PAID_LEAVE.value: "#2a9a2a",
        WorkType.COMP_LEAVE.value: "#8844cc",
        WorkType.SICK_LEAVE.value: "#cc3333",
        WorkType.MEETING.value: "#2563b8",
        WorkType.TRAINING.value: "#b38b00",
        WorkType.BREAK.value: None,
        WorkType.OTHER.value: "#737b87",
    },
    True: {
        WorkType.NORMAL.value: None,
        WorkType.REMOTE.value: "#59c9d7",
        WorkType.BUSINESS_TRIP.value: "#ffaa44",
        WorkType.PAID_LEAVE.value: "#66cc66",
        WorkType.COMP_LEAVE.value: "#bb88ff",
        WorkType.SICK_LEAVE.value: "#ff6666",
        WorkType.MEETING.value: "#80b3ff",
        WorkType.TRAINING.value: "#e8c65b",
        WorkType.BREAK.value: None,
        WorkType.OTHER.value: "#aeb6c2",
    },
}


def calendar_cell_style(flags: set[str], palette: ColorPalette) -> CalendarCellStyle:
    profile = material_profile(palette.material)
    key = "default"
    for candidate in STYLE_PRIORITY:
        if candidate in flags:
            key = candidate
    if key == "selected":
        background, foreground, border, width = (
            palette.accent,
            palette.highlighted_text,
            palette.accent,
            2,
        )
    else:
        state = profile.calendar(key, palette.dark)
        background, foreground, border = (_color(value, palette) for value in
                                         (state.background, state.foreground, state.border))
        width = state.border_width
        if state.alpha != 255:
            background = f"#{state.alpha:02x}" + background.lstrip("#").lower()
    return CalendarCellStyle(
        key=key,
        background=background,
        foreground=foreground,
        border=border,
        border_width=int(width),
        hover_border=palette.hover,
        holiday_foreground=_color(profile.holiday_foreground, palette),
        highlighted_foreground=palette.highlighted_text,
    )


def _color(value: str, palette: ColorPalette) -> str:
    return value if value.startswith("#") else getattr(palette, value)


def work_type_marker_color(work_type: WorkType | CustomWorkType | str, *, dark: bool = False) -> str | None:
    if isinstance(work_type, CustomWorkType):
        value = WorkType.PAID_LEAVE.value if work_type.category == "leave" else WorkType.NORMAL.value
    else:
        value = work_type.value if isinstance(work_type, WorkType) else str(work_type)
    return _WORK_TYPE_MARKERS[bool(dark)].get(value)
