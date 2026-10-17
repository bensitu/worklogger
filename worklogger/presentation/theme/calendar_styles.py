"""Calendar state styling independent of theme identifiers."""

from worklogger.domain.worklog.models import CustomEntryType, EntryType
from worklogger.presentation.theme.models import CalendarCellStyle, ColorPalette
from worklogger.presentation.theme.materials import material_profile

STYLE_PRIORITY = ("weekend", "holiday", "today", "selected")

_ENTRY_TYPE_MARKERS: dict[bool, dict[str, str | None]] = {
    False: {
        EntryType.NORMAL.value: None,
        EntryType.REMOTE.value: "#168a9b",
        EntryType.BUSINESS_TRIP.value: "#e07800",
        EntryType.PAID_LEAVE.value: "#2a9a2a",
        EntryType.COMP_LEAVE.value: "#8844cc",
        EntryType.SICK_LEAVE.value: "#cc3333",
        EntryType.MEETING.value: "#2563b8",
        EntryType.TRAINING.value: "#b38b00",
        EntryType.BREAK.value: None,
        EntryType.OTHER.value: "#737b87",
    },
    True: {
        EntryType.NORMAL.value: None,
        EntryType.REMOTE.value: "#59c9d7",
        EntryType.BUSINESS_TRIP.value: "#ffaa44",
        EntryType.PAID_LEAVE.value: "#66cc66",
        EntryType.COMP_LEAVE.value: "#bb88ff",
        EntryType.SICK_LEAVE.value: "#ff6666",
        EntryType.MEETING.value: "#80b3ff",
        EntryType.TRAINING.value: "#e8c65b",
        EntryType.BREAK.value: None,
        EntryType.OTHER.value: "#aeb6c2",
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


def entry_type_marker_color(entry_type: EntryType | CustomEntryType | str, *, dark: bool = False) -> str | None:
    if isinstance(entry_type, CustomEntryType):
        value = EntryType.PAID_LEAVE.value if entry_type.category == "leave" else EntryType.NORMAL.value
    else:
        value = entry_type.value if isinstance(entry_type, EntryType) else str(entry_type)
    return _ENTRY_TYPE_MARKERS[bool(dark)].get(value)
