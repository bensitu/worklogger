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
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from worklogger.domain.shared.errors import AppError, ValidationError
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.viewmodels import ReportEditorState, ReportEditorViewModel
from worklogger.presentation.widgets.assets import apply_window_icon


class ReportDialog(QDialog):
    saved = Signal()

    def __init__(
        self,
        view_model: ReportEditorViewModel,
        selected_day: date,
        parent: QWidget | None = None,
        confirm_discard_changes: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self._view_model = view_model
        self._selected_day = selected_day
        self._confirm_discard_changes = confirm_discard_changes
        self._states: dict[str, ReportEditorState] = {}
        self._saved_content: dict[str, str] = {}
        self._last_error: AppError | None = None
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
            self.status_label.setText(_("Ready"))
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

        bottom = QHBoxLayout()
        self.status_label = QLabel("")
        self.save_button = QPushButton(_("Save"))
        self.save_button.setObjectName("save_report_button")
        self.save_button.setProperty("variant", "primary")
        self.close_button = QPushButton(_("Close"))
        bottom.addWidget(self.status_label, 1)
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
        result = self._view_model.save(state, self._current_editor().toPlainText())
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
        path, _ = QFileDialog.getSaveFileName(
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
        report_type = self._current_type()
        state = self._states.get(report_type)
        if state is None:
            self._set_error(ValidationError("report_not_loaded", "report_not_loaded"))
            return
        result = self._view_model.rewrite(state, self._current_editor().toPlainText())
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return
        self._current_editor().setPlainText(result.value)
        self.status_label.setText(_("Rewritten"))

    def _set_error(self, error: AppError | None) -> None:
        self._last_error = error
        self.status_label.setText(display_error_message(error))

    def reject(self) -> None:
        if not self._confirm_discard_changes_if_needed():
            return
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
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
