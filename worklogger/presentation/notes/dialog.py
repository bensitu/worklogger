"""Daily memo editor with recoverable drafts and account-scoped history."""

from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, QLocale, QSignalBlocker, QTimer, Signal, Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QFileDialog,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QTextEdit, QToolButton, QVBoxLayout, QWidget)

from worklogger.domain.notes.preferences import NoteSharing
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.errors import CancellationError
from worklogger.infrastructure.i18n import _, get_language
from worklogger.presentation.widgets.two_line_delegate import TwoLineItemDelegate
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.job_runner import QtJobRunner
from worklogger.presentation.widgets.assets import apply_window_icon
from worklogger.presentation.widgets.icons import set_button_icon
from worklogger.presentation.widgets.feedback import show_information
from worklogger.presentation.processing import TextProcessingTask
from worklogger.presentation.widgets.processing_progress import ProcessingProgress


class NoteEditorDialog(QDialog):
    saved = Signal()

    def __init__(self, view_model, day: date, parent=None, *, job_runner=None, confirm_discard_changes=None):
        super().__init__(parent)
        self._view_model, self._day = view_model, day
        self._ai_ready = view_model.rewrite_available
        self._job_runner = job_runner or QtJobRunner(self)
        self._rewrite_task = TextProcessingTask(self, job_runner=self._job_runner)
        self._confirm_discard_changes = confirm_discard_changes
        self._state = None
        self._last_error = None
        self._busy = False
        self._draft_busy = False
        self._search_busy = False
        self._search_revision = 0
        self._closed = False
        self._after_draft = None
        self._version = 0
        self._updating = False
        self._saved_content = ""
        self._saved_sharing = NoteSharing()
        self.setObjectName("note_editor_dialog")
        self.setWindowTitle(_("Notes"))
        apply_window_icon(self)
        self.resize(900, 640)
        self.setMinimumSize(760, 520)
        self._build_ui()
        self._draft_timer = QTimer(self)
        self._draft_timer.setSingleShot(True)
        self._draft_timer.setInterval(800)
        self._draft_timer.timeout.connect(self._persist_draft)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(650)
        self._search_timer.timeout.connect(self._search)
        self.finished.connect(self._stop_search)

    @property
    def last_error(self):
        return self._last_error

    @property
    def has_unsaved_changes(self):
        return self.editor.toPlainText() != self._saved_content or self._sharing() != self._saved_sharing

    def _sharing(self):
        return NoteSharing(self.report_checkbox.isChecked(), self.ai_checkbox.isChecked())

    def refresh(self):
        if self._busy:
            return False
        day = self._day
        def complete(state):
            self.set_state(state)
            self._search()
        self._run("load_note", lambda: self._view_model.load(day), complete)
        return True

    def set_state(self, state):
        self._search_revision += 1
        self._updating = True
        try:
            self._state = state
            self._day = state.note.day
            self._saved_content, self._saved_sharing = state.note.content, state.saved_sharing
            day = state.note.day
            self.date_label.setText(QLocale(get_language()).toString(
                QDate(day.year, day.month, day.day), QLocale.FormatType.LongFormat))
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
        self._sync_history_selection()
        self._update_actions()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        root.setSpacing(16)
        body = QHBoxLayout()
        body.setSpacing(20)
        sidebar = QWidget()
        sidebar.setMinimumWidth(190)
        sidebar.setMaximumWidth(250)
        history = QVBoxLayout(sidebar)
        history.setContentsMargins(0, 0, 0, 0)
        history.setSpacing(12)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(_("Search notes"))
        self.search_input.setClearButtonEnabled(True)
        history.addWidget(self.search_input)
        self.history_list = QListWidget()
        self.history_list.setObjectName("note_history_list_widget")
        self.history_list.setAccessibleName(_("Notes"))
        self.history_list.setItemDelegate(TwoLineItemDelegate(self.history_list))
        self.history_list.setSpacing(4)
        self.history_list.setFrameShape(QFrame.Shape.NoFrame)
        self.history_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.empty_label = QLabel(_("No notes found"))
        self.empty_label.setProperty("role", "secondary")
        self.empty_label.setWordWrap(True)
        self.empty_label.hide()
        history.addWidget(self.empty_label)
        history.addWidget(self.history_list, 1)
        body.addWidget(sidebar, 1)
        content = QVBoxLayout()
        content.setSpacing(12)
        heading = QHBoxLayout()
        heading.setSpacing(8)
        self.date_label = QLabel()
        self.date_label.setWordWrap(True)
        self.date_label.setProperty("role", "section_heading")
        heading.addWidget(self.date_label, 1)
        self.rewrite_button = QPushButton(_("Polish text"))
        set_button_icon(self.rewrite_button, "sparkles")
        heading.addWidget(self.rewrite_button)
        self.copy_button = QToolButton()
        self.copy_button.setObjectName("note_copy_button")
        self.copy_button.setProperty("variant", "outline")
        self.copy_button.setToolTip(_("Copy Markdown"))
        self.copy_button.setAccessibleName(_("Copy Markdown"))
        set_button_icon(self.copy_button, "copy")
        self.export_button = QToolButton()
        self.export_button.setObjectName("note_export_button")
        self.export_button.setProperty("variant", "outline")
        self.export_button.setToolTip(_("Export Markdown"))
        self.export_button.setAccessibleName(_("Export Markdown"))
        set_button_icon(self.export_button, "file-output")
        heading.addWidget(self.export_button)
        heading.addWidget(self.copy_button)
        self.reload_button = QToolButton()
        self.reload_button.setObjectName("note_reload_button")
        self.reload_button.setProperty("variant", "outline")
        self.reload_button.setToolTip(_("Reload saved note"))
        self.reload_button.setAccessibleName(_("Reload saved note"))
        set_button_icon(self.reload_button, "refresh-cw")
        heading.addWidget(self.reload_button)
        content.addLayout(heading)
        self.recovery_label = QLabel(_("Recovered draft"))
        self.recovery_label.setProperty("role", "secondary")
        content.addWidget(self.recovery_label)
        self.editor = QTextEdit()
        self.editor.setObjectName("note_text_edit")
        self.editor.setAcceptRichText(False)
        self.editor.setAccessibleName(_("Notes"))
        self.editor.setPlaceholderText(_("Write a note for this date..."))
        content.addWidget(self.editor, 1)
        self.processing_progress = ProcessingProgress()
        self.processing_progress.cancel_requested.connect(self._rewrite_task.cancel)
        self._rewrite_task.started.connect(lambda: self.processing_progress.start(_("Polishing text...")))
        self._rewrite_task.finished.connect(self.processing_progress.finish)
        content.addWidget(self.processing_progress)
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
        body.addLayout(content, 3)
        root.addLayout(body, 1)
        tools = QHBoxLayout()
        self.close_button = QPushButton(_("Close"))
        self.save_button = QPushButton(_("Save"))
        self.save_button.setProperty("variant", "primary")
        set_button_icon(self.save_button, "save")
        for button in (self.rewrite_button, self.copy_button, self.export_button, self.reload_button,
                       self.close_button, self.save_button):
            button.setMinimumHeight(36)
        for button in (self.copy_button, self.export_button, self.reload_button):
            button.setMinimumWidth(36)
        tools.addStretch()
        tools.addWidget(self.close_button)
        tools.addWidget(self.save_button)
        root.addLayout(tools)
        QWidget.setTabOrder(self.rewrite_button, self.export_button)
        QWidget.setTabOrder(self.export_button, self.copy_button)
        QWidget.setTabOrder(self.copy_button, self.reload_button)
        self.editor.textChanged.connect(self._changed)
        self.report_checkbox.toggled.connect(self._changed)
        self.ai_checkbox.toggled.connect(self._changed)
        self.search_input.textChanged.connect(self._schedule_search)
        self.history_list.currentItemChanged.connect(
            lambda current, _previous: self._select_note(current) if current is not None else None)
        self.insert_button.clicked.connect(self._transfer_previous_entries)
        self.reload_button.clicked.connect(self._reload)
        self.rewrite_button.clicked.connect(self._rewrite)
        self.copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self.editor.toPlainText()))
        self.export_button.clicked.connect(self._choose_export_path)
        self.close_button.clicked.connect(self.reject)
        self.save_button.clicked.connect(self._save)
        self._update_actions()

    def _update_actions(self):
        has_content = bool(self.editor.toPlainText().strip())
        self.rewrite_button.setEnabled(not self._busy and has_content and self._ai_ready)
        self.copy_button.setEnabled(has_content)
        self.export_button.setEnabled(has_content)

    def refresh_ai_availability(self):
        self._ai_ready = self._view_model.rewrite_available
        self._update_actions()

    def _sync_history_selection(self):
        with QSignalBlocker(self.history_list):
            self.history_list.setCurrentRow(-1)
            for row in range(self.history_list.count()):
                item = self.history_list.item(row)
                if item.data(Qt.ItemDataRole.UserRole) == self._day:
                    self.history_list.setCurrentItem(item)
                    break

    def _changed(self, *_args):
        self._update_actions()
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
            self._set_error(InfrastructureError("note_save_failed", "note_save_failed"))

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
            self._set_error(InfrastructureError("note_save_failed", "note_save_failed"))

    def _schedule_search(self, *_args):
        self._search_revision += 1
        self._search_timer.start()

    def _stop_search(self, *_args):
        self._closed = True
        self._search_timer.stop()

    def _search(self):
        if self._closed:
            return
        if self._busy or self._search_busy:
            self._search_timer.start()
            return
        query, day, revision = self.search_input.text(), self._day, self._search_revision
        def render(notes):
            previews = {note.day: " ".join(note.content.split()) for note in notes}
            if not query.strip() and self._state is not None:
                previews.setdefault(self._day, " ".join(self._state.content.split()))
            with QSignalBlocker(self.history_list):
                self.history_list.clear()
                for day, preview in sorted(previews.items(), reverse=True):
                    item = QListWidgetItem(day.isoformat() + "\n" + (preview[:160] or _("No note yet")))
                    item.setData(Qt.ItemDataRole.UserRole, day)
                    self.history_list.addItem(item)
            self.empty_label.setVisible(not previews)
            self._sync_history_selection()
        self._search_busy = True
        def done(result):
            self._search_busy = False
            if self._closed:
                return
            if revision != self._search_revision or day != self._day or self._busy:
                self._search_timer.start()
                return
            if result.ok:
                render(result.value)
            else:
                self._set_error(result.error)
        try:
            self._job_runner.submit("search_notes", lambda _token: self._view_model.search(query), on_complete=done)
        except Exception:
            self._search_busy = False
            self._set_error(InfrastructureError("note_load_failed", "note_load_failed"))

    def _transfer_previous_entries(self):
        if self._state is None or not self._state.previous_entries or self._busy:
            return
        if QMessageBox.question(self, _("Add to note"),
            _("Add these entries to the note and save it? Their original records will be deleted only if saving succeeds."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        state, sharing = self._state, self._sharing()
        content = self._view_model.insert_previous_entries(state, self.editor.toPlainText())
        self.editor.setPlainText(content)
        content = self.editor.toPlainText()
        self._run("transfer_note_entries", lambda: self._view_model.transfer_previous_entries(state, content, sharing),
                  self._note_saved)

    def _select_note(self, item):
        day = item.data(Qt.ItemDataRole.UserRole)
        if day == self._day or self._busy:
            self._sync_history_selection()
            return
        if self.has_unsaved_changes and QMessageBox.question(self, _("Keep draft"),
            _("Keep the current draft and open another date?"), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            self._sync_history_selection()
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
        self._run("save_note", lambda: self._view_model.save(state, content, sharing), self._note_saved)

    def _note_saved(self, workspace):
        self.set_state(workspace)
        self.saved.emit()
        show_information(self, _("Notes"), _("Note saved."),
                         detail=_("Your changes have been saved for {date}.").format(date=workspace.note.day.isoformat()))
        self._search()

    def _rewrite(self):
        if self._busy or self._rewrite_task.is_running:
            return
        if self._draft_busy:
            self._after_draft = self._rewrite
            return
        content = self.editor.toPlainText()
        self._draft_timer.stop()
        self._busy = True
        self.editor.setReadOnly(True)
        self._last_error = None
        for field in (self.history_list, self.search_input, self.reload_button, self.save_button,
                      self.insert_button, self.report_checkbox, self.ai_checkbox):
            field.setEnabled(False)
        self.rewrite_button.setEnabled(False)
        self.close_button.setEnabled(False)
        def completed(result):
            self._busy = False
            self.editor.setReadOnly(False)
            for field in (self.history_list, self.search_input, self.reload_button, self.save_button,
                          self.insert_button, self.report_checkbox, self.ai_checkbox, self.close_button):
                field.setEnabled(True)
            if result.ok:
                self.editor.setPlainText(result.value)
            elif not isinstance(result.error, CancellationError):
                self._set_error(result.error)
            else:
                self._draft_timer.start()
            if not isinstance(result.error, CancellationError):
                self._ai_ready = self._view_model.rewrite_available
            self._update_actions()
        self._rewrite_task.run("rewrite_note", lambda _token: self._view_model.rewrite(content), on_complete=completed)

    def export_markdown(self, destination: Path):
        content = self.editor.toPlainText()
        self._run("export_note", lambda: self._view_model.export_markdown(destination, content),
                  lambda _path: show_information(self, _("Export Markdown"), _("Exported Markdown")))

    def _choose_export_path(self):
        path, _filter = QFileDialog.getSaveFileName(self, _("Export Markdown"), f"note-{self._day.isoformat()}.md", _("Markdown files (*.md)"))
        if path:
            self.export_markdown(Path(path))

    def _set_error(self, error):
        self._last_error = error
        self._sync_history_selection()
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
            box = QMessageBox(QMessageBox.Icon.Question, _("Notes"), _("Keep this draft for later?"),
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
