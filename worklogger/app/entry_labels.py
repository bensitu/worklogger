"""Classification formatting with an explicitly supplied translator."""

from collections.abc import Callable

from worklogger.domain.worklog.models import EntryType, CustomEntryType, WorkMode, EntryCategory


def N_(message: str) -> str:
    """Mark a message without binding it to the process language."""
    return message


_ENTRY_TYPE_LABELS = {
    "normal": N_("Normal"), "remote": N_("Remote"), "business_trip": N_("Business trip"),
    "meeting": N_("Meeting"), "training": N_("Training"), "break": N_("Break"),
    "other": N_("Other"), "paid_leave": N_("Paid leave"), "comp_leave": N_("Compensatory leave"),
    "sick_leave": N_("Sick leave"), "leave": N_("Leave"),
}
_WORK_MODE_LABELS = {
    None: N_("Not specified"), "onsite": N_("On-site"), "remote": N_("Remote"),
    "business_trip": N_("Business trip"), "other": N_("Other"),
}


def entry_type_label(entry_type: str | EntryType | CustomEntryType, translate: Callable[[str], str]) -> str:
    if isinstance(entry_type, CustomEntryType):
        return entry_type.label
    key = entry_type.value if isinstance(entry_type, EntryType) else entry_type
    message = _ENTRY_TYPE_LABELS.get(key)
    return translate(message) if message else ""


def work_mode_label(work_mode: WorkMode | str | None, translate: Callable[[str], str]) -> str:
    message = _WORK_MODE_LABELS.get(work_mode)
    return translate(message) if message else ""


def classification_label(entry_type: EntryType | CustomEntryType, work_mode: WorkMode | None,
                         translate: Callable[[str], str]) -> str:
    _ = translate
    if isinstance(entry_type, EntryType) and entry_type.is_legacy:
        label = _("Legacy classification") + " · " + entry_type_label(entry_type, _)
        if work_mode is not None and work_mode.value != entry_type.value:
            label += " · " + work_mode_label(work_mode, _)
        return label
    label = entry_type_label(entry_type, _)
    if entry_type.category == EntryCategory.LEAVE:
        return _("Leave") + " · " + label
    if entry_type.category == EntryCategory.WORK and work_mode is not None:
        return label + " · " + work_mode_label(work_mode, _)
    return label
