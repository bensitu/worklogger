"""Localized activity labels shared by desktop views and exported documents."""

from worklogger.domain.worklog.models import EntryType, CustomEntryType, WorkMode, EntryCategory
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


def work_mode_label(work_mode: WorkMode | str | None) -> str:
    return {
        None: _("Not specified"), "onsite": _("On-site"), "remote": _("Remote"),
        "business_trip": _("Business trip"), "other": _("Other"),
    }.get(work_mode, "")


def classification_label(entry_type: EntryType | CustomEntryType, work_mode: WorkMode | None = None) -> str:
    if isinstance(entry_type, EntryType) and entry_type.is_legacy:
        label = _("Legacy classification") + " · " + entry_type_label(entry_type)
        if work_mode is not None and work_mode.value != entry_type.value:
            label += " · " + work_mode_label(work_mode)
        return label
    label = entry_type_label(entry_type)
    if entry_type.category == EntryCategory.LEAVE:
        return _("Leave") + " · " + label
    if entry_type.category == EntryCategory.WORK and work_mode is not None:
        return label + " · " + work_mode_label(work_mode)
    return label
