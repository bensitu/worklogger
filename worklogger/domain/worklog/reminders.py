"""Personal timer reminders without inferring or changing recorded time."""

from datetime import datetime
from worklogger.domain.worklog.models import CustomWorkType, WorkType
from worklogger.domain.worklog.rules import timestamp_span_hours
from worklogger.config.constants import MAX_SHIFT_HOURS


def timer_reminders(started_at: datetime, now: datetime, work_type, *, long_hours=10.0, continuous_hours=0.0):
    elapsed = max(0, timestamp_span_hours(started_at, now))
    reasons = []
    if elapsed > MAX_SHIFT_HOURS:
        reasons.append("duration_limit")
    elif long_hours > 0 and elapsed >= long_hours:
        reasons.append("long_timer")
    is_work = work_type.category == "work" if isinstance(work_type, CustomWorkType) else work_type not in {
        WorkType.BREAK, WorkType.PAID_LEAVE, WorkType.COMP_LEAVE, WorkType.SICK_LEAVE}
    if is_work and continuous_hours > 0 and elapsed >= continuous_hours:
        reasons.append("continuous_timer")
    return tuple(reasons)
