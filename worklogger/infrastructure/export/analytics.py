"""Analytics export adapters."""

from __future__ import annotations

import csv
from pathlib import Path
from worklogger.infrastructure.files import atomic_destination, spreadsheet_text
from worklogger.infrastructure.i18n import _

from worklogger.domain.analytics.models import ChartDataBundle
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result


class AnalyticsCsvExporter:
    def export_bundle(self, destination: Path, bundle: ChartDataBundle) -> Result[Path]:
        try:
            path = Path(destination)
            if path.suffix.lower() != ".csv":
                path = path.with_name(path.name + ".csv")
            with atomic_destination(path) as temporary, temporary.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["label", "bar_value", "line_value", "leave_hours", "leave_marker"])
                for index, (label, bar_value) in enumerate(bundle.bar_data):
                    line_value = bundle.line_data[index][1] if index < len(bundle.line_data) else ""
                    leave_hours = (
                        bundle.leave_hours_data[index][1]
                        if index < len(bundle.leave_hours_data)
                        else ""
                    )
                    writer.writerow(
                        [
                            spreadsheet_text(label),
                            f"{float(bar_value):.2f}",
                            f"{float(line_value):.2f}" if line_value != "" else "",
                            f"{float(leave_hours):.2f}" if leave_hours != "" else "",
                            "1" if index in bundle.leave_indices else "0",
                        ]
                    )
        except (OSError, TypeError, ValueError) as exc:
            return Result.failure(
                InfrastructureError(
                    "analytics_csv_export_failed",
                    "analytics_csv_export_failed",
                    {"reason": str(exc)},
                )
            )
        return Result.success(path)


class AnalyticsPdfExporter:
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
                    {"reason": str(exc)},
                )
            )
        return Result.success(path)


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

