"""Calendar state styling independent of theme identifiers."""

from worklogger.presentation.theme.models import CalendarCellStyle, ColorPalette
from worklogger.presentation.theme.materials import material_profile

STYLE_PRIORITY = ("weekend", "holiday", "today", "selected")

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
