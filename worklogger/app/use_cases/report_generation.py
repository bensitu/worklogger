"""Report generation with privacy filtering and source provenance."""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from functools import partial
from hashlib import sha256

from worklogger.app.commands.report_commands import GenerateReportCommand
from worklogger.app.entry_labels import classification_label
from worklogger.app.ports import TemplateProvider
from worklogger.app.use_cases.user_profile import profile_display_name
from worklogger.domain.auth.repositories import UserProfileRepository
from worklogger.domain.calendar.models import CalendarEvent
from worklogger.domain.calendar.repositories import CalendarEventRepository
from worklogger.domain.notes.preferences import NoteSharing, note_sharing_key
from worklogger.domain.notes.repositories import DailyNoteRepository
from worklogger.domain.quicklog.models import QuickLog
from worklogger.domain.quicklog.repositories import QuickLogRepository
from worklogger.domain.quicklog.rules import contains_quick_log_reference
from worklogger.domain.reporting.models import ReportProvenance, ReportSource
from worklogger.domain.reporting.periods import validate_report_period
from worklogger.domain.reporting.templates import render_template
from worklogger.domain.settings.repositories import SettingsRepository
from worklogger.domain.shared.dates import time_range_label
from worklogger.domain.shared.errors import InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkLog
from worklogger.domain.worklog.repositories import WorkLogRepository
from worklogger.domain.worklog.rules import aggregate_days


@dataclass(frozen=True)
class GeneratedReport:
    report_type: str
    period_start: date
    period_end: date
    content: str
    provenance: ReportProvenance = ReportProvenance()


class GenerateReportHandler:
    def __init__(
        self,
        *,
        work_logs: WorkLogRepository,
        quick_logs: QuickLogRepository,
        calendar_events: CalendarEventRepository,
        templates: TemplateProvider,
        notes: DailyNoteRepository | None = None,
        translator: Callable[..., str] | None = None,
        note_settings: SettingsRepository | None = None,
        profiles: UserProfileRepository | None = None,
    ) -> None:
        self._work_logs = work_logs
        self._quick_logs = quick_logs
        self._calendar_events = calendar_events
        self._templates = templates
        self._notes = notes
        self._note_settings = note_settings
        self._translator = translator or (lambda message, **kwargs: message)
        self._profiles = profiles

    def handle(self, command: GenerateReportCommand) -> Result[GeneratedReport]:
        try:
            period = validate_report_period(
                command.report_type,
                command.period_start,
                command.period_end,
            )
            standard_hours = float(command.standard_work_hours)
            if not math.isfinite(standard_hours) or not 1 <= standard_hours <= 24:
                raise ValueError("standard_work_hours_invalid")
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))

        try:
            display_name = profile_display_name(self._profiles, command.user_id)
            work_logs = self._work_logs.list_range(command.user_id, period.start, period.end)
            source_records = tuple(entry for record in work_logs for entry in (record.entries or (record,)))
            if len(source_records) > 50000:
                raise ValueError("record_range_too_large")
            notes = ()
            if self._notes is not None and self._note_settings is not None:
                notes = self._notes.list_range(command.user_id, period.start, period.end)
                notes = tuple(note for note in notes if NoteSharing.decode(
                    self._note_settings.get(command.user_id, note_sharing_key(note.day))).reports)
                recorded_notes = {(entry.day, entry.note) for record in work_logs for entry in (record.entries or (record,))}
                work_logs += tuple(WorkLog(command.user_id, note.day, note=note.content)
                                   for note in notes if note.content and (note.day, note.content) not in recorded_notes)
            quick_logs = self._quick_logs.list_for_range(command.user_id, period.start, period.end)
            notes_by_day = {}
            for note in notes:
                notes_by_day.setdefault(note.day, []).append(note.content)
            quick_logs = tuple(entry for entry in quick_logs if not any(
                contains_quick_log_reference(content, entry) for content in notes_by_day.get(entry.day, ())))
            events = self._calendar_events.list_for_range(command.user_id, period.start, period.end)
            template = self._templates.get_template(
                command.language, period.report_type, user_id=command.user_id,
            )
        except ValueError as exc:
            if str(exc) == "record_range_too_large":
                return Result.failure(ValidationError(str(exc), str(exc)))
            return Result.failure(InfrastructureError("report_load_failed", "report_load_failed"))
        except Exception:
            return Result.failure(InfrastructureError("report_load_failed", "report_load_failed"))
        translate = partial(self._translator, language=command.language)
        if not template.ok or not template.value:
            content = _fallback_report(period.report_type, period.start, period.end, translate)
        else:
            content = render_template(
                template.value,
                _template_values(
                    report_type=period.report_type,
                    start=period.start,
                    end=period.end,
                    work_logs=work_logs,
                    quick_logs=quick_logs,
                    events=events,
                    standard_hours=standard_hours,
                    translate=translate,
                    display_name=display_name,
                ),
            )
        return Result.success(
            GeneratedReport(
                report_type=period.report_type,
                period_start=period.start,
                period_end=period.end,
                content=content,
                provenance=ReportProvenance(
                    generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    language=command.language, standard_hours=standard_hours,
                    template_digest=_source_digest(template.value) if template.ok and template.value else "",
                    sources=tuple(_report_source("record", str(entry.id) if entry.id else entry.day.isoformat(), entry, entry.revision)
                                  for entry in source_records)
                    + tuple(_report_source("note", note.day.isoformat(), note) for note in notes)
                    + tuple(_report_source("calendar", str(event.id), event) for event in events)
                    + tuple(_report_source("quick_log", str(entry.id), entry) for entry in quick_logs),
                ),
            )
        )


def _source_digest(value):
    from dataclasses import is_dataclass
    payload = asdict(value) if is_dataclass(value) else value
    return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def _report_source(kind, identifier, value, revision=None):
    return ReportSource(kind, identifier, revision, _source_digest(value))


def _template_values(
    *,
    report_type: str,
    start: date,
    end: date,
    work_logs: tuple[WorkLog, ...],
    quick_logs: tuple[QuickLog, ...],
    events: tuple[CalendarEvent, ...],
    standard_hours: float,
    translate: Callable[[str], str],
    display_name: str = "",
) -> dict[str, object]:
    _ = translate
    entries = tuple(entry for record in work_logs for entry in (record.entries or (record,)))
    work_records = aggregate_days(tuple(entry for entry in entries if not entry.is_note_only))
    note_records = sorted((entry for entry in entries if entry.is_note_only), key=lambda entry: entry.day)
    total = sum(work_log.worked_hours() for work_log in work_logs if not work_log.is_leave)
    overtime = sum(
        max(work_log.worked_hours() - standard_hours, 0.0)
        for work_log in work_logs
        if not work_log.is_leave
    )
    return {
        "display_name": display_name,
        "date": start.isoformat(),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "date_range": f"{start.isoformat()} - {end.isoformat()}",
        "year": start.year,
        "month": f"{start.month:02d}" if report_type == "monthly" else start.month,
        "task_list": _work_log_lines(work_logs, standard_hours, translate),
        "work_records": _work_log_lines(work_records, standard_hours, translate) if work_records else "- " + _("No work records for this period."),
        "notes_section": _optional_section(_("Notes"), "\n".join(
            [_list_item(f"{row.day.isoformat()} - {row.note}") for row in note_records]
            + ([_quick_log_lines(quick_logs)] if quick_logs else []))),
        "calendar_section": _optional_section(_("Calendar events"), _event_lines(events, translate) if events else ""),
        "projects_section": _optional_section(_("Project summary"), _project_summary(work_logs, translate)),
        "calendar_events": _event_lines(events, translate),
        "quick_logs": _quick_log_lines(quick_logs),
        "total_hours": f"{total:.1f}",
        "overtime_hours": f"{overtime:.1f}",
        "projects_summary": _project_summary(work_logs, translate),
        "issues": "- ",
        "next_plan": "- ",
    }


def _optional_section(title: str, content: str) -> str:
    return f"## {title}\n{content}\n\n" if content.strip() else ""


def _project_summary(work_logs, _):
    totals = {}
    for record in work_logs:
        for entry in record.entries or (record,):
            hours = entry.worked_hours()
            if hours > 0:
                key = ("project", entry.context.project_id) if entry.context.project_id else ("label", entry.context.project_label)
                previous = totals.get(key, ("", 0))
                totals[key] = (entry.context.project_label, previous[1] + hours)
    return "\n".join(_list_item(f"{label or _('Unclassified')}: {hours:.1f}h")
                     for label, hours in sorted(totals.values()))


def _work_log_lines(work_logs: tuple[WorkLog, ...], standard_hours: float, _: Callable[[str], str]) -> str:
    if not work_logs:
        return "- " + _("No notes recorded for this period.")
    lines = []
    for record in sorted(work_logs, key=lambda item: item.day):
        if record.is_note_only and not record.entries:
            lines.append(_list_item(f"{record.day.isoformat()} - {record.note}"))
            continue
        hours = record.worked_hours()
        heading = f"{record.day.isoformat()}: {hours:.1f}h"
        overtime = max(hours - standard_hours, 0.0)
        if overtime:
            heading += "  " + _("Overtime") + f" +{overtime:.1f}h"
        lines.append(_list_item(heading))
        for entry in record.entries or (record,):
            span = time_range_label(entry.start_time, entry.end_time) if entry.has_times else _("All day")
            label = classification_label(entry.entry_type, entry.work_mode, _)
            description = f"{span} [{label}]"
            if entry.context.label:
                description += " [" + entry.context.label + "]"
            if entry.is_overnight:
                description += " " + _("Overnight")
            if entry.note:
                description += " - " + entry.note
            lines.append("  " + _list_item(description))
    return "\n".join(lines)


def _quick_log_lines(quick_logs: tuple[QuickLog, ...]) -> str:
    if not quick_logs:
        return "- "
    lines: list[str] = []
    for quick_log in sorted(quick_logs, key=lambda item: (item.day, item.start_time, item.id or 0)):
        time_text = time_range_label(quick_log.start_time, quick_log.end_time)
        prefix = f"{quick_log.day.isoformat()} {time_text}".strip()
        lines.append(_list_item(f"{prefix}: {quick_log.description}"))
    return "\n".join(lines)


def _event_lines(events: tuple[CalendarEvent, ...], _: Callable[[str], str]) -> str:
    if not events:
        return "- "
    lines: list[str] = []
    for event in sorted(events, key=lambda item: (item.day, item.start_time or "", item.summary)):
        time_text = _("All day") if event.all_day else time_range_label(event.start_time, event.end_time)
        prefix = f"{event.day.isoformat()} {time_text}".strip()
        lines.append(_list_item(f"{prefix}: {event.summary}"))
    return "\n".join(lines)


def _list_item(content: str) -> str:
    return "- " + content.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\n  ")


def _fallback_report(report_type: str, start: date, end: date, _: Callable[[str], str]) -> str:
    if report_type == "daily":
        title = _("Daily Report")
    elif report_type == "weekly":
        title = _("Weekly Report")
    else:
        title = _("Monthly Report")
    return f"# {title}  {start.isoformat()} - {end.isoformat()}\n\n- "
