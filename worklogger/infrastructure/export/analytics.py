"""Analytics export adapters."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path
from worklogger.infrastructure.files import atomic_destination, spreadsheet_text
from worklogger.infrastructure.i18n import _

from worklogger.domain.analytics.models import AnalyticsDashboard, ChartDataBundle
from worklogger.domain.reporting.timesheets import Timesheet
from worklogger.infrastructure.entry_type_labels import work_mode_label
from worklogger.infrastructure.export.timesheets import timesheet_rows
from worklogger.domain.shared.errors import InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result


class AnalyticsCsvExporter:
    def export_dashboard(self, destination: Path, dashboard: AnalyticsDashboard, *, scope: str) -> Result[Path]:
        try:
            path = Path(destination)
            if path.suffix.lower() != ".csv":
                path = path.with_name(path.name + ".csv")
            sheet = _timesheet(dashboard)
            with atomic_destination(path) as temporary, temporary.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow((_("Record date"), _("Start"), _("End"), _("End date"), _("Classification"),
                    _("Accounting category"), _("Work arrangement"), _("Project"), _("Work item"), _("Content"),
                    _("Worked hours") + " (h)", _("Rest hours") + " (h)", _("Leave hours") + " (h)",
                    _("Record status"), _("Started at"), _("Ended at")))
                categories = {"work": _("Work"), "break": _("Break"), "leave": _("Leave")}
                for values, entry in timesheet_rows(sheet):
                    end_day = (entry.ended_at.date() if entry.ended_at is not None else
                               entry.day + timedelta(days=int(entry.is_overnight))) if entry and entry.has_times else None
                    row = (values[0], values[1], values[2], end_day.isoformat() if end_day else "", values[3],
                        categories[entry.entry_type.category] if entry else "", work_mode_label(entry.work_mode) if entry and not (entry.is_break or entry.is_leave) else "",
                        values[4], values[5], values[6], *(f"{number:.6f}" for number in values[7:10]), values[10],
                        entry.started_at.isoformat() if entry and entry.started_at else "",
                        entry.ended_at.isoformat() if entry and entry.ended_at else "")
                    writer.writerow(tuple(spreadsheet_text(value) for value in row))
        except Exception as exc:
            return _export_failure("analytics_csv_export_failed", exc)
        return Result.success(path)

    def export_bundle(self, destination: Path, bundle: ChartDataBundle, *, metric: str = "hours") -> Result[Path]:
        try:
            path = Path(destination)
            if path.suffix.lower() != ".csv":
                path = path.with_name(path.name + ".csv")
            with atomic_destination(path) as temporary, temporary.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow([_("Period"), (_("Average Work Hours") if metric == "average" else _("Work hours")) + " (h)",
                                 (_("Average leave hours") if metric == "average" else _("Leave hours")) + " (h)"])
                for index, (label, bar_value) in enumerate(bundle.bar_data):
                    leave_hours = (
                        bundle.leave_hours_data[index][1]
                        if index < len(bundle.leave_hours_data)
                        else ""
                    )
                    writer.writerow(
                        [
                            spreadsheet_text(label.replace("\n", " ")),
                            f"{float(bar_value):.2f}",
                            f"{float(leave_hours):.2f}" if leave_hours != "" else "",
                        ]
                    )
        except (OSError, TypeError, ValueError) as exc:
            return Result.failure(
                InfrastructureError(
                    "analytics_csv_export_failed",
                    "analytics_csv_export_failed",
                    {"reason": type(exc).__name__},
                )
            )
        return Result.success(path)


class AnalyticsPdfExporter:
    def export_dashboard(self, destination: Path, dashboard: AnalyticsDashboard, *, scope: str,
                         breakdown_dimension: str = "entry_type") -> Result[Path]:
        try:
            from worklogger.infrastructure.export.analytics_pdf import write_dashboard_pdf
            sheet = _timesheet(dashboard)
            path = Path(destination)
            if path.suffix.lower() != ".pdf":
                path = path.with_name(path.name + ".pdf")
            with atomic_destination(path) as temporary:
                write_dashboard_pdf(temporary, dashboard, scope=scope, breakdown_dimension=breakdown_dimension,
                                    generated_at=sheet.generated_at)
        except Exception as exc:
            return _export_failure("analytics_pdf_export_failed", exc)
        return Result.success(path)

    def export_bundle(
        self,
        destination: Path,
        bundle: ChartDataBundle,
        *,
        title: str = "Analytics",
    ) -> Result[Path]:
        try:
            path = Path(destination)
            if path.suffix.lower() != ".pdf":
                path = path.with_name(path.name + ".pdf")
            lines = [title, ""]
            for index, (label, value) in enumerate(bundle.bar_data):
                leave = (
                    bundle.leave_hours_data[index][1]
                    if index < len(bundle.leave_hours_data)
                    else 0.0
                )
                marker = f" ({_('Leave')})" if index in bundle.leave_indices else ""
                lines.append(f"{label}: {float(value):.2f}h, {_('Leave')} {float(leave):.2f}h{marker}")
            with atomic_destination(path) as temporary:
                _write_pdf(temporary, lines)
        except (OSError, TypeError, ValueError, RuntimeError) as exc:
            return Result.failure(
                InfrastructureError(
                    "analytics_pdf_export_failed",
                    "analytics_pdf_export_failed",
                    {"reason": type(exc).__name__},
                )
            )
        return Result.success(path)


def _export_failure(code, error):
    if isinstance(error, ValueError) and str(error) == "timesheet_too_large":
        return Result.failure(ValidationError("analytics_export_too_large", "analytics_export_too_large"))
    return Result.failure(InfrastructureError(code, code, {"reason": type(error).__name__}))


def _timesheet(dashboard):
    entries = tuple(entry for record in dashboard.records for entry in (record.entries or (record,)))
    return Timesheet(dashboard.period_start, dashboard.period_end, "", datetime.now().astimezone(),
                     dashboard.standard_work_hours, entries)


def _write_pdf(destination: Path, lines: list[str]) -> None:
    from PySide6.QtCore import QMarginsF
    from PySide6.QtGui import QFont, QGuiApplication, QPageSize, QPdfWriter, QTextDocument

    if QGuiApplication.instance() is None:
        raise RuntimeError("pdf_application_required")
    writer = QPdfWriter(str(destination))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(15, 15, 15, 15))
    writer.setTitle(lines[0])
    writer.setCreator("WorkLogger")
    writer.setResolution(96)
    document = QTextDocument()
    font = QFont(QGuiApplication.font())
    font.setPointSizeF(10)
    document.setDefaultFont(font)
    document.setPlainText("\n".join(lines))
    document.print_(writer)

