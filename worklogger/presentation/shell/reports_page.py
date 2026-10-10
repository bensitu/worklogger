"""Period report editing and saved history."""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Callable
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from worklogger.app.job_runner import JobRunner
from worklogger.domain.shared.dates import add_months
from worklogger.domain.shared.errors import (
    AppError,
    CancellationError,
    InfrastructureError,
    ValidationError,
)
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import _
from worklogger.presentation.date_labels import period_range_label
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.job_runner import QtJobRunner
from worklogger.presentation.reporting.dialog import (
    ReportTemplateDialog,
    confirm_report_overwrite,
)
from worklogger.presentation.viewmodels import (
    ReportEditorState,
    ReportEditorViewModel,
)
from worklogger.presentation.widgets import (
    CardFrame,
    ExportMenuButton,
    ReportHistoryDisplayItem,
    ReportHistoryPanel,
    SegmentedControl,
)
from worklogger.presentation.widgets.icons import IconLabel, set_button_icon
from worklogger.presentation.processing import TextProcessingTask
from worklogger.presentation.widgets.processing_progress import ProcessingProgress


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
        self._build_ui()

    @property
    def is_busy(self):
        return self._rewrite_busy or self._delete_busy or self._generate_busy or self._io_busy

    def _run_io(self, name, operation, complete):
        if self.is_busy:
            return False
        self._io_busy = True
        self._update_busy_controls()
        def finished(result):
            self._io_busy = False
            self._update_busy_controls()
            complete(result)
        try:
            self._job_runner.submit(name, lambda _token: operation(), on_complete=finished)
        except Exception:
            finished(Result.failure(InfrastructureError("report_request_failed", "report_request_failed")))
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
        day, report_type = self._selected_day, self._current_type()
        def load():
            states = {}
            for kind in ("daily", "weekly", "monthly"):
                result = self._view_model.load(kind, day)
                if not result.ok:
                    return result
                states[kind] = result.value
            history = self._view_model.list_history(report_type)
            if not history.ok:
                return history
            return Result.success((states, history.value))
        def complete(result):
            if not result.ok or result.value is None:
                self._set_error(result.error)
                return
            states, history = result.value
            self._states = states
            self._saved_content = {kind: state.content for kind, state in states.items()}
            self._render_current(refresh_history=False)
            self._set_history(history)
            self._set_status("")
        return self._run_io("load_reports", load, complete)

    def copy_markdown(self) -> None:
        QApplication.clipboard().setText(self.editor.toPlainText())
        self._set_status(_("Copied"))

    def export_markdown(self, destination: Path) -> bool:
        if self._view_model is None:
            return False
        content = self.editor.toPlainText()
        state = self._states.get(self._current_type())
        period = _period_label(state) if state is not None else period_range_label(self._selected_day, self._selected_day)
        def complete(result):
            if not result.ok:
                self._set_error(result.error)
            else:
                self._set_status(_("Current report exported for {period}.").format(period=period))
        exporter = getattr(self._view_model, "export_with_sources", None)
        return self._run_io("export_report", lambda: exporter(destination, state, content) if exporter and state
                            else self._view_model.export_markdown(destination, content), complete)

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

        editor_card = CardFrame(object_name="report_editor_frame")
        period_row = QHBoxLayout()
        self.period_title_label = QLabel("")
        self.period_title_label.setObjectName("report_period_label")
        self.period_title_label.setProperty("role", "title")
        self.previous_period_button = QPushButton("<")
        self.previous_period_button.setObjectName("previous_report_period_button")
        self.previous_period_button.setProperty("variant", "outline")
        self.previous_period_button.clicked.connect(lambda: self._shift_period(-1))
        self.previous_period_button.setToolTip(_("Previous period"))
        self.previous_period_button.setAccessibleName(_("Previous period"))
        set_button_icon(self.previous_period_button, "chevron-left")
        self.previous_period_button.setText("")
        self.next_period_button = QPushButton(">")
        self.next_period_button.setObjectName("next_report_period_button")
        self.next_period_button.setProperty("variant", "outline")
        self.next_period_button.clicked.connect(lambda: self._shift_period(1))
        self.next_period_button.setToolTip(_("Next period"))
        self.next_period_button.setAccessibleName(_("Next period"))
        set_button_icon(self.next_period_button, "chevron-right")
        self.next_period_button.setText("")
        period_row.addWidget(IconLabel("calendar-days"))
        self.period_title_label.setWordWrap(True)
        period_row.addWidget(self.period_title_label, 1)
        self.previous_period_button.setFixedWidth(34)
        self.next_period_button.setFixedWidth(34)
        period_row.addWidget(self.previous_period_button)
        period_row.addWidget(self.next_period_button)
        editor_card.content_layout.addLayout(period_row)
        divider = QFrame()
        divider.setObjectName("report_period_separator_frame")
        divider.setFixedHeight(1)
        editor_card.content_layout.addWidget(divider)

        report_row = QHBoxLayout()
        report_title = QLabel(_("Report"))
        report_title.setObjectName("report_title_label")
        self.templates_button = QPushButton(_("Templates"))
        self.templates_button.setObjectName("templates_button")
        self.templates_button.setProperty("variant", "outline")
        self.templates_button.clicked.connect(self._open_templates)
        set_button_icon(self.templates_button, "file-text")
        report_row.addWidget(report_title, 1)
        self.generate_button = QPushButton(_("Generate from records"))
        self.generate_button.setObjectName("generate_report_button")
        set_button_icon(self.generate_button, "file-plus-2")
        self.generate_button.clicked.connect(self._generate_current)
        report_row.addWidget(self.generate_button)
        report_row.addWidget(self.templates_button)
        editor_card.content_layout.addLayout(report_row)

        self.editor = QTextEdit()
        self.editor.setObjectName("report_text_edit")
        self.editor.setAcceptRichText(False)
        self.editor.textChanged.connect(self._update_report_status)
        self.report_state_label = QLabel()
        self.report_state_label.setObjectName("report_state_label")
        self.report_state_label.setProperty("role", "secondary")
        self.report_state_label.setWordWrap(True)
        editor_card.content_layout.addWidget(self.report_state_label)
        editor_card.content_layout.addWidget(self.editor, 1)

        self.ai_hint_line_edit = QLineEdit()
        self.ai_hint_line_edit.setObjectName("ai_hint_line_edit")
        self.ai_hint_line_edit.setPlaceholderText(_("AI Assist Hint / extra instructions (optional)"))
        editor_card.content_layout.addWidget(self.ai_hint_line_edit)

        ai_row = QHBoxLayout()
        self.ai_assist_button = QPushButton(_("Polish text"))
        self.ai_assist_button.setObjectName("report_ai_assist_button")
        self.ai_assist_button.setProperty("variant", "outline")
        self.ai_assist_button.clicked.connect(self._rewrite_current)
        set_button_icon(self.ai_assist_button, "sparkles")
        if not self._ai_ready:
            self.ai_assist_button.setEnabled(False)
            self.ai_assist_button.setToolTip(_("AI Assist is not configured."))
            self.ai_hint_line_edit.setEnabled(False)
        ai_row.addWidget(self.ai_assist_button)
        ai_row.addStretch(1)
        self.versions_button = QPushButton(_("Report versions"))
        set_button_icon(self.versions_button, "history")
        self.versions_button.clicked.connect(self._open_versions)
        ai_row.addWidget(self.versions_button)
        editor_card.content_layout.addLayout(ai_row)
        self.processing_progress = ProcessingProgress()
        self.processing_progress.cancel_requested.connect(self._rewrite_task.cancel)
        self._rewrite_task.started.connect(lambda: self.processing_progress.start(_("Polishing text...")))
        self._rewrite_task.finished.connect(self.processing_progress.finish)
        editor_card.content_layout.addWidget(self.processing_progress)

        bottom = QHBoxLayout()
        self.copy_button = QToolButton()
        self.copy_button.setProperty("variant", "outline")
        self.copy_button.setToolTip(_("Copy"))
        self.copy_button.setAccessibleName(_("Copy"))
        self.copy_button.setFixedSize(40, 40)
        self.copy_button.setObjectName("copy_report_button")
        self.copy_button.clicked.connect(self.copy_markdown)
        set_button_icon(self.copy_button, "copy")
        self.save_button = QPushButton(_("Save Report"))
        self.save_button.setObjectName("save_report_button")
        self.save_button.setProperty("variant", "primary")
        self.save_button.clicked.connect(self._save_current)
        set_button_icon(self.save_button, "save")
        bottom.addWidget(self.copy_button)
        self.export_current_button = ExportMenuButton(_("Export report"),
            (("current", _("Current visible report")), ("day", _("Saved daily report")), ("month", _("Saved daily reports for this month"))))
        self.export_current_button.setObjectName("export_current_report_button")
        self.export_current_button.setProperty("variant", "outline")
        self.export_current_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        set_button_icon(self.export_current_button, "file-output")
        self.export_current_button.setMinimumWidth(self.export_current_button.fontMetrics().horizontalAdvance(self.export_current_button.text()) + 56)
        self.export_current_button.export_requested.connect(self._choose_export_scope)
        if bool(getattr(self._view_model, "timesheet_available", False)):
            menu = self.export_current_button.menu().addMenu(_("Timesheet"))
            for key, caption in (("timesheet_day_xlsx", _("Selected day (Excel)")), ("timesheet_month_xlsx", _("Selected month (Excel)")),
                                 ("timesheet_day_pdf", _("Selected day (PDF)")), ("timesheet_month_pdf", _("Selected month (PDF)"))):
                action = menu.addAction(caption)
                action.setData(key)
                action.triggered.connect(lambda _checked=False, key=key: self._choose_export_scope(key))
        bottom.addWidget(self.export_current_button)
        bottom.addStretch(1)
        bottom.addWidget(self.save_button)
        editor_card.content_layout.addLayout(bottom)
        content.addWidget(editor_card, 2)

        self.history_panel = ReportHistoryPanel(allow_delete=bool(getattr(self._view_model, "delete_available", False)), show_export=False)
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
        self.versions_button.setEnabled(not self.is_busy and state is not None and state.report_id is not None
            and bool(getattr(self._view_model, "revisions_available", False)))
        if state is None:
            self.report_state_label.clear()
            self.save_button.setEnabled(False)
            self.export_current_button.setEnabled(False)
            self.copy_button.setEnabled(False)
            self.generate_button.setEnabled(False)
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
        busy = self.is_busy
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
        busy = self.is_busy
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
            generator = getattr(self._view_model, "generate_with_sources", self._view_model.generate_draft)
            self._job_runner.submit("generate_report", lambda _token: generator(state), on_complete=complete)
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

    def _set_status(self, message: str, *, notify: bool = True, error: bool = False) -> None:
        if not error:
            self._last_error = None
        self.status_label.setText(message)
        self.status_label.hide()
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
        self.refresh(shift_period(day, self._current_type(), direction))

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
        self.period_title_label.setText(_period_label(state))
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
        self._rewrite_task.run("rewrite_report", lambda _token: self._view_model.rewrite(state, content, instructions),
                               on_complete=self._complete_rewrite)

    def _set_rewrite_busy(self, busy: bool) -> None:
        self._rewrite_busy = busy
        self._update_busy_controls()

    def _update_busy_controls(self):
        busy = self.is_busy
        self.editor.setReadOnly(busy)
        for widget in (self.report_type_control, self.previous_period_button, self.next_period_button, self.templates_button, self.ai_hint_line_edit, self.save_button, self.history_panel):
            widget.setEnabled(not busy)
        self.ai_assist_button.setEnabled(not busy and self._ai_ready)
        self.ai_hint_line_edit.setEnabled(self.ai_assist_button.isEnabled())
        self.generate_button.setEnabled(not busy)
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
            self._job_runner.submit("delete_report", lambda _token: self._view_model.delete(item), on_complete=complete)
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

    def _refresh_history(self) -> None:
        self.history_panel.set_report_type(self._current_type())
        if self._view_model is None:
            self.history_panel.set_items(())
            return
        report_type = self._current_type()
        def complete(result):
            if not result.ok or result.value is None:
                self._set_error(result.error)
            else:
                self._set_history(result.value)
        self._run_io("load_report_history", lambda: self._view_model.list_history(report_type), complete)

    def _set_history(self, items):
        self.history_panel.set_report_type(self._current_type())
        self.history_panel.set_items(
            ReportHistoryDisplayItem(
                report_id=item.report_id,
                user_id=item.user_id,
                report_type=item.report_type,
                period_start=item.period_start,
                period_end=item.period_end,
                label=period_range_label(item.period_start, item.period_end),
                content=item.content,
                saved=item.saved,
                created_at=item.created_at,
                revision=getattr(item, "revision", 0), updated_at=getattr(item, "updated_at", None),
                provenance=getattr(item, "provenance", ReportEditorState.__dataclass_fields__["provenance"].default),
            )
            for item in items
        )
        state = self._states.get(self._current_type())
        self.history_panel.set_selected_report(state.report_id if state is not None else None)

    def _select_history_item(self, item: ReportHistoryDisplayItem) -> None:
        if not self._view_model or not self.confirm_leave():
            state = self._states.get(self._rendered_type)
            self.history_panel.set_selected_report(state.report_id if state else None)
            return
        state = ReportEditorState(
            user_id=item.user_id,
            report_type=item.report_type,
            period_start=item.period_start,
            period_end=item.period_end,
            content=item.content,
            saved=True,
            report_id=item.report_id,
            created_at=item.created_at,
            revision=item.revision, updated_at=item.updated_at, provenance=item.provenance,
        )
        self._states[item.report_type] = state
        self._saved_content[item.report_type] = state.content
        self._rendered_type = item.report_type
        self._selected_day = item.period_start
        self.report_type_control.set_value(item.report_type, emit=False)
        self.history_panel.set_selected_report(item.report_id)
        self.editor.setPlainText(state.content)
        self._saved_content[item.report_type] = self.editor.toPlainText()
        self.period_title_label.setText(_period_label(state))
        self._update_report_status()

    def _choose_export_scope(self, scope: str) -> None:
        if scope.startswith("timesheet_"):
            self._export_timesheet(scope)
            return
        if scope not in {"current", "day", "month"} or self._view_model is None or self.is_busy:
            return
        state = self._states.get(self._current_type())
        suffix = state.period_start.isoformat() if state is not None else self._selected_day.isoformat()
        identity = str(state.report_id) if state is not None and state.report_id is not None else "draft"
        filename = f"{self._current_type()}-report-{suffix}-{identity}.md"
        if scope != "current":
            filename = "daily-reports-" + (self._selected_day.strftime("%Y-%m") if scope == "month" else self._selected_day.isoformat()) + ".md"
        path, _selected = QFileDialog.getSaveFileName(
            self,
            _("Export Markdown"),
            filename,
            _("Markdown files (*.md)"),
        )
        if path:
            if scope == "current":
                self.export_markdown(Path(path))
            else:
                day = self._selected_day
                self._generate_busy = True
                self._update_busy_controls()
                def complete(result):
                    self._generate_busy = False
                    self._update_busy_controls()
                    if result.ok:
                        self._set_status(_("Saved daily reports exported."))
                    else:
                        self._set_error(result.error)
                try:
                    self._job_runner.submit("export_saved_reports", lambda _token: self._view_model.export_saved_daily(
                        Path(path), day, whole_month=scope == "month"), on_complete=complete)
                except Exception:
                    complete(Result.failure(InfrastructureError("report_export_failed", "report_export_failed")))

    def _export_timesheet(self, scope):
        options = {"timesheet_day_xlsx": (False, "xlsx"), "timesheet_month_xlsx": (True, "xlsx"),
                   "timesheet_day_pdf": (False, "pdf"), "timesheet_month_pdf": (True, "pdf")}
        if scope not in options or self.is_busy or not bool(getattr(self._view_model, "timesheet_available", False)):
            return
        whole_month, format = options[scope]
        day = self._selected_day
        suffix = day.strftime("%Y-%m") if whole_month else day.isoformat()
        path, _selected = QFileDialog.getSaveFileName(self, _("Export timesheet"), f"timesheet-{suffix}.{format}",
            _("Excel files (*.xlsx)") if format == "xlsx" else _("PDF files (*.pdf)"))
        if not path:
            return
        self._generate_busy = True
        self._update_busy_controls()
        def completed(result):
            self._generate_busy = False
            self._update_busy_controls()
            if result.ok:
                self._set_status(_("Timesheet exported."))
            else:
                self._set_error(result.error)
        try:
            self._job_runner.submit("export_timesheet", lambda _token: self._view_model.export_timesheet(
                Path(path), day, whole_month=whole_month, format=format), on_complete=completed)
        except Exception:
            completed(Result.failure(InfrastructureError("timesheet_export_failed", "timesheet_export_failed")))

    def _set_error(self, error: AppError | None) -> None:
        if isinstance(error, CancellationError):
            self._last_error = None
            self._set_status(display_error_message(error), notify=False)
            return
        self._last_error = error
        self._set_status(display_error_message(error), error=True)

def _period_label(state: ReportEditorState) -> str:
    label = period_range_label(state.period_start, state.period_end)
    if state.report_type == "weekly":
        label += " " + _("(Week {week})").format(week=state.period_start.isocalendar().week)
    return label

def shift_period(day: date, report_type: str, direction: int) -> date:
    if report_type == "daily":
        return day + timedelta(days=direction)
    if report_type == "weekly":
        return day + timedelta(days=direction * 7)
    shifted = add_months(day.replace(day=1), direction)
    last = monthrange(shifted.year, shifted.month)[1]
    return shifted.replace(day=min(day.day, last))
