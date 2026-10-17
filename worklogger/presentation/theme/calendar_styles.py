"""Calendar state styling independent of theme identifiers."""

from hashlib import sha256

from worklogger.domain.worklog.models import CustomEntryType, EntryType
from worklogger.presentation.theme.models import CalendarCellStyle, ColorPalette
from worklogger.presentation.theme.materials import material_profile

STYLE_PRIORITY = ("weekend", "holiday", "today", "selected")

_ENTRY_TYPE_COLORS: dict[bool, dict[str, str]] = {
    False: {
        EntryType.NORMAL.value: "#7c7c7c",
        EntryType.REMOTE.value: "#168a9b",
        EntryType.BUSINESS_TRIP.value: "#e07800",
        EntryType.PAID_LEAVE.value: "#2a9a2a",
        EntryType.COMP_LEAVE.value: "#8844cc",
        EntryType.SICK_LEAVE.value: "#cc3333",
        EntryType.MEETING.value: "#2563b8",
        EntryType.TRAINING.value: "#b38b00",
        EntryType.BREAK.value: "#a3a3a3",
        EntryType.OTHER.value: "#737b87",
    },
    True: {
        EntryType.NORMAL.value: "#b3b3b3",
        EntryType.REMOTE.value: "#59c9d7",
        EntryType.BUSINESS_TRIP.value: "#ffaa44",
        EntryType.PAID_LEAVE.value: "#66cc66",
        EntryType.COMP_LEAVE.value: "#bb88ff",
        EntryType.SICK_LEAVE.value: "#ff6666",
        EntryType.MEETING.value: "#80b3ff",
        EntryType.TRAINING.value: "#e8c65b",
        EntryType.BREAK.value: "#808080",
        EntryType.OTHER.value: "#aeb6c2",
    },
}

_CUSTOM_ENTRY_TYPE_COLORS = {
    False: ("#3f7f8c", "#7c6995", "#897431", "#4d8660",
            "#a06375", "#556fa0", "#94705a", "#658147"),
    True: ("#82bbc6", "#b09bc9", "#c9b36a", "#8ebd9d",
           "#d09cac", "#96add3", "#c7a18b", "#a6be81"),
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


def entry_type_color(entry_type: EntryType | CustomEntryType | str, *, dark: bool = False) -> str | None:
    value = entry_type.value if isinstance(entry_type, (EntryType, CustomEntryType)) else str(entry_type)
    if value.startswith("custom:"):
        palette = _CUSTOM_ENTRY_TYPE_COLORS[bool(dark)]
        index = int.from_bytes(sha256(value.encode("utf-8")).digest()[:8], "big") % len(palette)
        return palette[index]
    return _ENTRY_TYPE_COLORS[bool(dark)].get(value)
