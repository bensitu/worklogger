from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QMessageBox

from services.ai_assist_service import (
    AiAssistLaunchConfig,
    build_ai_assist_request,
)
from utils.i18n import _

from .ai_chat_dialog import AiChatDialog


def launch_ai_assist(
    parent,
    app_ref,
    config: AiAssistLaunchConfig,
    on_apply: Callable[[str], None],
) -> None:
    try:
        request = build_ai_assist_request(
            app_ref.services,
            lang=app_ref.lang,
            selected_date=app_ref.selected,
            current_year=app_ref.current.year,
            current_month=app_ref.current.month,
            config=config,
        )
    except Exception as exc:
        QMessageBox.critical(parent, _("AI Assist"), str(exc))
        return

    if request.external_provider_required:
        QMessageBox.warning(
            parent,
            _("AI Assist"),
            _(
                "Please enable a local model in Settings -> AI, or configure "
                "an external AI provider with API key, base URL, and model name."
            ),
        )
        return

    dialog = AiChatDialog(
        parent,
        app_ref,
        request.session,
        config.period_label,
        request.context_builder,
        on_apply,
        request.api_key,
        request.base_url,
        request.model,
        token_budget=request.token_budget,
        initial_user_message=request.initial_user_message,
        initial_display_message=request.initial_display_message,
        apply_button_text=config.apply_button_text,
        mode=config.period_type,
        auto_start_initial=True,
    )
    dialog.exec()
