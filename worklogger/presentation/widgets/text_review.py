"""Editable text comparison with cancellable background regeneration."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                              QStackedWidget, QVBoxLayout, QWidget)

from worklogger.domain.shared.errors import CancellationError
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.processing import TextProcessingTask
from worklogger.presentation.widgets.assets import apply_window_icon
from worklogger.presentation.widgets.icons import set_button_icon
from worklogger.presentation.widgets.processing_progress import ProcessingProgress


class TextReviewDialog(QDialog):
    def __init__(self, source, result, *, operation, available, instructions="", job_runner=None, parent=None):
        super().__init__(parent)
        self._operation, self._available = operation, available
        self._closed = False
        self._task = TextProcessingTask(self, job_runner=job_runner)
        self.setWindowTitle(_("Review AI text"))
        self.setObjectName("text_review_dialog")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        apply_window_icon(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        root.setSpacing(12)
        intro = QLabel(_("Compare and edit both versions. Your original text changes only when you choose Use text."))
        intro.setWordWrap(True)
        root.addWidget(intro)
        columns = QHBoxLayout()
        columns.setSpacing(16)
        self.source_edit = QPlainTextEdit(source)
        self.source_edit.setPlaceholderText(_("Enter the text to polish."))
        self.result_edit = QPlainTextEdit(result)
        self.result_edit.setPlaceholderText(_("The revised text will appear here."))
        self.result_stack = QStackedWidget()
        self.result_stack.addWidget(self.result_edit)
        busy_page = QFrame()
        busy_page.setProperty("role", "processing_input")
        busy_layout = QVBoxLayout(busy_page)
        busy_layout.addStretch()
        self.progress = ProcessingProgress()
        self.progress.cancel_requested.connect(self._task.cancel)
        busy_layout.addWidget(self.progress)
        busy_layout.addStretch()
        self.result_stack.addWidget(busy_page)
        for title, editor, content in ((_("Source text"), self.source_edit, self.source_edit),
                                       (_("Revised text"), self.result_edit, self.result_stack)):
            column = QVBoxLayout()
            label = QLabel(title)
            label.setProperty("role", "section_heading")
            label.setBuddy(editor)
            editor.setAccessibleName(title)
            editor.setMinimumWidth(0)
            column.addWidget(label)
            column.addWidget(content, 1)
            columns.addLayout(column, 1)
        root.addLayout(columns, 1)
        label = QLabel(_("Additional instructions"))
        self.instructions_edit = QPlainTextEdit(instructions)
        self.instructions_edit.setAccessibleName(label.text())
        self.instructions_edit.setPlaceholderText(_("For example: make it more concise, keep the bullet points, or use a formal tone."))
        instructions_area = QWidget()
        instructions_area.setFixedHeight(84)
        instructions_layout = QVBoxLayout(instructions_area)
        instructions_layout.setContentsMargins(0, 0, 0, 0)
        instructions_layout.addWidget(self.instructions_edit)
        label.setBuddy(self.instructions_edit)
        root.addWidget(label)
        root.addWidget(instructions_area)
        self.status_label = QLabel(" ")
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setProperty("role", "secondary")
        self.status_label.setMinimumHeight(self.status_label.fontMetrics().lineSpacing() * 2)
        root.addWidget(self.status_label)
        footer = QHBoxLayout()
        self.retry_button = QPushButton(_("Polish again"))
        self.cancel_button = QPushButton(_("Cancel"))
        self.use_button = QPushButton(_("Use text"))
        self.use_button.setProperty("variant", "primary")
        for button, icon in ((self.retry_button, "sparkles"), (self.cancel_button, "x"), (self.use_button, "check")):
            button.setProperty("dialog_action", True)
            button.setAutoDefault(False)
            set_button_icon(button, icon)
        footer.addWidget(self.retry_button)
        footer.addStretch()
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.use_button)
        root.addLayout(footer)
        self.retry_button.clicked.connect(self._regenerate)
        self.cancel_button.clicked.connect(self.reject)
        self.use_button.clicked.connect(self.accept)
        self.source_edit.textChanged.connect(self._update_actions)
        self.result_edit.textChanged.connect(self._update_actions)
        screen = self.screen().availableGeometry()
        self.resize(min(1000, screen.width() - 40), min(680, screen.height() - 70))
        self._update_actions()

    def _update_actions(self):
        ready = self._available()
        running = self._task.is_running
        self.retry_button.setEnabled(ready and not running and bool(self.source_edit.toPlainText().strip()))
        self.use_button.setEnabled(ready and not running and bool(self.result_edit.toPlainText().strip()))
        self.source_edit.setReadOnly(running or not ready)
        self.instructions_edit.setReadOnly(running or not ready)
        self.result_edit.setReadOnly(running or not ready)

    def _regenerate(self):
        if self._closed or self._task.is_running or not self._available():
            self._update_actions()
            return
        source, instructions = self.source_edit.toPlainText(), self.instructions_edit.toPlainText()
        if not source.strip():
            return
        self.status_label.setText(" ")
        self.result_stack.setCurrentIndex(1)
        self.progress.start(_("Polishing text..."))
        self._task.run("ai_review_text", lambda token: self._operation(source, instructions, token), on_complete=self._completed)
        self._update_actions()

    def _completed(self, result):
        if self._closed:
            return
        self.progress.finish()
        self.result_stack.setCurrentIndex(0)
        if result.ok and result.value is not None:
            self.result_edit.setPlainText(result.value)
        elif not isinstance(result.error, CancellationError):
            self.status_label.setText(display_error_message(result.error))
        self._update_actions()

    def accept(self):
        if self._closed or self._task.is_running or not self._available() or not self.result_edit.toPlainText().strip():
            self._update_actions()
            return
        super().accept()

    def done(self, code):
        self._closed = True
        self._task.cancel()
        super().done(code)
