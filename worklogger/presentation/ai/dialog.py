"""AI Assist chat dialog."""

from __future__ import annotations

from datetime import date

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

from worklogger.domain.shared.errors import AppError
from worklogger.infrastructure.i18n import _
from worklogger.presentation.viewmodels import AiAssistViewModel, AiChatState


class AiAssistDialog(QDialog):
    def __init__(
        self,
        view_model: AiAssistViewModel,
        selected_day: date,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._view_model = view_model
        self._selected_day = selected_day
        self._state = view_model.initial_state()
        self._last_error: AppError | None = None
        self.setObjectName("ai_assist_dialog")
        self.setWindowTitle(_("AI Assist"))
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
        self.status_label = QLabel("")
        self.close_button = QPushButton(_("Close"))
        bottom.addWidget(self.status_label, 1)
        bottom.addWidget(self.close_button)
        root.addLayout(bottom)

        self.send_button.clicked.connect(self.send_current_message)
        self.message_input.returnPressed.connect(self.send_current_message)
        self.close_button.clicked.connect(self.accept)

    def send_current_message(self) -> bool:
        message = self.message_input.text()
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
        self.status_label.setText(_("Ready"))
        return True

    def _render_history(self) -> None:
        lines: list[str] = []
        for item in self._state.history:
            role = _("You") if item["role"] == "user" else _("Assistant")
            lines.append(f"{role}: {item['content']}")
        self.transcript.setPlainText("\n\n".join(lines))

    def _set_error(self, error: AppError | None) -> None:
        self._last_error = error
        self.status_label.setText(error.message if error is not None else _("Unknown error"))
