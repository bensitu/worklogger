"""WorkLogger context builder for AI prompts."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta

from core.time_calc import calc_hours


class AiContextService:
    """Build compact, user-scoped Markdown context through AppServices."""

    def __init__(self, services):
        self._services = services

    def build_daily_context(
        self,
        selected_date: date,
        *,
        include_notes: bool = True,
        include_calendar: bool = True,
        include_calendar_titles: bool | None = None,
        include_quick_log_details: bool = True,
    ) -> str:
        day = selected_date.isoformat()
        return self._build_context(
            day,
            day,
            include_notes=include_notes,
            include_calendar=include_calendar,
            include_calendar_titles=include_calendar_titles,
            include_quick_log_details=include_quick_log_details,
        )

    def build_weekly_context(
        self,
        selected_date: date,
        *,
        include_notes: bool = True,
        include_calendar: bool = True,
        include_calendar_titles: bool | None = None,
        include_quick_log_details: bool = True,
    ) -> str:
        start = selected_date - timedelta(days=selected_date.weekday())
        end = start + timedelta(days=6)
        return self._build_context(
            start.isoformat(),
            end.isoformat(),
            include_notes=include_notes,
            include_calendar=include_calendar,
            include_calendar_titles=include_calendar_titles,
            include_quick_log_details=include_quick_log_details,
        )

    def build_monthly_context(
        self,
        year: int,
        month: int,
        *,
        include_notes: bool = True,
        include_calendar: bool = True,
        include_calendar_titles: bool | None = None,
        include_quick_log_details: bool = True,
    ) -> str:
        _first_weekday, last_day = monthrange(year, month)
        return self._build_context(
            f"{year}-{month:02d}-01",
            f"{year}-{month:02d}-{last_day:02d}",
            include_notes=include_notes,
            include_calendar=include_calendar,
            include_calendar_titles=include_calendar_titles,
            include_quick_log_details=include_quick_log_details,
        )

    def _build_context(
        self,
        start_day: str,
        end_day: str,
        *,
        include_notes: bool,
        include_calendar: bool,
        include_calendar_titles: bool | None,
        include_quick_log_details: bool,
    ) -> str:
        calendar_titles = include_calendar if include_calendar_titles is None else include_calendar_titles
        lines: list[str] = [
            "# WorkLogger Context",
            "",
            "## Period",
            f"{start_day} to {end_day}",
            "",
        ]
        records = self._records_for_period(start_day, end_day)
        lines.extend(self._work_records_block(records, include_notes=include_notes))
        lines.extend(self._quick_logs_block(
            self._services.quick_logs_for_range(start_day, end_day),
            include_details=include_quick_log_details,
        ))
        if include_calendar:
            lines.extend(self._calendar_block(
                self._services.get_calendar_events_for_range(start_day, end_day),
                include_titles=calendar_titles,
            ))
        else:
            lines.extend(["## Calendar Events", "Calendar details excluded.", ""])
        lines.extend([
            "## Rules",
            "- Do not invent tasks.",
            "- If data is missing, say it is missing.",
            "- Respect the selected language.",
            "- Respect the selected privacy options.",
        ])
        return "\n".join(lines).strip() + "\n"

    def _records_for_period(self, start_day: str, end_day: str) -> list:
        year_months = self._year_months(start_day, end_day)
        records = []
        for ym in year_months:
            records.extend(self._services.month_records(ym))
        return [
            record for record in records
            if start_day <= self._record_date(record) <= end_day
        ]

    @staticmethod
    def _year_months(start_day: str, end_day: str) -> list[str]:
        start = date.fromisoformat(start_day)
        end = date.fromisoformat(end_day)
        result: list[str] = []
        year, month = start.year, start.month
        while (year, month) <= (end.year, end.month):
            result.append(f"{year}-{month:02d}")
            month += 1
            if month > 12:
                month = 1
                year += 1
        return result

    def _work_records_block(self, records: list, *, include_notes: bool) -> list[str]:
        lines = ["## Work Records"]
        if not records:
            return [*lines, "No work records found.", ""]
        note_header = " | Note" if include_notes else ""
        lines.append(f"| Date | Type | Start | End | Break | Hours{note_header} |")
        lines.append(f"|---|---|---|---|---|---{'|---' if include_notes else ''}|")
        for record in records:
            start = self._cell(getattr(record, "start", "") or "")
            end = self._cell(getattr(record, "end", "") or "")
            break_hours = getattr(record, "break_hours", getattr(record, "break", 0.0))
            work_type = self._cell(record.safe_work_type() if hasattr(record, "safe_work_type") else getattr(record, "work_type", ""))
            hours = 0.0
            if hasattr(record, "has_times") and record.has_times:
                hours = calc_hours(getattr(record, "start", ""), getattr(record, "end", ""), break_hours)
            values = [
                self._cell(self._record_date(record)),
                work_type,
                start,
                end,
                self._cell(str(break_hours or 0)),
                self._cell(f"{hours:.1f}"),
            ]
            if include_notes:
                note = record.safe_note() if hasattr(record, "safe_note") else getattr(record, "note", "")
                values.append(self._cell(note))
            lines.append("| " + " | ".join(values) + " |")
        lines.append("")
        return lines

    def _quick_logs_block(self, logs: list[dict], *, include_details: bool) -> list[str]:
        lines = ["## Quick Logs"]
        if not logs:
            return [*lines, "No quick logs found.", ""]
        if not include_details:
            return [*lines, f"{len(logs)} quick log entries excluded by privacy settings.", ""]
        for item in logs:
            end = f"-{item.get('end_time')}" if item.get("end_time") else ""
            lines.append(
                f"- {item.get('date', '')} {item.get('time', '')}{end}: "
                f"{self._plain(item.get('description', ''))}"
            )
        lines.append("")
        return lines

    def _calendar_block(self, events: list[dict], *, include_titles: bool) -> list[str]:
        lines = ["## Calendar Events"]
        if not events:
            return [*lines, "No calendar events found.", ""]
        for event in events:
            start = event.get("start_time") or ""
            end = event.get("end_time") or ""
            span = f"{start}-{end}".strip("-") or "all day"
            summary = self._plain(event.get("summary", "")) if include_titles else "Title hidden"
            lines.append(f"- {event.get('date', '')} {span}: {summary}")
        lines.append("")
        return lines

    @staticmethod
    def _plain(value) -> str:
        return str(value or "").replace("\r", " ").replace("\n", " ").strip()

    @classmethod
    def _cell(cls, value) -> str:
        return cls._plain(value).replace("|", "\\|")

    @staticmethod
    def _record_date(record) -> str:
        return str(getattr(record, "date", getattr(record, "d", "")) or "")
