"""Restrained semantic palettes shared by classification indicators and charts."""

from hashlib import sha256

from worklogger.domain.worklog.models import EntryCategory

_CUSTOM_COLORS = {
    False: {
        "work": ("#75818b", "#527e91", "#6576a4", "#4c78a0", "#6b7790", "#687f8c", "#7e8893", "#597d88"),
        "leave": ("#ba8656", "#b8934d", "#b87473", "#b18c69", "#ac7760", "#af846e", "#b59b60", "#b37e79"),
        "break": ("#719680", "#608b78", "#7a967d", "#689184", "#839a7e", "#6e8f75", "#799987", "#64877a"),
    },
    True: {
        "work": ("#a1adb6", "#82adbe", "#9ba8cf", "#89afd0", "#a2adbf", "#92acb9", "#acb5c0", "#8fadb7"),
        "leave": ("#d9ad80", "#d3b67b", "#d49a98", "#ccad90", "#ce9d86", "#cda892", "#d0bc8d", "#d0a19c"),
        "break": ("#9cbea9", "#8fb5a2", "#a3bda6", "#97baad", "#adbea7", "#9ab6a0", "#a0bfaf", "#94b3a5"),
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
