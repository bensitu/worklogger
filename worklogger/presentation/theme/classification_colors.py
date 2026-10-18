"""Restrained semantic palettes shared by classification indicators and charts."""

from hashlib import sha256

from worklogger.domain.worklog.models import EntryCategory

_CUSTOM_COLORS = {
    False: {
        "work": ("#75818b", "#328b9e", "#7166ae", "#3f7fb1", "#575a95", "#567da0", "#64717f", "#438e9c"),
        "leave": ("#c18a4b", "#b09b3e", "#be6963", "#bf8d65", "#b77952", "#b16c57", "#aa963e", "#b87b6d"),
        "break": ("#4d9b76", "#448b80", "#789d56", "#529b8b", "#8b9e5e", "#639753", "#65a489", "#4a8672"),
    },
    True: {
        "work": ("#a1adb6", "#66b6c9", "#aaa0d6", "#85b3d5", "#989bd0", "#81aec7", "#869eb6", "#75bcc8"),
        "leave": ("#d3a770", "#cdb25d", "#d58c85", "#d3a17a", "#d59b78", "#cc9282", "#c5b16b", "#d39a8b"),
        "break": ("#82b99d", "#72aea2", "#a0bb7b", "#80bba9", "#adbd84", "#90b57e", "#8bc4aa", "#7bad96"),
    },
}
_BUILTIN_COLORS = {
    "normal": ("work", 0), "onsite": ("work", 0), "unspecified": ("work", 0),
    "remote": ("work", 1), "business_trip": ("work", 2), "meeting": ("work", 3),
    "training": ("work", 4), "other": ("work", 6), "break": ("break", 0),
    "paid_leave": ("leave", 0), "comp_leave": ("leave", 1), "sick_leave": ("leave", 2),
}


def classification_color(definition, *, dark=False, category=None):
    value = getattr(definition, "value", definition)
    if value is None:
        return None
    if value in _BUILTIN_COLORS:
        group, index = _BUILTIN_COLORS[value]
        return _CUSTOM_COLORS[bool(dark)][group][index]
    if isinstance(value, str) and value.startswith("custom:"):
        group = EntryCategory(category or getattr(definition, "category", EntryCategory.WORK))
        palette = _CUSTOM_COLORS[bool(dark)][group]
        index = int.from_bytes(sha256(value.encode("utf-8")).digest()[:8], "big") % len(palette)
        return palette[index]
    return None
