"""Localized activity labels shared by desktop views and exported documents."""

from worklogger.domain.worklog.models import WorkType, CustomWorkType
from worklogger.infrastructure.i18n import _


def work_type_label(work_type: str | WorkType | CustomWorkType) -> str:
    if isinstance(work_type, CustomWorkType):
        return work_type.label
    key = work_type.value if isinstance(work_type, WorkType) else work_type
    return {
        "normal": _("Normal"), "remote": _("Remote"), "business_trip": _("Business trip"),
        "meeting": _("Meeting"), "training": _("Training"), "break": _("Break"),
        "other": _("Other"), "paid_leave": _("Paid leave"), "comp_leave": _("Comp leave"),
        "sick_leave": _("Sick leave"), "leave": _("Leave"),
    }.get(key, "")
