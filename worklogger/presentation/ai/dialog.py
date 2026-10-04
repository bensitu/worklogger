"""AI Assist chat dialog."""

from __future__ import annotations

from datetime import date

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from worklogger.app.job_runner import JobHandle, JobRunner
from worklogger.domain.shared.errors import AppError, CancellationError
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.viewmodels import AiAssistViewModel, AiChatState
from worklogger.presentation.widgets.assets import apply_window_icon
from worklogger.presentation.widgets.status_label import StatusLabel


class AiAssistDialog(QDialog):
    def __init__(
        self,
        view_model: AiAssistViewModel,
        selected_day: date,
        parent: QWidget | None = None,
        job_runner: JobRunner | None = None,
    ) -> None:
        super().__init__(parent)
        self._view_model = view_model
        self._selected_day = selected_day
        self._state = view_model.initial_state()
        self._last_error: AppError | None = None
        self._job_runner = job_runner
        self._pending_handle: JobHandle[object] | None = None
        self.setObjectName("ai_assist_dialog")
        self.setWindowTitle(_("AI Assist"))
        apply_window_icon(self)
        self._build_ui()

    @property
    def last_error(self) -> AppError | None:
        return self._last_error

    @property
    def state(self) -> AiChatState:
        return self._state

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        self.context_label = QLabel(
            _("Selected day: {day}").format(day=self._selected_day.isoformat())
        )
        self.context_label.setObjectName("selected_day_context_label")
        root.addWidget(self.context_label)

        self.transcript = QTextEdit()
        self.transcript.setObjectName("ai_transcript_text_edit")
        self.transcript.setReadOnly(True)
        root.addWidget(self.transcript, 1)

        row = QHBoxLayout()
        self.message_input = QLineEdit()
        self.message_input.setPlaceholderText(_("Ask about your work logs"))
        self.send_button = QPushButton(_("Send"))
        row.addWidget(self.message_input, 1)
        row.addWidget(self.send_button)
        root.addLayout(row)

        bottom = QHBoxLayout()
        self.status_label = StatusLabel()
        self.close_button = QPushButton(_("Close"))
        bottom.addWidget(self.status_label, 1)
        bottom.addStretch()
        bottom.addWidget(self.close_button)
        root.addLayout(bottom)

        self.send_button.clicked.connect(self.send_current_message)
        self.message_input.returnPressed.connect(self.send_current_message)
        self.close_button.clicked.connect(self.accept)
        self._set_busy(False)
        if not self._view_model.available:
            self.status_label.setText(_("AI Assist is not configured."))
            self.send_button.setToolTip(_("AI Assist is not configured."))

    def send_current_message(self) -> bool:
        if not self._view_model.available:
            self.status_label.setText(_("AI Assist is not configured."))
            return False
        if self._pending_handle is not None:
            self.status_label.setText(_("Please wait for the current request."))
            return False
        message = self.message_input.text()
        if self._job_runner is not None:
            state = self._state
            selected_day = self._selected_day
            self._set_busy(True)
            self.status_label.setText(_("Sending..."))
            self._pending_handle = JobHandle(
                job_id="ai_chat_pending",
                cancel=lambda: None,
            )
            handle = self._job_runner.submit(
                "ai_chat",
                lambda _token: self._view_model.send(
                    state,
                    message,
                    selected_day=selected_day,
                    period_type="daily",
                ),
                on_complete=self._complete_send,
            )
            if self._pending_handle is not None:
                self._pending_handle = handle
            return True
        result = self._view_model.send(
            self._state,
            message,
            selected_day=self._selected_day,
            period_type="daily",
        )
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return False
        self._state = result.value
        self.message_input.clear()
        self._render_history()
        self._last_error = None
        self.status_label.clear()
        return True

    def _complete_send(self, result: object) -> None:
        self._pending_handle = None
        self._set_busy(False)
        if not getattr(result, "ok", False) or getattr(result, "value", None) is None:
            self._set_error(getattr(result, "error", None))
            return
        self._state = result.value
        self.message_input.clear()
        self._render_history()
        self._last_error = None
        self.status_label.clear()

    def _set_busy(self, busy: bool) -> None:
        self.send_button.setEnabled(not busy and self._view_model.available)
        self.message_input.setEnabled(not busy and self._view_model.available)
        self.close_button.setEnabled(not busy)

    def accept(self) -> None:
        if self._pending_handle is None:
            super().accept()

    def reject(self) -> None:
        if self._pending_handle is None:
            super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._pending_handle is not None:
            event.ignore()
            return
        super().closeEvent(event)

    def _render_history(self) -> None:
        lines: list[str] = []
        for item in self._state.history:
            role = _("You") if item["role"] == "user" else _("Assistant")
            lines.append(f"{role}: {item['content']}")
        self.transcript.setPlainText("\n\n".join(lines))

    def _set_error(self, error: AppError | None) -> None:
        self._last_error = None if isinstance(error, CancellationError) else error
        self.status_label.setText(display_error_message(error))
