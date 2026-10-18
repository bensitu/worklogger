"""Restrained semantic palettes shared by classification indicators and charts."""

from hashlib import sha256

from worklogger.domain.worklog.models import EntryCategory

_CUSTOM_COLORS = {
    False: {
        "work": ("#74818e", "#258a9e", "#7865b6", "#2f80bc", "#514b96", "#719fc4",
                 "#4e626f", "#9793bf", "#4e67b2", "#8bb4be", "#616d8b", "#5b5486"),
        "leave": ("#c4843a", "#b29c2c", "#c45e58", "#d39a66", "#b46635", "#a84f3d",
                  "#927e2a", "#d28d82", "#a86f5e", "#cda52f", "#da7772", "#c5a17e"),
        "break": ("#379563", "#2e8c82", "#7c9c3d", "#60af94", "#a1b96c", "#4d7e38",
                  "#83b9a0", "#386c5c", "#4d8e42", "#93b27a", "#337e71", "#a1bd56"),
    },
    True: {
        "work": ("#a1adb9", "#51b4c8", "#a99bdc", "#66a9db", "#8882c6", "#97c2df",
                 "#7e969e", "#c1b9df", "#849bdf", "#a5d0d9", "#a4b1c8", "#8f82bc"),
        "leave": ("#dba459", "#d1b744", "#df8279", "#e0b381", "#cd9056", "#c56e5d",
                  "#b6a04d", "#e6a89c", "#be8f7e", "#e0be67", "#e89b94", "#cdb49a"),
        "break": ("#70ba8e", "#5eb6a8", "#a6c360", "#8ed1b6", "#bed68a", "#7baf62",
                  "#b0d9c2", "#6e9f8e", "#74b86a", "#b3ca9e", "#58a391", "#bfd879"),
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
