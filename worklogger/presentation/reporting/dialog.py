"""Report dialog."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QLabel,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from worklogger.domain.shared.errors import AppError, CancellationError, ValidationError
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.viewmodels import ReportEditorState, ReportEditorViewModel
from worklogger.presentation.widgets.assets import apply_window_icon
from worklogger.presentation.widgets.status_label import StatusLabel
from worklogger.presentation.widgets.icons import set_button_icon
from worklogger.presentation.processing import TextProcessingTask
from worklogger.presentation.widgets.processing_progress import ProcessingProgress


def confirm_report_overwrite(parent: QWidget) -> bool:
    return QMessageBox.question(
        parent,
        _("Overwrite report?"),
        _("Replace the saved content of this report? Previous versions remain available in report versions."),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    ) == QMessageBox.StandardButton.Yes


class ReportTemplateDialog(QDialog):
    apply_requested = Signal()

    def __init__(self, view_model: ReportEditorViewModel, report_type: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._view_model = view_model
        self._report_type = report_type
        self._saved_template = ""
        self.setObjectName("report_template_dialog")
        self.setWindowTitle(_("Templates"))
        apply_window_icon(self)
        self.resize(620, 480)
        layout = QVBoxLayout(self)
        labels = {"daily": _("Daily Report"), "weekly": _("Weekly Report"), "monthly": _("Monthly Report")}
        self.scope_label = QLabel(_("Template: {type} | {language}").format(
            type=labels.get(report_type, report_type), language=getattr(view_model, "language", "en_US")))
        self.scope_label.setObjectName("template_scope_label")
        layout.addWidget(self.scope_label)
        self.editor = QTextEdit()
        self.editor.setObjectName("template_text_edit")
        self.editor.setAcceptRichText(False)
        self.editor.textChanged.connect(self._update_actions)
        layout.addWidget(self.editor, 1)
        self.status_label = StatusLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        row = QHBoxLayout()
        self.reset_button = QPushButton(_("Reset template"))
        self.reset_button.clicked.connect(self.reset_template)
        set_button_icon(self.reset_button, "rotate-ccw")
        self.save_button = QPushButton(_("Save template"))
        self.save_button.clicked.connect(self.save_template)
        set_button_icon(self.save_button, "save")
        self.apply_button = QPushButton(_("Save and apply"))
        self.apply_button.clicked.connect(self.apply_template)
        self.apply_button.setProperty("variant", "primary")
        for button in (self.reset_button, self.save_button, self.apply_button):
            row.addWidget(button)
        self.close_button = QPushButton(_("Close"))
        self.close_button.clicked.connect(self.reject)
        row.addWidget(self.close_button)
        layout.addLayout(row)

    def refresh(self) -> bool:
        result = self._view_model.load_template(self._report_type)
        if not result.ok or result.value is None:
            self.status_label.setText(display_error_message(result.error))
            return False
        self._saved_template = result.value
        self.editor.setPlainText(result.value)
        self._update_actions()
        self.status_label.clear()
        return True

    def save_template(self) -> bool:
        result = self._view_model.save_template(self._report_type, self.editor.toPlainText())
        if not result.ok:
            self.status_label.setText(display_error_message(result.error))
            return False
        self._saved_template = self.editor.toPlainText()
        self._update_actions()
        self.status_label.setText(_("Template saved."))
        return True

    def reset_template(self) -> bool:
        if QMessageBox.question(self, _("Reset template"), _("Reset this template to its default?"), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return False
        result = self._view_model.reset_template(self._report_type)
        if not result.ok:
            self.status_label.setText(display_error_message(result.error))
            return False
        return self.refresh()

    def apply_template(self) -> None:
        if self.editor.toPlainText() != self._saved_template and not self.save_template():
            return
        self.apply_requested.emit()
        self.accept()

    def _update_actions(self) -> None:
        if hasattr(self, "apply_button"):
            self.apply_button.setEnabled(bool(self.editor.toPlainText().strip()))

    def _confirm_close(self) -> bool:
        return self.editor.toPlainText() == self._saved_template or QMessageBox.question(self, _("Discard changes?"), _("You have unsaved template changes. Discard them?"), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def reject(self) -> None:
        if self._confirm_close():
            super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._confirm_close():
            event.accept()
        else:
            event.ignore()


class ReportDialog(QDialog):
    saved = Signal()

    def __init__(
        self,
        view_model: ReportEditorViewModel,
        selected_day: date,
        parent: QWidget | None = None,
        confirm_discard_changes: Callable[[], bool] | None = None,
        job_runner=None,
    ) -> None:
        super().__init__(parent)
        self._view_model = view_model
        self._selected_day = selected_day
        self._confirm_discard_changes = confirm_discard_changes
        self._states: dict[str, ReportEditorState] = {}
        self._saved_content: dict[str, str] = {}
        self._last_error: AppError | None = None
        self._rewrite_task = TextProcessingTask(self, job_runner=job_runner)
        self.setObjectName("report_dialog")
        self.setWindowTitle(_("Work Report"))
        apply_window_icon(self)
        self._build_ui()

    @property
    def last_error(self) -> AppError | None:
        return self._last_error

    @property
    def has_unsaved_changes(self) -> bool:
        for report_type, editor in self._editors().items():
            if editor.toPlainText() != self._saved_content.get(report_type, ""):
                return True
        return False

    def refresh(self) -> bool:
        ok = True
        for report_type, editor in self._editors().items():
            result = self._view_model.load(report_type, self._selected_day)
            if not result.ok or result.value is None:
                self._set_error(result.error)
                ok = False
                continue
            self._states[report_type] = result.value
            editor.setPlainText(result.value.content)
            self._saved_content[report_type] = result.value.content
        if ok:
            self._last_error = None
            self.status_label.clear()
        return ok

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        self.tabs = QTabWidget()
        self.daily_editor = self._editor()
        self.weekly_editor = self._editor()
        self.monthly_editor = self._editor()
        self.tabs.addTab(_tab(self.daily_editor), _("Daily Report"))
        self.tabs.addTab(_tab(self.weekly_editor), _("Weekly Report"))
        self.tabs.addTab(_tab(self.monthly_editor), _("Monthly Report"))
        root.addWidget(self.tabs, 1)

        tools = QHBoxLayout()
        self.rewrite_button = QPushButton(_("Rewrite"))
        self.rewrite_button.setEnabled(bool(self._view_model.rewrite_available))
        self.rewrite_button.setToolTip(_("Polish text") if self._view_model.rewrite_available else _("Text processing is not ready. Check AI settings."))
        self.copy_button = QPushButton(_("Copy Markdown"))
        self.export_button = QPushButton(_("Export Markdown"))
        self.save_template_button = QPushButton(_("Save template"))
        self.reset_template_button = QPushButton(_("Reset template"))
        tools.addWidget(self.rewrite_button)
        tools.addWidget(self.copy_button)
        tools.addWidget(self.export_button)
        tools.addWidget(self.save_template_button)
        tools.addWidget(self.reset_template_button)
        tools.addStretch(1)
        root.addLayout(tools)
        self.processing_progress = ProcessingProgress()
        self.processing_progress.cancel_requested.connect(self._rewrite_task.cancel)
        self._rewrite_task.started.connect(lambda: self.processing_progress.start(_("Polishing text...")))
        self._rewrite_task.finished.connect(self.processing_progress.finish)
        root.addWidget(self.processing_progress)

        bottom = QHBoxLayout()
        self.status_label = StatusLabel()
        self.save_button = QPushButton(_("Save"))
        self.save_button.setObjectName("save_report_button")
        self.save_button.setProperty("variant", "primary")
        self.close_button = QPushButton(_("Close"))
        bottom.addWidget(self.status_label, 1)
        bottom.addStretch()
        bottom.addWidget(self.close_button)
        bottom.addWidget(self.save_button)
        root.addLayout(bottom)

        self.rewrite_button.clicked.connect(self._rewrite_current)
        self.copy_button.clicked.connect(self.copy_markdown)
        self.export_button.clicked.connect(self._choose_export_path)
        self.save_template_button.clicked.connect(self._save_template_current)
        self.reset_template_button.clicked.connect(self._reset_template_current)
        self.save_button.clicked.connect(self._save_current)
        self.close_button.clicked.connect(self.reject)

    def _editor(self) -> QTextEdit:
        editor = QTextEdit()
        editor.setObjectName("report_text_edit")
        return editor

    def _editors(self) -> dict[str, QTextEdit]:
        return {
            "daily": self.daily_editor,
            "weekly": self.weekly_editor,
            "monthly": self.monthly_editor,
        }

    def _current_type(self) -> str:
        return ("daily", "weekly", "monthly")[self.tabs.currentIndex()]

    def _current_editor(self) -> QTextEdit:
        return self._editors()[self._current_type()]

    def _save_current(self) -> None:
        report_type = self._current_type()
        state = self._states.get(report_type)
        if state is None:
            self._set_error(ValidationError("report_not_loaded", "report_not_loaded"))
            return
        content = self._current_editor().toPlainText()
        if state.report_id is not None:
            if content == state.content or not confirm_report_overwrite(self):
                return
        result = self._view_model.save(state, content)
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return
        self._states[report_type] = result.value
        self._saved_content[report_type] = result.value.content
        self.status_label.setText(_("Report saved."))
        self.saved.emit()

    def copy_markdown(self) -> None:
        QApplication.clipboard().setText(self._current_editor().toPlainText())
        self.status_label.setText(_("Copied"))

    def export_markdown(self, destination: Path) -> bool:
        result = self._view_model.export_markdown(
            destination,
            self._current_editor().toPlainText(),
        )
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return False
        self.status_label.setText(_("Exported Markdown"))
        return True

    def _choose_export_path(self) -> None:
        report_type = self._current_type()
        state = self._states.get(report_type)
        suffix = state.period_start.isoformat() if state is not None else self._selected_day.isoformat()
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            _("Export Markdown"),
            f"{report_type}-report-{suffix}.md",
            _("Markdown files (*.md)"),
        )
        if path:
            self.export_markdown(Path(path))

    def _save_template_current(self) -> None:
        report_type = self._current_type()
        result = self._view_model.save_template(
            report_type,
            self._current_editor().toPlainText(),
        )
        if not result.ok:
            self._set_error(result.error)
            return
        self.status_label.setText(_("Template saved."))

    def _reset_template_current(self) -> None:
        result = self._view_model.reset_template(self._current_type())
        if not result.ok:
            self._set_error(result.error)
            return
        self.status_label.setText(_("Template reset."))

    def _rewrite_current(self) -> None:
        if self._rewrite_task.is_running or not self._view_model.rewrite_available:
            return
        report_type = self._current_type()
        state = self._states.get(report_type)
        if state is None:
            self._set_error(ValidationError("report_not_loaded", "report_not_loaded"))
            return
        editor = self._current_editor()
        content = editor.toPlainText()
        self.tabs.tabBar().setEnabled(False)
        editor.setReadOnly(True)
        for field in (self.rewrite_button, self.save_button, self.save_template_button,
                      self.reset_template_button, self.close_button):
            field.setEnabled(False)
        def completed(result):
            self.tabs.tabBar().setEnabled(True)
            editor.setReadOnly(False)
            for field in (self.rewrite_button, self.save_button, self.save_template_button,
                          self.reset_template_button, self.close_button):
                field.setEnabled(True)
            if not result.ok or result.value is None:
                self._set_error(result.error)
                return
            editor.setPlainText(result.value)
            self.status_label.setText(_("Rewritten"))
        self._rewrite_task.run("rewrite_report", lambda _token: self._view_model.rewrite(state, content), on_complete=completed)

    def _set_error(self, error: AppError | None) -> None:
        self._last_error = None if isinstance(error, CancellationError) else error
        self.status_label.setText(display_error_message(error))

    def reject(self) -> None:
        if self._rewrite_task.is_running:
            return
        if not self._confirm_discard_changes_if_needed():
            return
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._rewrite_task.is_running:
            event.ignore()
            return
        if not self._confirm_discard_changes_if_needed():
            event.ignore()
            return
        super().closeEvent(event)

    def _confirm_discard_changes_if_needed(self) -> bool:
        if not self.has_unsaved_changes:
            return True
        if self._confirm_discard_changes is not None:
            confirmed = bool(self._confirm_discard_changes())
        else:
            confirmed = self._ask_discard_changes()
        if not confirmed:
            self.status_label.setText(_("Unsaved changes"))
            return False
        self._saved_content = {
            report_type: editor.toPlainText()
            for report_type, editor in self._editors().items()
        }
        return True

    def _ask_discard_changes(self) -> bool:
        answer = QMessageBox.question(
            self,
            _("Discard changes?"),
            _("You have unsaved report changes. Discard them?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes


def _tab(editor: QTextEdit) -> QWidget:
    tab = QWidget()
    layout = QVBoxLayout(tab)
    layout.setContentsMargins(6, 6, 6, 6)
    layout.addWidget(editor)
    return tab
