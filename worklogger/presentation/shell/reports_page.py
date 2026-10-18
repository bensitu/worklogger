"""Period report editing and saved history."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import date
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from worklogger.app.job_runner import JobRunner
from worklogger.domain.reporting.periods import shift_report_period
from worklogger.domain.shared.errors import (
    AppError,
    CancellationError,
    InfrastructureError,
    ValidationError,
)
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import _
from worklogger.presentation.date_labels import report_period_label
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.job_runner import QtJobRunner, owned_callback
from worklogger.presentation.reporting.dialog import (
    ReportTemplateDialog,
    confirm_report_overwrite,
)
from worklogger.presentation.reporting.exports import ReportExportController, ReportExportSnapshot
from worklogger.presentation.reporting.history import ReportHistoryController
from worklogger.presentation.viewmodels import (
    ReportEditorState,
    ReportEditorViewModel,
)
from worklogger.presentation.widgets import (
    ReportHistoryDisplayItem,
    ReportHistoryPanel,
    SegmentedControl,
)
from worklogger.presentation.widgets.report_editor import ReportEditorPanel
from worklogger.presentation.processing import TextProcessingTask


class ReportsPage(QWidget):
    def __init__(
        self,
        view_model: ReportEditorViewModel | None,
        selected_day: date,
        parent: QWidget | None = None,
        *,
        confirm_discard: Callable[[], bool] | None = None,
        job_runner: JobRunner | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("reports_page_widget")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._view_model = view_model
        self._ai_ready = bool(view_model is not None and getattr(view_model, "rewrite_available", True))
        self._selected_day = selected_day
        self._states: dict[str, ReportEditorState] = {}
        self._saved_content: dict[str, str] = {}
        self._last_error: AppError | None = None
        self._rendered_type = "daily"
        self._confirm_discard = confirm_discard
        self._job_runner = job_runner or QtJobRunner(self)
        self._rewrite_task = TextProcessingTask(self, job_runner=self._job_runner)
        self._rewrite_busy = False
        self._delete_busy = False
        self._generate_busy = False
        self._io_busy = False
        self._io_feedback_visible = False
        self._io_feedback_timer = QTimer(self)
        self._io_feedback_timer.setSingleShot(True)
        self._io_feedback_timer.setInterval(150)
        self._io_feedback_timer.timeout.connect(self._show_io_feedback)
        self._build_ui()
        self._history = ReportHistoryController(self.history_panel, view_model, self._job_runner, self._set_error, self)
        self._exports = ReportExportController(
            self, view_model, run_request=self._run_io, is_busy=lambda: self.is_busy,
            show_status=self._set_status, show_error=self._set_error,
        )

    @property
    def is_busy(self):
        return self._rewrite_busy or self._delete_busy or self._generate_busy or self._io_busy

    @property
    def _controls_busy(self):
        return (self._rewrite_busy or self._delete_busy or self._generate_busy
                or (self._io_busy and self._io_feedback_visible))

    def _show_io_feedback(self):
        if self._io_busy:
            self._io_feedback_visible = True
            self._update_busy_controls()

    def _run_io(self, name, operation, complete, *, defer_busy_feedback=False,
                error_code="report_request_failed"):
        if self.is_busy:
            return False
        self._io_busy = True
        self._io_feedback_visible = not defer_busy_feedback
        if defer_busy_feedback:
            self._io_feedback_timer.start()
        self._update_busy_controls()
        def finished(result):
            self._io_feedback_timer.stop()
            self._io_busy = False
            self._io_feedback_visible = False
            try:
                complete(result)
            finally:
                self._update_busy_controls()
        try:
            self._job_runner.submit(name, lambda _token: operation(), on_complete=owned_callback(self, finished))
        except Exception:
            finished(Result.failure(InfrastructureError(error_code, error_code)))
            return False
        return True

    @property
    def last_error(self) -> AppError | None:
        return self._last_error

    @property
    def has_unsaved_changes(self) -> bool:
        return self.editor.toPlainText() != self._saved_content.get(self._rendered_type, "")

    def confirm_leave(self) -> bool:
        if self.is_busy:
            self._set_status(_("Please wait for the current request."))
            return False
        if not self.has_unsaved_changes:
            return True
        confirmed = (
            self._confirm_discard()
            if self._confirm_discard is not None
            else QMessageBox.question(
                self,
                _("Discard changes?"),
                _("You have unsaved report changes. Discard them?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            ) == QMessageBox.StandardButton.Yes
        )
        if confirmed:
            self.editor.setPlainText(self._saved_content.get(self._rendered_type, ""))
        return bool(confirmed)

    def refresh(self, selected_day: date | None = None) -> bool:
        if not self.confirm_leave():
            return False
        if selected_day is not None:
            self._selected_day = selected_day
        if self._view_model is None:
            self._set_status(_("Reports are not configured."), error=True)
            return False
        day = self._selected_day
        def load():
            states = {}
            for kind in ("daily", "weekly", "monthly"):
                result = self._view_model.load(kind, day)
                if not result.ok:
                    return result
                states[kind] = result.value
            return Result.success(states)
        def complete(result):
            if not result.ok or result.value is None:
                self._set_error(result.error)
                return
            states = result.value
            self._states = states
            self._saved_content = {kind: state.content for kind, state in states.items()}
            self._render_current(refresh_history=False)
            self._refresh_history(reset=True)
            self._set_status("")
        return self._run_io("load_reports", load, complete, defer_busy_feedback=True)

    def copy_markdown(self) -> None:
        if self.is_busy:
            return
        QApplication.clipboard().setText(self.editor.toPlainText())
        self._set_status(_("Copied"))

    def export_markdown(self, destination: Path) -> bool:
        return self._exports.export_markdown(destination, self._export_snapshot())

    def _export_snapshot(self) -> ReportExportSnapshot:
        report_type = self._current_type()
        return ReportExportSnapshot(report_type, self._selected_day, self._states.get(report_type),
                                    self.editor.toPlainText())

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        self.report_type_control = SegmentedControl(
            (
                ("daily", _("Daily Report")),
                ("weekly", _("Weekly Report")),
                ("monthly", _("Monthly Report")),
            ), tabs=True,
        )
        self.report_type_control.value_changed.connect(self._change_report_type)
        root.addWidget(self.report_type_control)

        content = QHBoxLayout()
        content.setSpacing(16)
        root.addLayout(content, 1)

        self.editor_panel = ReportEditorPanel(
            ai_ready=self._ai_ready,
            timesheet_available=bool(getattr(self._view_model, "timesheet_available", False)),
        )
        for name in self.editor_panel.control_names:
            setattr(self, name, getattr(self.editor_panel, name))
        self.previous_period_button.clicked.connect(lambda: self._shift_period(-1))
        self.next_period_button.clicked.connect(lambda: self._shift_period(1))
        self.templates_button.clicked.connect(self._open_templates)
        self.generate_button.clicked.connect(self._generate_current)
        self.editor.textChanged.connect(self._update_report_status)
        self.ai_assist_button.clicked.connect(self._rewrite_current)
        self.versions_button.clicked.connect(self._open_versions)
        self.processing_progress.cancel_requested.connect(self._rewrite_task.cancel)
        self._rewrite_task.started.connect(lambda: self.processing_progress.start(_("Polishing text...")))
        self._rewrite_task.finished.connect(self.processing_progress.finish)
        self.copy_button.clicked.connect(self.copy_markdown)
        self.save_button.clicked.connect(self._save_current)
        self.export_current_button.export_requested.connect(self._choose_export_scope)
        content.addWidget(self.editor_panel, 2)

        self.history_panel = ReportHistoryPanel(allow_delete=bool(getattr(self._view_model, "delete_available", False)),
                                               show_export=False, day=self._selected_day)
        self.history_panel.item_selected.connect(self._select_history_item)
        self.history_panel.delete_requested.connect(self._delete_history_item)
        content.addWidget(self.history_panel, 1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("reports_status_label")
        self.status_label.setProperty("role", "secondary")
        self.status_label.hide()
        root.addWidget(self.status_label)
        self._update_report_status()

    def _update_report_status(self):
        if not hasattr(self, "save_button"):
            return
        state = self._states.get(self._current_type())
        self.versions_button.setEnabled(not self._controls_busy and state is not None and state.report_id is not None
            and bool(getattr(self._view_model, "revisions_available", False)))
        if state is None:
            self.report_state_label.clear()
            self.save_button.setEnabled(False)
            self.export_current_button.setEnabled(False)
            self.copy_button.setEnabled(False)
            self.generate_button.setEnabled(False)
            self._update_ai_controls()
            return
        modified = self.editor.toPlainText() != self._saved_content.get(self._current_type(), state.content)
        identity = (_("Saved report #{report_id}").format(report_id=state.report_id)
                    if state.report_id is not None else _("Generated draft"))
        self.report_state_label.setText(identity + (" | " + _("Unsaved changes") if modified else ""))
        from worklogger.presentation.report_source_labels import provenance_text
        self.report_state_label.setToolTip(provenance_text(state.provenance, include_references=False))
        if state.report_id is not None:
            self.report_state_label.setText(self.report_state_label.text() + " | " + _("Version {number}").format(number=state.revision + 1))
        self.save_button.setText(_("Save changes") if state.report_id is not None else _("Save Report"))
        busy = self._controls_busy
        has_content = bool(self.editor.toPlainText().strip())
        self.save_button.setEnabled(not busy and has_content and (state.report_id is None or modified))
        saved_export = bool(getattr(self._view_model, "saved_export_available", False))
        timesheet_export = bool(getattr(self._view_model, "timesheet_available", False))
        self.export_current_button.setEnabled(not busy and (has_content or saved_export or timesheet_export))
        for action in self.export_current_button.menu().actions():
            key = action.data()
            action.setEnabled(not busy and (timesheet_export if action.menu() is not None else has_content if key == "current" else saved_export))
            if key == "day":
                action.setText(_("Saved daily report") + f" ({self._selected_day.isoformat()})")
            elif key == "month":
                action.setText(_("Saved daily reports for this month") + f" ({self._selected_day:%Y-%m})")
        self.copy_button.setEnabled(not busy and has_content)
        self.generate_button.setEnabled(not busy and self._view_model is not None)
        self._update_ai_controls()

    def refresh_ai_availability(self):
        self._ai_ready = bool(self._view_model is not None and getattr(self._view_model, "rewrite_available", True))
        self._update_ai_controls()

    def _update_ai_controls(self):
        available = self._ai_ready
        busy = self._controls_busy
        self.ai_assist_button.setEnabled(available and not busy and bool(self.editor.toPlainText().strip()))
        self.ai_hint_line_edit.setEnabled(available and not busy)
        self.ai_assist_button.setToolTip("" if available else _("AI Assist is not configured."))

    def _generate_current(self):
        if self._view_model is None or self.is_busy:
            return
        state = self._states.get(self._current_type())
        if state is None:
            return
        if (state.report_id is not None or self.has_unsaved_changes) and QMessageBox.question(self, _("Generate from records"),
            _("Replace the visible draft with current records? The saved report will not change until you save."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self._generate_busy = True
        self._update_busy_controls()
        def complete(result):
            self._generate_busy = False
            self._update_busy_controls()
            if result.ok and result.value is not None:
                self._last_error = None
                generated = result.value
                if isinstance(generated, str):
                    self.editor.setPlainText(generated)
                else:
                    self._states[state.report_type] = replace(state, provenance=generated.provenance)
                    self.editor.setPlainText(generated.content)
            else:
                self._set_error(result.error or ValidationError("report_generate_failed", "report_generate_failed"))
        try:
            generator = getattr(self._view_model, "generate_with_sources", None) or self._view_model.generate_draft
            self._job_runner.submit("generate_report", lambda _token: generator(state), on_complete=owned_callback(self, complete))
        except Exception:
            self._generate_busy = False
            self._update_busy_controls()
            self._set_error(ValidationError("report_generate_failed", "report_generate_failed"))

    def _open_versions(self):
        state = self._states.get(self._current_type())
        if state is None or self.is_busy or not self.versions_button.isEnabled():
            return
        from worklogger.presentation.widgets.report_revisions import ReportRevisionsDialog
        dialog = ReportRevisionsDialog(self._view_model, state, self, job_runner=self._job_runner)
        def restored(value):
            self._states[value.report_type] = value
            self._saved_content[value.report_type] = value.content
            self.editor.setPlainText(value.content)
            self._update_report_status()
            self._refresh_history()
        dialog.restored.connect(restored)
        dialog.finished.connect(dialog.deleteLater)
        dialog.open()

    def _set_status(self, message: str, *, notify: bool = False, error: bool = False) -> None:
        if not error:
            self._last_error = None
        self.status_label.setText(message)
        self.status_label.setVisible(bool(message) and not notify)
        if message and notify:
            show = QMessageBox.warning if error else QMessageBox.information
            show(self, _("Reports"), message)

    def _current_type(self) -> str:
        return self.report_type_control.value or "daily"

    def _change_report_type(self, report_type: str) -> None:
        if not self.confirm_leave():
            self.report_type_control.set_value(self._rendered_type, emit=False)
            return
        self._render_current()

    def _shift_period(self, direction: int) -> None:
        state = self._states.get(self._current_type())
        day = state.period_start if state is not None else self._selected_day
        try:
            target = shift_report_period(day, self._current_type(), direction)
        except (TypeError, ValueError):
            self._set_error(ValidationError("report_period_invalid", "report_period_invalid"))
            return
        self.refresh(target)

    def _open_templates(self) -> None:
        if self._view_model is None or self.is_busy:
            return
        dialog = ReportTemplateDialog(self._view_model, self._current_type(), self)
        dialog.apply_requested.connect(self._apply_template)
        if dialog.refresh():
            dialog.exec()
        else:
            self._set_status(dialog.status_label.text(), error=True)

    def _apply_template(self) -> None:
        self._generate_current()

    def _render_current(self, *, refresh_history=True) -> None:
        report_type = self._current_type()
        state = self._states.get(report_type)
        if state is None:
            return
        self._rendered_type = report_type
        self.period_title_label.setText(report_period_label(state.report_type, state.period_start, state.period_end))
        with QSignalBlocker(self.editor):
            self.editor.setPlainText(state.content)
            self._saved_content[report_type] = self.editor.toPlainText()
        self._update_report_status()
        if refresh_history:
            self._refresh_history()

    def _save_current(self) -> None:
        if self._view_model is None or self.is_busy:
            return
        report_type = self._current_type()
        state = self._states.get(report_type)
        if state is None:
            self._set_error(ValidationError("report_not_loaded", "report_not_loaded"))
            return
        content = self.editor.toPlainText()
        if state.report_id is not None:
            if content == self._saved_content.get(report_type, state.content) or not confirm_report_overwrite(self):
                return
        def complete(result):
            if not result.ok or result.value is None:
                self._set_error(result.error)
                return
            self._states[report_type] = result.value
            self._saved_content[report_type] = result.value.content
            self._update_report_status()
            self._set_status(_("Report saved."))
            self._refresh_history()
        self._run_io("save_report", lambda: self._view_model.save(state, content), complete)

    def _rewrite_current(self) -> None:
        if self._view_model is None or self.is_busy:
            return
        state = self._states.get(self._current_type())
        if state is None:
            self._set_error(ValidationError("report_not_loaded", "report_not_loaded"))
            return
        content = self.editor.toPlainText()
        instructions = self.ai_hint_line_edit.text()
        self._set_rewrite_busy(True)
        self._set_status(_("Rewriting report..."), notify=False)
        self._rewrite_task.run("rewrite_report", lambda token: self._view_model.rewrite(state, content, instructions, cancellation_token=token),
                               on_complete=self._complete_rewrite)

    def _set_rewrite_busy(self, busy: bool) -> None:
        self._rewrite_busy = busy
        self._update_busy_controls()

    def _update_busy_controls(self):
        busy = self._controls_busy
        self.editor.setReadOnly(self.is_busy)
        for widget in (self.report_type_control, self.previous_period_button, self.next_period_button, self.templates_button, self.history_panel):
            widget.setEnabled(not busy)
        self._update_report_status()

    def _delete_history_item(self, item: ReportHistoryDisplayItem) -> None:
        if self._view_model is None or self.is_busy or item.report_id is None:
            return
        state = self._states.get(item.report_type)
        deleting_current = state is not None and state.report_id == item.report_id
        message = _("Delete report #{report_id}? This cannot be undone.").format(report_id=item.report_id)
        if deleting_current and self.has_unsaved_changes:
            message += "\n" + _("Unsaved edits to this report will also be discarded.")
        if QMessageBox.question(self, _("Delete report"), message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self._delete_busy = True
        self._update_busy_controls()

        def complete(result):
            self._delete_busy = False
            self._update_busy_controls()
            if not result.ok:
                self._set_error(result.error)
                return
            if deleting_current:
                self._states[item.report_type] = replace(state, content="", saved=False, report_id=None, created_at=None)
                self._saved_content[item.report_type] = ""
                if self._rendered_type == item.report_type:
                    self.editor.clear()
            self._last_error = None
            self._refresh_history()

        try:
            self._job_runner.submit("delete_report", lambda _token: self._view_model.delete(item), on_complete=owned_callback(self, complete))
        except Exception:
            self._delete_busy = False
            self._update_busy_controls()
            self._set_error(ValidationError("report_delete_failed", "report_delete_failed"))

    def _complete_rewrite(self, result: object) -> None:
        self._set_rewrite_busy(False)
        if not isinstance(result.error, CancellationError):
            self.refresh_ai_availability()
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return
        self.editor.setPlainText(result.value)
        self._set_status(_("Rewritten"))

    def _refresh_history(self, *, reset=False) -> None:
        self.history_panel.set_context(self._current_type(), self._selected_day, reset=reset,
                                      week_start_monday=bool(getattr(self._view_model, "week_start_monday", False)))
        state = self._states.get(self._current_type())
        self.history_panel.set_selected_report(state.report_id if state is not None else None)
        self._history.refresh()

    def _select_history_item(self, item: ReportHistoryDisplayItem) -> None:
        if not self._view_model or not self.confirm_leave():
            state = self._states.get(self._rendered_type)
            self.history_panel.set_selected_report(state.report_id if state else None)
            return
        def complete(result):
            if not result.ok or result.value is None:
                self._set_error(result.error)
                return
            self._show_history_report(result.value)
        self._run_io("load_saved_report", lambda: self._view_model.load_history_report(item.report_id), complete,
                     defer_busy_feedback=True)

    def _show_history_report(self, state):
        self._states[state.report_type] = state
        self._saved_content[state.report_type] = state.content
        self._rendered_type = state.report_type
        self._selected_day = state.period_start
        self.report_type_control.set_value(state.report_type, emit=False)
        self.history_panel.set_selected_report(state.report_id)
        self.editor.setPlainText(state.content)
        self._saved_content[state.report_type] = self.editor.toPlainText()
        self.period_title_label.setText(report_period_label(state.report_type, state.period_start, state.period_end))
        self._update_report_status()

    def _choose_export_scope(self, scope: str) -> None:
        self._exports.choose_scope(scope, self._export_snapshot())

    def _set_error(self, error: AppError | None) -> None:
        if isinstance(error, CancellationError):
            self._last_error = None
            self._set_status(display_error_message(error), notify=False)
            return
        self._last_error = error
        self._set_status(display_error_message(error), notify=True, error=True)
