"""Daily memo editor with recoverable drafts and account-scoped history."""

from datetime import date
from pathlib import Path

from PySide6.QtCore import QTimer, Signal, Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QFileDialog,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QTextEdit, QToolButton, QVBoxLayout, QWidget)

from worklogger.domain.notes.preferences import NoteSharing
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.job_runner import QtJobRunner
from worklogger.presentation.widgets.assets import apply_window_icon
from worklogger.presentation.widgets.icons import set_button_icon


class NoteEditorDialog(QDialog):
    saved = Signal()

    def __init__(self, view_model, day: date, parent=None, *, job_runner=None, confirm_discard_changes=None):
        super().__init__(parent)
        self._view_model, self._day = view_model, day
        self._job_runner = job_runner or QtJobRunner(self)
        self._confirm_discard_changes = confirm_discard_changes
        self._state = None
        self._last_error = None
        self._busy = False
        self._draft_busy = False
        self._after_draft = None
        self._version = 0
        self._updating = False
        self._saved_content = ""
        self._saved_sharing = NoteSharing()
        self.setObjectName("note_editor_dialog")
        self.setWindowTitle(_("Daily notes"))
        apply_window_icon(self)
        self.resize(740, 580)
        self._build_ui()
        self._draft_timer = QTimer(self)
        self._draft_timer.setSingleShot(True)
        self._draft_timer.setInterval(800)
        self._draft_timer.timeout.connect(self._persist_draft)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self._search)

    @property
    def last_error(self):
        return self._last_error

    @property
    def has_unsaved_changes(self):
        return self.editor.toPlainText() != self._saved_content or self._sharing() != self._saved_sharing

    def _sharing(self):
        return NoteSharing(self.report_checkbox.isChecked(), self.ai_checkbox.isChecked())

    def refresh(self):
        result = self._view_model.load(self._day)
        if not result.ok:
            self._set_error(result.error)
            return False
        self.set_state(result.value)
        self._search()
        return True

    def set_state(self, state):
        self._updating = True
        try:
            self._state = state
            self._day = state.note.day
            self._saved_content, self._saved_sharing = state.note.content, state.saved_sharing
            self.date_label.setText(state.note.day.isoformat())
            self.editor.setPlainText(state.content)
            self.report_checkbox.setChecked(state.sharing.reports)
            self.ai_checkbox.setChecked(state.sharing.ai)
            self.recovery_label.setVisible(state.recovered_draft)
            self.previous_list.clear()
            for entry in state.previous_entries:
                span = " - ".join(part for part in (entry.start_time, entry.end_time) if part)
                self.previous_list.addItem((span + "\n" if span else "") + entry.description)
            self.previous_group.setVisible(bool(state.previous_entries))
            self._last_error = None
        finally:
            self._updating = False

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(_("Search notes"))
        row.addWidget(self.search_input, 1)
        self.date_label = QLabel()
        row.addWidget(self.date_label)
        self.reload_button = QToolButton()
        self.reload_button.setToolTip(_("Reload saved note"))
        set_button_icon(self.reload_button, "rotate-ccw")
        row.addWidget(self.reload_button)
        root.addLayout(row)
        body = QHBoxLayout()
        self.history_list = QListWidget()
        self.history_list.setMaximumWidth(190)
        body.addWidget(self.history_list)
        content = QVBoxLayout()
        self.recovery_label = QLabel(_("Recovered draft"))
        self.recovery_label.setProperty("role", "secondary")
        content.addWidget(self.recovery_label)
        self.editor = QTextEdit()
        self.editor.setObjectName("note_text_edit")
        self.editor.setAcceptRichText(False)
        content.addWidget(self.editor, 1)
        self.previous_group = QWidget()
        previous = QVBoxLayout(self.previous_group)
        previous.setContentsMargins(0, 0, 0, 0)
        previous.addWidget(QLabel(_("Previous entries")))
        self.previous_list = QListWidget()
        self.previous_list.setWordWrap(True)
        self.previous_list.setMaximumHeight(110)
        previous.addWidget(self.previous_list)
        self.insert_button = QPushButton(_("Add to note"))
        set_button_icon(self.insert_button, "plus")
        previous.addWidget(self.insert_button)
        content.addWidget(self.previous_group)
        self.report_checkbox = QCheckBox(_("Allow in reports"))
        self.ai_checkbox = QCheckBox(_("Allow in AI context"))
        content.addWidget(self.report_checkbox)
        content.addWidget(self.ai_checkbox)
        body.addLayout(content, 1)
        root.addLayout(body, 1)
        tools = QHBoxLayout()
        self.rewrite_button = QPushButton(_("Polish text"))
        set_button_icon(self.rewrite_button, "sparkles", accent=True)
        self.rewrite_button.setEnabled(self._view_model.rewrite_available)
        self.copy_button = QToolButton()
        self.copy_button.setToolTip(_("Copy Markdown"))
        set_button_icon(self.copy_button, "copy")
        self.export_button = QToolButton()
        self.export_button.setToolTip(_("Export Markdown"))
        set_button_icon(self.export_button, "download")
        self.close_button = QPushButton(_("Close"))
        self.save_button = QPushButton(_("Save"))
        self.save_button.setProperty("variant", "primary")
        set_button_icon(self.save_button, "save")
        for button in (self.rewrite_button, self.copy_button, self.export_button):
            tools.addWidget(button)
        tools.addStretch()
        tools.addWidget(self.close_button)
        tools.addWidget(self.save_button)
        root.addLayout(tools)
        self.editor.textChanged.connect(self._changed)
        self.report_checkbox.toggled.connect(self._changed)
        self.ai_checkbox.toggled.connect(self._changed)
        self.search_input.textChanged.connect(lambda: self._search_timer.start())
        self.history_list.itemActivated.connect(self._select_note)
        self.history_list.itemClicked.connect(self._select_note)
        self.insert_button.clicked.connect(lambda: self.editor.setPlainText(
            self._view_model.insert_previous_entries(self._state, self.editor.toPlainText())))
        self.reload_button.clicked.connect(self._reload)
        self.rewrite_button.clicked.connect(self._rewrite)
        self.copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self.editor.toPlainText()))
        self.export_button.clicked.connect(self._choose_export_path)
        self.close_button.clicked.connect(self.reject)
        self.save_button.clicked.connect(self._save)

    def _changed(self, *_args):
        if self._updating or self._state is None:
            return
        self._version += 1
        self._draft_timer.start()

    def _set_busy(self, busy):
        self._busy = busy
        self.setEnabled(not busy)

    def _run(self, name, operation, completed):
        if self._busy:
            return
        self._draft_timer.stop()
        if self._draft_busy:
            self._set_busy(True)
            self._after_draft = lambda: self._run(name, operation, completed)
            return
        self._set_busy(True)
        def done(result):
            self._set_busy(False)
            if result.ok:
                self._last_error = None
                completed(result.value)
            else:
                self._set_error(result.error)
        try:
            self._job_runner.submit(name, lambda _token: operation(), on_complete=done)
        except Exception:
            self._set_busy(False)
            self._set_error(None)

    def _persist_draft(self):
        if self._state is None or self._busy or self._draft_busy:
            return
        state, content, sharing, version = self._state, self.editor.toPlainText(), self._sharing(), self._version
        self._draft_busy = True
        def done(result):
            self._draft_busy = False
            if not result.ok:
                self._set_error(result.error)
            if self._after_draft is not None:
                action, self._after_draft = self._after_draft, None
                self._set_busy(False)
                action()
            elif result.ok and version != self._version:
                self._draft_timer.start()
        try:
            self._job_runner.submit("save_note_draft", lambda _token: self._view_model.save_draft(state, content, sharing), on_complete=done)
        except Exception:
            self._draft_busy = False
            self._set_error(None)

    def _search(self):
        if self._busy or self._draft_busy:
            self._search_timer.start()
            return
        query = self.search_input.text()
        def render(notes):
            self.history_list.clear()
            for note in notes:
                preview = note.content.splitlines()[0][:45] if note.content else _("Previous entries")
                item = QListWidgetItem(note.day.isoformat() + "\n" + preview)
                item.setData(Qt.ItemDataRole.UserRole, note.day)
                self.history_list.addItem(item)
        self._run("search_notes", lambda: self._view_model.search(query), render)

    def _select_note(self, item):
        day = item.data(Qt.ItemDataRole.UserRole)
        if day == self._day or self._busy:
            return
        if self.has_unsaved_changes and QMessageBox.question(self, _("Keep draft"),
            _("Keep the current draft and open another date?"), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        state, content, sharing = self._state, self.editor.toPlainText(), self._sharing()
        def load():
            saved = self._view_model.save_draft(state, content, sharing)
            return self._view_model.load(day) if saved.ok else saved
        self._run("load_note", load, self.set_state)

    def _reload(self):
        if self.has_unsaved_changes and QMessageBox.question(self, _("Discard changes?"),
            _("You have unsaved note changes. Discard them?"), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self._run("reload_note", lambda: self._view_model.reload(self._day), self.set_state)

    def _save(self):
        if self._state is None:
            return
        state, content, sharing = self._state, self.editor.toPlainText(), self._sharing()
        def saved(workspace):
            self.set_state(workspace)
            self.saved.emit()
            QMessageBox.information(self, _("Daily notes"), _("Saved"))
            self._search()
        self._run("save_note", lambda: self._view_model.save(state, content, sharing), saved)

    def _rewrite(self):
        content = self.editor.toPlainText()
        self._run("rewrite_note", lambda: self._view_model.rewrite(content), self.editor.setPlainText)

    def export_markdown(self, destination: Path):
        content = self.editor.toPlainText()
        self._run("export_note", lambda: self._view_model.export_markdown(destination, content),
                  lambda _path: QMessageBox.information(self, _("Export Markdown"), _("Exported Markdown")))

    def _choose_export_path(self):
        path, _filter = QFileDialog.getSaveFileName(self, _("Export Markdown"), f"note-{self._day.isoformat()}.md", _("Markdown files (*.md)"))
        if path:
            self.export_markdown(Path(path))

    def _set_error(self, error):
        self._last_error = error
        QMessageBox.warning(self, _("Error"), display_error_message(error))

    def _request_close(self):
        if self._busy:
            return
        if self._state is None:
            QDialog.reject(self)
            return
        if self.has_unsaved_changes and self._confirm_discard_changes is not None:
            if not self._confirm_discard_changes():
                return
            self._run("close_note", lambda: self._view_model.discard_draft(self._day), lambda _value: QDialog.reject(self))
            return
        if self.has_unsaved_changes:
            box = QMessageBox(QMessageBox.Icon.Question, _("Daily notes"), _("Keep this draft for later?"),
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel, self)
            box.button(QMessageBox.StandardButton.Save).setText(_("Keep draft"))
            box.button(QMessageBox.StandardButton.Discard).setText(_("Discard"))
            box.button(QMessageBox.StandardButton.Cancel).setText(_("Cancel"))
            box.setDefaultButton(QMessageBox.StandardButton.Cancel)
            answer = box.exec()
            box.deleteLater()
            if answer == QMessageBox.StandardButton.Cancel:
                return
            state, content, sharing = self._state, self.editor.toPlainText(), self._sharing()
            job = (lambda: self._view_model.save_draft(state, content, sharing)) if answer == QMessageBox.StandardButton.Save else (lambda: self._view_model.discard_draft(self._day))
        else:
            job = lambda: self._view_model.discard_draft(self._day)
        self._run("close_note", job, lambda _value: QDialog.reject(self))

    def reject(self):
        self._request_close()

    def closeEvent(self, event):
        event.ignore()
        self._request_close()
