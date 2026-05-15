"""Daily note editor dialog."""

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
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from worklogger.domain.shared.errors import AppError
from worklogger.infrastructure.i18n import _
from worklogger.presentation.viewmodels import NoteEditorState, NoteEditorViewModel


class NoteEditorDialog(QDialog):
    saved = Signal()

    def __init__(
        self,
        view_model: NoteEditorViewModel,
        day: date,
        parent: QWidget | None = None,
        confirm_discard_changes: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self._view_model = view_model
        self._day = day
        self._confirm_discard_changes = confirm_discard_changes
        self._state: NoteEditorState | None = None
        self._last_error: AppError | None = None
        self._saved_content = ""
        self.setObjectName("note_editor_dialog")
        self.setWindowTitle(_("Notes"))
        self._build_ui()

    @property
    def last_error(self) -> AppError | None:
        return self._last_error

    @property
    def has_unsaved_changes(self) -> bool:
        return self.editor.toPlainText() != self._saved_content

    def refresh(self) -> bool:
        result = self._view_model.load(self._day)
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return False
        self.set_state(result.value)
        self.status_label.setText(_("Ready"))
        return True

    def set_state(self, state: NoteEditorState) -> None:
        self._state = state
        self.date_label.setText(state.day.isoformat())
        self.editor.setPlainText(state.content)
        self._saved_content = state.content
        if state.calendar_events:
            summaries = " / ".join(event.summary for event in state.calendar_events[:4])
            self.calendar_label.setText(_("Calendar events: {events}").format(events=summaries))
            self.calendar_label.setVisible(True)
        else:
            self.calendar_label.setVisible(False)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        self.date_label = QLabel("")
        self.date_label.setObjectName("note_date_label")
        root.addWidget(self.date_label)

        self.calendar_label = QLabel("")
        self.calendar_label.setObjectName("note_calendar_events_label")
        self.calendar_label.setWordWrap(True)
        root.addWidget(self.calendar_label)

        self.editor = QTextEdit()
        self.editor.setObjectName("note_text_edit")
        root.addWidget(self.editor, 1)

        tools = QHBoxLayout()
        self.template_button = QPushButton(_("Apply template"))
        self.quick_logs_button = QPushButton(_("Insert Quick Log"))
        self.rewrite_button = QPushButton(_("Rewrite"))
        self.copy_button = QPushButton(_("Copy Markdown"))
        self.export_button = QPushButton(_("Export Markdown"))
        tools.addWidget(self.template_button)
        tools.addWidget(self.quick_logs_button)
        tools.addWidget(self.rewrite_button)
        tools.addWidget(self.copy_button)
        tools.addWidget(self.export_button)
        tools.addStretch(1)
        root.addLayout(tools)

        template_tools = QHBoxLayout()
        self.save_template_button = QPushButton(_("Save template"))
        self.reset_template_button = QPushButton(_("Reset template"))
        template_tools.addWidget(self.save_template_button)
        template_tools.addWidget(self.reset_template_button)
        template_tools.addStretch(1)
        root.addLayout(template_tools)

        bottom = QHBoxLayout()
        self.status_label = QLabel("")
        self.save_button = QPushButton(_("Save"))
        self.save_button.setObjectName("save_note_button")
        self.save_button.setProperty("variant", "primary")
        self.close_button = QPushButton(_("Close"))
        bottom.addWidget(self.status_label, 1)
        bottom.addWidget(self.close_button)
        bottom.addWidget(self.save_button)
        root.addLayout(bottom)

        self.template_button.clicked.connect(self._apply_template)
        self.quick_logs_button.clicked.connect(self._insert_quick_logs)
        self.rewrite_button.clicked.connect(self._rewrite)
        self.copy_button.clicked.connect(self.copy_markdown)
        self.export_button.clicked.connect(self._choose_export_path)
        self.save_template_button.clicked.connect(self._save_template)
        self.reset_template_button.clicked.connect(self._reset_template)
        self.save_button.clicked.connect(self._save)
        self.close_button.clicked.connect(self.reject)

    def _insert_quick_logs(self) -> None:
        if self._state is None:
            return
        updated = self._view_model.insert_quick_logs(
            NoteEditorState(
                user_id=self._state.user_id,
                day=self._state.day,
                content=self.editor.toPlainText(),
                quick_logs=self._state.quick_logs,
                calendar_events=self._state.calendar_events,
            )
        )
        self.editor.setPlainText(updated)

    def _apply_template(self) -> None:
        if self._state is None:
            return
        result = self._view_model.apply_template(self._state)
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return
        self.editor.setPlainText(result.value)

    def copy_markdown(self) -> None:
        QApplication.clipboard().setText(self.editor.toPlainText())
        self.status_label.setText(_("Copied"))

    def export_markdown(self, destination: Path) -> bool:
        result = self._view_model.export_markdown(destination, self.editor.toPlainText())
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return False
        self.status_label.setText(_("Exported Markdown"))
        return True

    def _choose_export_path(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            _("Export Markdown"),
            f"note-{self._day.isoformat()}.md",
            _("Markdown files (*.md)"),
        )
        if path:
            self.export_markdown(Path(path))

    def _save_template(self) -> None:
        result = self._view_model.save_template(self.editor.toPlainText())
        if not result.ok:
            self._set_error(result.error)
            return
        self.status_label.setText(_("Template saved."))

    def _reset_template(self) -> None:
        result = self._view_model.reset_template()
        if not result.ok:
            self._set_error(result.error)
            return
        self.status_label.setText(_("Template reset."))

    def _rewrite(self) -> None:
        result = self._view_model.rewrite(self.editor.toPlainText())
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return
        self.editor.setPlainText(result.value)
        self.status_label.setText(_("Rewritten"))

    def _save(self) -> None:
        result = self._view_model.save(self._day, self.editor.toPlainText())
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return
        self._state = result.value
        self._saved_content = result.value.content
        self.status_label.setText(_("Saved"))
        self.saved.emit()

    def _set_error(self, error: AppError | None) -> None:
        self._last_error = error
        self.status_label.setText(error.message if error is not None else _("Unknown error"))

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
        self._saved_content = self.editor.toPlainText()
        return True

    def _ask_discard_changes(self) -> bool:
        answer = QMessageBox.question(
            self,
            _("Discard changes?"),
            _("You have unsaved note changes. Discard them?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes
