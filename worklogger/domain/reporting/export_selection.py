"""Owned daily snapshots selected for chronological report exports."""

from datetime import date, datetime, timezone


def saved_report_order(report):
    stamp = report.created_at or datetime.min.replace(tzinfo=timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp, getattr(report, "id", getattr(report, "report_id", 0)) or 0


def latest_daily_reports(reports, user_id: int, start: date, end: date):
    selected = {}
    for report in reports:
        if (report.user_id != user_id or report.report_type != "daily" or
                report.period_start != report.period_end or not start <= report.period_start <= end):
            continue
        previous = selected.get(report.period_start)
        if previous is None or saved_report_order(report) > saved_report_order(previous):
            selected[report.period_start] = report
    return tuple(selected[day] for day in sorted(selected))
