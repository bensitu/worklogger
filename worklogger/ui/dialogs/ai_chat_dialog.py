from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config.themes import switch_off_color, theme_colors
from services.ai_chat_session import AiChatSession
from services.ai_service import AIWorker, LocalModelWorker
from services.local_model_service import LOCAL_MODEL_SENTINEL
from ui.widgets import SwitchButton
from utils.formatters import parse_status
from utils.i18n import _, msg


class AiChatDialog(QDialog):
    """Workflow-scoped AI refinement dialog."""

    def __init__(
        self,
        parent,
        app_ref,
        session: AiChatSession,
        period_label: str,
        context_builder: Callable[..., str],
        on_apply: Callable[[str], None],
        api_key: str,
        base_url: str,
        model: str,
        token_budget: int | None = None,
        initial_user_message: str = "",
        initial_display_message: str = "",
        initial_assistant_message: str = "",
        apply_button_text: str | None = None,
        mode: str = "generic",
        auto_start_initial: bool = False,
    ):
        super().__init__(parent)
        self._app = app_ref
        self._session = session
        self._period_label = period_label
        self._context_builder = context_builder
        self._on_apply = on_apply
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._token_budget = token_budget
        self._mode = mode
        self._worker = None
        self._busy = False
        self._pending_user_message = ""
        self._request_serial = 0
        self._latest_successful_text = session.last_assistant_message() or ""

        self.setWindowTitle(_("✨ AI Assist"))
        self.setMinimumSize(720, 560)
        self.resize(860, 660)

        root = QVBoxLayout(self)
        root.setSpacing(8)

        header = QLabel(_("✨ AI Assist - {}").format(period_label))
        header.setObjectName("section_title")
        header.setWordWrap(True)
        root.addWidget(header)

        runtime_text = _("Runtime: Local model") if api_key == LOCAL_MODEL_SENTINEL else _("Runtime: External API")
        self._runtime_label = QLabel(runtime_text)
        self._runtime_label.setWordWrap(True)
        root.addWidget(self._runtime_label)

        if api_key != LOCAL_MODEL_SENTINEL:
            privacy = QLabel(
                _(
                    "Selected context may be sent to the configured external AI provider."
                )
            )
            privacy.setObjectName("muted")
            privacy.setWordWrap(True)
            root.addWidget(privacy)

        options = QHBoxLayout()
        options.setSpacing(10)
        switch_on = theme_colors(
            getattr(app_ref, "theme", "blue"),
            bool(getattr(app_ref, "dark", False)),
        )[0]
        switch_off = switch_off_color(bool(getattr(app_ref, "dark", False)))
        self._include_notes, notes_row = self._switch_with_label(
            _("Include notes"),
            True,
            switch_on,
            switch_off,
        )
        self._include_calendar, calendar_row = self._switch_with_label(
            _("Include calendar events"),
            True,
            switch_on,
            switch_off,
        )
        self._include_calendar_titles, titles_row = self._switch_with_label(
            _("Include calendar event titles"),
            True,
            switch_on,
            switch_off,
        )
        self._include_quick_logs, quick_row = self._switch_with_label(
            _("Include quick log details"),
            True,
            switch_on,
            switch_off,
        )
        for row in (notes_row, calendar_row, titles_row, quick_row):
            options.addWidget(row)
        options.addStretch()
        root.addLayout(options)

        self._history = QTextEdit()
        self._history.setReadOnly(True)
        root.addWidget(self._history, 1)

        self._status = QLabel(_("Ready"))
        self._status.setObjectName("muted")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        self._input = QTextEdit()
        self._input.setPlaceholderText(_("Follow up on this result..."))
        self._input.setFixedHeight(92)
        self._input.installEventFilter(self)
        root.addWidget(self._input)

        hint = QLabel(_("Ctrl+Enter to send"))
        hint.setObjectName("muted")
        root.addWidget(hint)

        buttons = QHBoxLayout()
        self._clear_btn = QPushButton(_("Clear conversation"))
        self._apply_btn = QPushButton(apply_button_text or _("Apply"))
        self._close_btn = QPushButton(_("Close"))
        self._send_btn = QPushButton(_("Send"))
        self._apply_btn.setObjectName("primary_btn")
        self._send_btn.setObjectName("primary_btn")
        buttons.addWidget(self._clear_btn)
        buttons.addStretch()
        buttons.addWidget(self._apply_btn)
        buttons.addWidget(self._close_btn)
        buttons.addWidget(self._send_btn)
        root.addLayout(buttons)

        self._clear_btn.clicked.connect(self._clear)
        self._apply_btn.clicked.connect(self._apply_latest)
        self._close_btn.clicked.connect(self.reject)
        self._send_btn.clicked.connect(self._send)
        self._sync_buttons()
        if initial_user_message and auto_start_initial and not initial_assistant_message:
            QTimer.singleShot(
                0,
                lambda: self._start_request(
                    initial_display_message or self._period_label,
                    initial_user_message,
                ),
            )
        elif initial_user_message or initial_assistant_message:
            self.prefill_first_turn(initial_user_message, initial_assistant_message)

    @staticmethod
    def _switch_with_label(
        text: str,
        checked: bool,
        color_on: str,
        color_off: str,
    ) -> tuple[SwitchButton, QWidget]:
        wrap = QWidget()
        wrap.setObjectName("transparent_container")
        wrap.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        wrap.setStyleSheet(
            "QWidget#transparent_container{background:transparent;"
            "background-color:transparent;border:none;}"
            "QWidget#transparent_container QLabel#ai_switch_label{"
            "background:transparent;background-color:transparent;"
            "border:none;padding:0px;}"
        )
        layout = QHBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        switch = SwitchButton(
            checked=checked,
            color_on=color_on,
            color_off=color_off,
        )
        label = QLabel(text)
        label.setObjectName("ai_switch_label")
        label.setBuddy(switch)
        label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        layout.addWidget(switch)
        layout.addWidget(label)
        return switch, wrap

    def prefill_first_turn(self, user_text: str, assistant_text: str) -> None:
        if user_text:
            self._append_message(_("You"), user_text)
        if assistant_text:
            text = assistant_text.strip() or _("No response.")
            self._latest_successful_text = text
            self._append_message(_("AI"), text)
        self._sync_buttons()

    def eventFilter(self, obj, event):
        if obj is self._input and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    self._send()
                    return True
        return super().eventFilter(obj, event)

    def reject(self):
        self._cancel_worker()
        super().reject()

    def closeEvent(self, event):
        self._cancel_worker()
        event.accept()

    def _sync_buttons(self) -> None:
        self._apply_btn.setEnabled((not self._busy) and bool(self._latest_successful_text))

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        enabled = not busy
        for widget in (
            self._include_notes,
            self._include_calendar,
            self._include_calendar_titles,
            self._include_quick_logs,
            self._input,
            self._clear_btn,
            self._send_btn,
        ):
            widget.setEnabled(enabled)
        self._close_btn.setEnabled(True)
        self._sync_buttons()

    def _clear(self) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(_("AI Assist"))
        box.setText(_("Clear this conversation?"))
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        self._session.reset()
        self._history.clear()
        self._latest_successful_text = ""
        self._status.setText(_("Conversation cleared."))
        self._sync_buttons()

    def _cancel_worker(self) -> None:
        worker = self._worker
        was_busy = self._busy
        self._request_serial += 1
        if worker is not None and hasattr(worker, "cancel"):
            try:
                worker.cancel()
            except Exception:
                pass
        self._worker = None
        self._pending_user_message = ""
        if was_busy:
            self._status.setText(_("Request canceled."))
        self._set_busy(False)

    def _apply_latest(self) -> None:
        text = self._latest_successful_text
        if not text:
            return
        try:
            self._on_apply(text)
        except Exception as exc:
            QMessageBox.critical(self, _("AI Assist"), str(exc))
            return
        self.accept()

    def _send(self) -> None:
        user_text = self._input.toPlainText().strip()
        if not user_text:
            return
        if self._api_key != LOCAL_MODEL_SENTINEL and (
            not self._api_key or not self._base_url or not self._model
        ):
            QMessageBox.warning(
                self,
                _("AI Assist"),
                _("Please configure an AI provider in Settings -> AI."),
            )
            return

        self._status.setText(_("Building context..."))
        try:
            context = self._build_context()
        except Exception as exc:
            self._set_busy(False)
            QMessageBox.critical(self, _("AI Assist"), str(exc))
            return

        payload = (
            f"{context}\n\n"
            f"## Follow-up request\n{user_text}\n\n"
            "Revise or answer using the current WorkLogger context and prior conversation."
        )
        self._start_request(user_text, payload)

    def _start_request(self, display_user_text: str, payload: str) -> None:
        if self._busy:
            return
        if self._api_key != LOCAL_MODEL_SENTINEL and (
            not self._api_key or not self._base_url or not self._model
        ):
            QMessageBox.warning(
                self,
                _("AI Assist"),
                _("Please configure an AI provider in Settings -> AI."),
            )
            return

        self._set_busy(True)
        messages = self._session.get_messages(
            additional_messages=[{"role": "user", "content": payload}],
            token_budget=self._token_budget,
        )
        self._pending_user_message = payload
        self._input.clear()
        self._append_message(_("You"), display_user_text)
        self._status.setText(_("Sending request..."))
        self._request_serial += 1
        request_id = self._request_serial

        def on_status(raw: str) -> None:
            if request_id != self._request_serial:
                return
            key, kwargs = parse_status(raw)
            if key:
                self._status.setText(msg(key, **kwargs))
            else:
                self._status.setText(kwargs.get("raw", raw))

        def on_done(text: str) -> None:
            if request_id != self._request_serial:
                return
            text = text.strip() or _("No response.")
            pending = self._pending_user_message
            if pending:
                self._session.add_user_message(pending)
            self._session.add_assistant_message(text)
            self._pending_user_message = ""
            self._latest_successful_text = text
            self._append_message(_("AI"), text)
            self._status.setText(_("Done"))
            self._worker = None
            self._set_busy(False)

        def on_error(short: str, detail: str) -> None:
            if request_id != self._request_serial:
                return
            self._pending_user_message = ""
            friendly = msg(short, short)
            if detail:
                friendly = f"{friendly}\n{detail}"
            self._status.setText(_("Error: {detail}").format(detail=friendly))
            self._worker = None
            self._set_busy(False)

        if self._api_key == LOCAL_MODEL_SENTINEL:
            self._worker = LocalModelWorker(
                messages,
                on_done,
                on_error,
                services=self._app.services,
                max_tokens=4096,
                temperature=0.3,
                on_status=on_status,
            )
        else:
            self._worker = AIWorker(
                self._api_key,
                self._base_url,
                self._model,
                messages,
                on_done,
                on_error,
                max_tokens=2048,
                on_status=on_status,
            )

    def _build_context(self) -> str:
        kwargs = {
            "include_notes": self._include_notes.isChecked(),
            "include_calendar": self._include_calendar.isChecked(),
            "include_calendar_titles": self._include_calendar_titles.isChecked(),
            "include_quick_log_details": self._include_quick_logs.isChecked(),
        }
        try:
            return self._context_builder(**kwargs)
        except TypeError:
            return self._context_builder()

    def _append_message(self, sender: str, content: str) -> None:
        safe_sender = self._escape(sender)
        safe_content = self._escape(content).replace("\n", "<br>")
        self._history.append(f"<b>[{safe_sender}]</b><br>{safe_content}<br>")
        scroll = self._history.verticalScrollBar()
        scroll.setValue(scroll.maximum())

    @staticmethod
    def _escape(value: str) -> str:
        return (
            str(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
