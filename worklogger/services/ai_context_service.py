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
        include_notes: bool = False,
        include_calendar: bool = True,
        include_calendar_titles: bool = False,
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
        include_notes: bool = False,
        include_calendar: bool = True,
        include_calendar_titles: bool = False,
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
        include_notes: bool = False,
        include_calendar: bool = True,
        include_calendar_titles: bool = False,
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

    def build_analytics_context(
        self,
        *,
        year: int,
        month: int,
        metric: str,
        chart_mode: str,
        include_leave: bool,
        monthly_bundle=None,
        quarterly_bundle=None,
        annual_bundle=None,
        current_bundle=None,
        current_tab_index: int | None = None,
        work_hours: float | None = None,
        monthly_target: float | None = None,
        month_labels: list[str] | None = None,
    ) -> str:
        lines: list[str] = [
            "# WorkLogger Analytics Context",
            "",
            "## Selection",
            f"- Year: {year}",
            f"- Month: {month:02d}",
            f"- Metric: {metric}",
            f"- Chart mode: {chart_mode}",
            f"- Current tab index: {current_tab_index if current_tab_index is not None else 'unknown'}",
        ]
        if work_hours is not None:
            lines.append(f"- Standard work hours: {work_hours:.1f}")
        if monthly_target is not None:
            lines.append(f"- Monthly target hours: {monthly_target:.1f}")
        lines.append(f"- Leave markers included: {'yes' if include_leave else 'no'}")
        lines.append("")

        bundle_sections = (
            ("Monthly chart data", monthly_bundle),
            ("Quarterly chart data", quarterly_bundle),
            ("Annual chart data", annual_bundle),
        )
        for title, bundle in bundle_sections:
            if bundle is None:
                continue
            lines.extend(self._analytics_bundle_block(title, bundle, include_leave))

        if current_bundle is not None:
            lines.extend(self._analytics_bundle_block(
                "Current visible chart data",
                current_bundle,
                include_leave,
            ))
        if month_labels:
            lines.extend(["## Month labels", ", ".join(map(str, month_labels)), ""])
        lines.extend([
            "## Rules",
            "- Summarize only the provided analytics data.",
            "- Do not invent missing periods, hours, or explanations.",
            "- Mention uncertainty when the data is sparse.",
        ])
        return "\n".join(lines).strip() + "\n"

    def estimate_tokens(self, context: str) -> int:
        return max(1, (len(context or "") + 2) // 3)

    def _build_context(
        self,
        start_day: str,
        end_day: str,
        *,
        include_notes: bool,
        include_calendar: bool,
        include_calendar_titles: bool,
        include_quick_log_details: bool,
    ) -> str:
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
                include_titles=include_calendar_titles,
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

    def _analytics_bundle_block(self, title: str, bundle, include_leave: bool) -> list[str]:
        bar_data = list(getattr(bundle, "bar_data", []) or [])
        line_data = list(getattr(bundle, "line_data", []) or [])
        leave_hours = list(getattr(bundle, "leave_hours_data", []) or [])
        reference = getattr(bundle, "reference_line", None)
        labels = [str(item[0]) for item in bar_data if isinstance(item, tuple) and item]
        if not labels:
            labels = [str(item[0]) for item in line_data if isinstance(item, tuple) and item]
        rows = max(len(labels), len(bar_data), len(line_data), len(leave_hours))
        lines = [f"## {title}"]
        if reference is not None:
            try:
                lines.append(f"Reference line: {float(reference):.2f}")
            except Exception:
                lines.append(f"Reference line: {reference}")
        if rows == 0:
            return [*lines, "No chart data.", ""]
        header = "| Label | Bar value | Line value |"
        sep = "|---|---:|---:|"
        if include_leave:
            header = "| Label | Bar value | Line value | Leave hours |"
            sep = "|---|---:|---:|---:|"
        lines.extend([header, sep])
        for index in range(rows):
            label = labels[index] if index < len(labels) else str(index + 1)
            bar = self._series_value(bar_data, index)
            line = self._series_value(line_data, index)
            values = [
                self._cell(label),
                self._number_cell(bar),
                self._number_cell(line),
            ]
            if include_leave:
                leave = self._series_value(leave_hours, index)
                values.append(self._number_cell(leave))
            lines.append("| " + " | ".join(values) + " |")
        lines.append("")
        return lines

    @staticmethod
    def _plain(value) -> str:
        return str(value or "").replace("\r", " ").replace("\n", " ").strip()

    @classmethod
    def _cell(cls, value) -> str:
        return cls._plain(value).replace("|", "\\|")

    @classmethod
    def _number_cell(cls, value) -> str:
        if value == "":
            return ""
        if isinstance(value, tuple) and len(value) >= 2:
            value = value[1]
        try:
            return f"{float(value):.2f}"
        except Exception:
            return cls._cell(value)

    @staticmethod
    def _series_value(series: list, index: int):
        if index >= len(series):
            return ""
        item = series[index]
        if isinstance(item, tuple) and len(item) >= 2:
            return item[1]
        return item

    @staticmethod
    def _record_date(record) -> str:
        return str(getattr(record, "date", getattr(record, "d", "")) or "")
