"""Analytics export adapters."""

from __future__ import annotations

import csv
from pathlib import Path

from worklogger.domain.analytics.models import ChartDataBundle
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result


class AnalyticsCsvExporter:
    def export_bundle(self, destination: Path, bundle: ChartDataBundle) -> Result[Path]:
        try:
            path = Path(destination)
            if path.suffix.lower() != ".csv":
                path = path.with_suffix(".csv")
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
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
                            label,
                            f"{float(bar_value):.2f}",
                            f"{float(line_value):.2f}" if line_value != "" else "",
                            f"{float(leave_hours):.2f}" if leave_hours != "" else "",
                            "1" if index in bundle.leave_indices else "0",
                        ]
                    )
        except OSError as exc:
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
                path = path.with_suffix(".pdf")
            path.parent.mkdir(parents=True, exist_ok=True)
            lines = [title, ""]
            for index, (label, value) in enumerate(bundle.bar_data):
                leave = (
                    bundle.leave_hours_data[index][1]
                    if index < len(bundle.leave_hours_data)
                    else 0.0
                )
                marker = " leave" if index in bundle.leave_indices else ""
                lines.append(f"{label}: {float(value):.2f}h, leave {float(leave):.2f}h{marker}")
            path.write_bytes(_simple_pdf(lines))
        except OSError as exc:
            return Result.failure(
                InfrastructureError(
                    "analytics_pdf_export_failed",
                    "analytics_pdf_export_failed",
                    {"reason": str(exc)},
                )
            )
        return Result.success(path)


def _simple_pdf(lines: list[str]) -> bytes:
    content_lines = ["BT", "/F1 10 Tf", "50 780 Td"]
    for index, line in enumerate(lines[:45]):
        if index:
            content_lines.append("0 -16 Td")
        content_lines.append(f"({_pdf_text(line)}) Tj")
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode("latin-1", errors="replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode("ascii"))
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(output)


def _pdf_text(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

