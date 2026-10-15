"""Report export selection and snapshot-based background requests."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from PySide6.QtWidgets import QFileDialog

from worklogger.infrastructure.i18n import _
from worklogger.presentation.date_labels import period_range_label, report_period_label
from worklogger.presentation.viewmodels.reports import ReportEditorState


@dataclass(frozen=True)
class ReportExportSnapshot:
    report_type: str
    selected_day: date
    state: ReportEditorState | None
    content: str


class ReportExportController:
    def __init__(self, parent, view_model, *, run_request, is_busy, show_status, show_error):
        self._parent = parent
        self._view_model = view_model
        self._run_request = run_request
        self._is_busy = is_busy
        self._show_status = show_status
        self._show_error = show_error

    def export_markdown(self, destination: Path, snapshot: ReportExportSnapshot) -> bool:
        if self._view_model is None or self._is_busy():
            return False
        state, content = snapshot.state, snapshot.content
        period = (report_period_label(state.report_type, state.period_start, state.period_end) if state else
                  period_range_label(snapshot.selected_day, snapshot.selected_day))
        exporter = getattr(self._view_model, "export_with_sources", None)
        return self._submit("export_report", lambda: exporter(destination, state, content) if exporter and state
                            else self._view_model.export_markdown(destination, content),
                            _("Current report exported for {period}.").format(period=period))

    def choose_scope(self, scope: str, snapshot: ReportExportSnapshot) -> bool:
        if self._view_model is None or self._is_busy():
            return False
        if scope.startswith("timesheet_"):
            return self._choose_timesheet(scope, snapshot.selected_day)
        if scope not in {"current", "day", "month"}:
            return False
        state, day = snapshot.state, snapshot.selected_day
        suffix = state.period_start.isoformat() if state else day.isoformat()
        identity = str(state.report_id) if state and state.report_id is not None else "draft"
        filename = f"{snapshot.report_type}-report-{suffix}-{identity}.md"
        if scope != "current":
            filename = "daily-reports-" + (day.strftime("%Y-%m") if scope == "month" else day.isoformat()) + ".md"
        path, _selected = QFileDialog.getSaveFileName(self._parent, _("Export Markdown"), filename,
                                                   _("Markdown files (*.md)"))
        if not path:
            return False
        if scope == "current":
            return self.export_markdown(Path(path), snapshot)
        return self._submit("export_saved_reports", lambda: self._view_model.export_saved_daily(
            Path(path), day, whole_month=scope == "month"), _("Saved daily reports exported."),
            error_code="report_export_failed")

    def _choose_timesheet(self, scope: str, day: date) -> bool:
        options = {"timesheet_day_xlsx": (False, "xlsx"), "timesheet_month_xlsx": (True, "xlsx"),
                   "timesheet_day_pdf": (False, "pdf"), "timesheet_month_pdf": (True, "pdf")}
        if scope not in options or not bool(getattr(self._view_model, "timesheet_available", False)):
            return False
        whole_month, file_format = options[scope]
        suffix = day.strftime("%Y-%m") if whole_month else day.isoformat()
        path, _selected = QFileDialog.getSaveFileName(self._parent, _("Export timesheet"),
            f"timesheet-{suffix}.{file_format}", _("Excel files (*.xlsx)") if file_format == "xlsx" else _("PDF files (*.pdf)"))
        if not path:
            return False
        return self._submit("export_timesheet", lambda: self._view_model.export_timesheet(
            Path(path), day, whole_month=whole_month, format=file_format), _("Timesheet exported."),
            error_code="timesheet_export_failed")

    def _submit(self, name, operation, success_message, *, error_code="report_request_failed") -> bool:
        def complete(result):
            if result.ok:
                self._show_status(success_message)
            else:
                self._show_error(result.error)
        return self._run_request(name, operation, complete, error_code=error_code)
