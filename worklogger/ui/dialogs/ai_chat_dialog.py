from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config.constants import (
    AI_INCLUDE_CALENDAR_TITLES_SETTING_KEY,
    AI_INCLUDE_NOTES_SETTING_KEY,
    AI_INCLUDE_QUICK_LOG_DETAILS_SETTING_KEY,
    AI_PRIVACY_MODE_SETTING_KEY,
)
from config.themes import switch_off_color, theme_colors
from services.ai_chat_session import AiChatSession
from services.ai_context_service import AiContextService
from services.ai_service import AIWorker, LocalModelWorker
from services.local_model_service import LOCAL_MODEL_SENTINEL
from ui.widgets import SwitchButton
from utils.formatters import parse_status
from utils.i18n import _, msg


class AiChatDialog(QDialog):
    def __init__(self, app_ref, parent=None):
        super().__init__(parent)
        self._app = app_ref
        self._context_service = AiContextService(app_ref.services)
        self._session = AiChatSession(
            self._system_prompt(),
            max_messages=20,
        )
        self._worker = None
        self._pending_user_message = ""

        self.setWindowTitle(_("AI Chat"))
        self.setMinimumSize(720, 560)
        self.resize(820, 640)

        root = QVBoxLayout(self)
        root.setSpacing(8)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self._period = QComboBox()
        self._period.addItem(_("Current day"), "day")
        self._period.addItem(_("Current week"), "week")
        self._period.addItem(_("Current month"), "month")
        controls.addWidget(QLabel(_("Context")))
        controls.addWidget(self._period)

        self._privacy = QComboBox()
        self._privacy.addItem(_("Local AI only"), "local_only")
        self._privacy.addItem(_("Remote AI allowed"), "remote_allowed")
        self._privacy.addItem(_("AI disabled"), "disabled")
        saved_privacy = app_ref.services.get_setting(
            AI_PRIVACY_MODE_SETTING_KEY,
            "local_only",
        )
        privacy_idx = self._privacy.findData(saved_privacy)
        if privacy_idx >= 0:
            self._privacy.setCurrentIndex(privacy_idx)
        controls.addWidget(QLabel(_("AI mode")))
        controls.addWidget(self._privacy)
        controls.addStretch()
        root.addLayout(controls)

        flags = QHBoxLayout()
        flags.setSpacing(8)
        switch_on = theme_colors(app_ref.theme, app_ref.dark)[0]
        switch_off = switch_off_color(app_ref.dark)

        def _switch_with_label(text: str, checked: bool) -> tuple[SwitchButton, QWidget]:
            wrap = QWidget()
            layout = QHBoxLayout(wrap)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(6)
            switch = SwitchButton(
                checked=checked,
                color_on=switch_on,
                color_off=switch_off,
            )
            label = QLabel(text)
            label.setBuddy(switch)
            layout.addWidget(switch)
            layout.addWidget(label)
            return switch, wrap

        self._include_notes, include_notes_row = _switch_with_label(
            _("Include notes"),
            app_ref.services.get_setting(
                AI_INCLUDE_NOTES_SETTING_KEY,
                "0",
            ) == "1"
        )
        self._include_calendar, include_calendar_row = _switch_with_label(
            _("Include calendar events"),
            True,
        )
        self._include_calendar_titles, include_calendar_titles_row = _switch_with_label(
            _("Include calendar titles"),
            app_ref.services.get_setting(
                AI_INCLUDE_CALENDAR_TITLES_SETTING_KEY,
                "0",
            ) == "1"
        )
        self._include_quick_logs, include_quick_logs_row = _switch_with_label(
            _("Include quick log details"),
            app_ref.services.get_setting(
                AI_INCLUDE_QUICK_LOG_DETAILS_SETTING_KEY,
                "1",
            ) == "1"
        )
        for widget in (
            include_notes_row,
            include_calendar_row,
            include_calendar_titles_row,
            include_quick_logs_row,
        ):
            flags.addWidget(widget)
        flags.addStretch()
        root.addLayout(flags)

        self._history = QTextEdit()
        self._history.setReadOnly(True)
        root.addWidget(self._history, 1)

        self._input = QTextEdit()
        self._input.setPlaceholderText(_("Ask about the selected work context..."))
        self._input.setFixedHeight(92)
        root.addWidget(self._input)

        self._status = QLabel(_("Ready"))
        self._status.setObjectName("muted")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        buttons = QHBoxLayout()
        self._clear_btn = QPushButton(_("Clear conversation"))
        self._cancel_btn = QPushButton(_("Cancel request"))
        self._send_btn = QPushButton(_("Send"))
        self._send_btn.setObjectName("primary_btn")
        self._close_btn = QPushButton(_("Close"))
        buttons.addWidget(self._clear_btn)
        buttons.addWidget(self._cancel_btn)
        buttons.addStretch()
        buttons.addWidget(self._close_btn)
        buttons.addWidget(self._send_btn)
        root.addLayout(buttons)

        self._send_btn.clicked.connect(self._send)
        self._clear_btn.clicked.connect(self._clear)
        self._cancel_btn.clicked.connect(self._cancel_worker)
        self._close_btn.clicked.connect(self.reject)
        self._cancel_btn.setEnabled(False)

    def reject(self):
        self._cancel_worker()
        super().reject()

    def _system_prompt(self) -> str:
        return (
            "You are WorkLogger's assistant. Use only the provided WorkLogger "
            "context and conversation history. Do not invent work items, notes, "
            "calendar events, times, or reports. If information is missing, say "
            "that it is missing. Keep local AI and remote AI privacy boundaries clear."
        )

    def _set_busy(self, busy: bool) -> None:
        enabled = not busy
        for widget in (
            self._period,
            self._privacy,
            self._include_notes,
            self._include_calendar,
            self._include_calendar_titles,
            self._include_quick_logs,
            self._input,
            self._clear_btn,
            self._close_btn,
            self._send_btn,
        ):
            widget.setEnabled(enabled)
        self._cancel_btn.setEnabled(busy)

    def _clear(self) -> None:
        self._session.clear()
        self._history.clear()
        self._status.setText(_("Conversation cleared."))

    def _cancel_worker(self) -> None:
        worker = self._worker
        was_busy = self._cancel_btn.isEnabled()
        if worker is not None and hasattr(worker, "cancel"):
            try:
                worker.cancel()
            except Exception:
                pass
        self._worker = None
        self._pending_user_message = ""
        self._set_busy(False)
        if was_busy:
            self._status.setText(_("Request canceled."))

    def _send(self) -> None:
        user_text = self._input.toPlainText().strip()
        if not user_text:
            return
        privacy_mode = self._privacy.currentData()
        if privacy_mode == "disabled":
            QMessageBox.warning(self, _("AI Chat"), _("AI is disabled by policy."))
            return
        api_key, base_url, model = self._app.services.resolve_ai_params(secondary=False)
        if privacy_mode == "local_only" and api_key != LOCAL_MODEL_SENTINEL:
            QMessageBox.warning(
                self,
                _("AI Chat"),
                _("Local model is not available. Enable or download a local model in Settings -> AI."),
            )
            return
        if api_key != LOCAL_MODEL_SENTINEL and (not api_key or not base_url or not model):
            QMessageBox.warning(
                self,
                _("AI Chat"),
                _("Please configure an AI provider in Settings -> AI."),
            )
            return

        self._persist_privacy_settings()
        self._set_busy(True)
        self._status.setText(_("Building context..."))
        try:
            context = self._build_context()
        except Exception as exc:
            self._set_busy(False)
            QMessageBox.critical(self, _("AI Chat"), str(exc))
            return

        payload = (
            f"{context}\n\n"
            f"## User Request\n{user_text}\n\n"
            "Answer using the context above and the prior conversation."
        )
        token_budget = self._prompt_token_budget(api_key)
        self._session.set_token_budget(token_budget)
        messages = self._session.get_messages(
            additional_messages=[{"role": "user", "content": payload}],
            token_budget=token_budget,
        )
        self._append_message(_("You"), user_text)
        self._input.clear()
        self._pending_user_message = payload
        self._status.setText(_("Sending request..."))

        def on_status(raw: str) -> None:
            key, kwargs = parse_status(raw)
            if key:
                self._status.setText(msg(key, **kwargs))
            else:
                self._status.setText(kwargs.get("raw", raw))

        def on_done(text: str) -> None:
            text = text.strip() or _("No response.")
            self._session.add_user_message(self._pending_user_message)
            self._session.add_assistant_message(text)
            self._pending_user_message = ""
            self._append_message(_("Assistant"), text)
            self._status.setText(_("Done"))
            self._worker = None
            self._set_busy(False)

        def on_error(short: str, detail: str) -> None:
            self._pending_user_message = ""
            friendly = msg(short, short)
            if detail:
                friendly = f"{friendly}\n{detail}"
            self._status.setText(_("Error: {}").format(friendly))
            self._worker = None
            self._set_busy(False)

        if api_key == LOCAL_MODEL_SENTINEL:
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
                api_key,
                base_url,
                model,
                messages,
                on_done,
                on_error,
                max_tokens=2048,
                on_status=on_status,
            )

    def _build_context(self) -> str:
        period = self._period.currentData()
        include_notes = self._include_notes.isChecked()
        include_calendar = self._include_calendar.isChecked()
        include_calendar_titles = self._include_calendar_titles.isChecked()
        include_quick_logs = self._include_quick_logs.isChecked()
        selected = self._app.selected
        if period == "week":
            return self._context_service.build_weekly_context(
                selected,
                include_notes=include_notes,
                include_calendar=include_calendar,
                include_calendar_titles=include_calendar_titles,
                include_quick_log_details=include_quick_logs,
            )
        if period == "month":
            return self._context_service.build_monthly_context(
                selected.year,
                selected.month,
                include_notes=include_notes,
                include_calendar=include_calendar,
                include_calendar_titles=include_calendar_titles,
                include_quick_log_details=include_quick_logs,
            )
        return self._context_service.build_daily_context(
            selected,
            include_notes=include_notes,
            include_calendar=include_calendar,
            include_calendar_titles=include_calendar_titles,
            include_quick_log_details=include_quick_logs,
        )

    def _persist_privacy_settings(self) -> None:
        services = self._app.services
        services.set_setting(AI_PRIVACY_MODE_SETTING_KEY, self._privacy.currentData())
        services.set_setting(
            AI_INCLUDE_NOTES_SETTING_KEY,
            "1" if self._include_notes.isChecked() else "0",
        )
        services.set_setting(
            AI_INCLUDE_CALENDAR_TITLES_SETTING_KEY,
            "1" if self._include_calendar_titles.isChecked() else "0",
        )
        services.set_setting(
            AI_INCLUDE_QUICK_LOG_DETAILS_SETTING_KEY,
            "1" if self._include_quick_logs.isChecked() else "0",
        )

    def _prompt_token_budget(self, api_key: str) -> int | None:
        if api_key != LOCAL_MODEL_SENTINEL:
            return None
        n_ctx = 4096
        max_tokens = 1024
        try:
            from services.local_model_service import (
                get_active_entry_id,
                get_catalog_entry,
            )
            entry = get_catalog_entry(get_active_entry_id())
            n_ctx = int(entry.get("n_ctx", n_ctx))
            max_tokens = int(entry.get("max_tokens", max_tokens))
        except Exception:
            pass
        return max(512, n_ctx - max_tokens - 256)

    def _append_message(self, sender: str, content: str) -> None:
        safe_sender = sender.replace("<", "&lt;").replace(">", "&gt;")
        safe_content = (
            content.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br>")
        )
        self._history.append(f"<b>{safe_sender}</b><br>{safe_content}<br>")
        scroll = self._history.verticalScrollBar()
        scroll.setValue(scroll.maximum())
