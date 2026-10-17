"""Localized activity labels shared by desktop views and exported documents."""

from worklogger.domain.worklog.models import EntryType, CustomEntryType
from worklogger.infrastructure.i18n import _


def entry_type_label(entry_type: str | EntryType | CustomEntryType) -> str:
    if isinstance(entry_type, CustomEntryType):
        return entry_type.label
    key = entry_type.value if isinstance(entry_type, EntryType) else entry_type
    return {
        "normal": _("Normal"), "remote": _("Remote"), "business_trip": _("Business trip"),
        "meeting": _("Meeting"), "training": _("Training"), "break": _("Break"),
        "other": _("Other"), "paid_leave": _("Paid leave"), "comp_leave": _("Comp leave"),
        "sick_leave": _("Sick leave"), "leave": _("Leave"),
    }.get(key, "")
