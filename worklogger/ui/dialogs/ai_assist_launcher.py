from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from PySide6.QtWidgets import QMessageBox

from services.ai_chat_session import AiChatSession
from services.ai_context_service import AiContextService
from services.local_model_service import LOCAL_MODEL_SENTINEL
from utils.i18n import _

from .ai_chat_dialog import AiChatDialog
from .common import _get_ai_params


@dataclass(frozen=True)
class AiAssistLaunchConfig:
    period_type: str
    period_label: str
    existing_text: str = ""
    hint: str = ""
    apply_button_text: str | None = None
    use_secondary_ai: bool = False
    analytics_kwargs: dict = field(default_factory=dict)


def get_local_chat_token_budget(services) -> int | None:
    """Return a conservative local-model prompt budget when catalog data exists."""
    try:
        from services.local_model_service import get_active_entry_id, get_catalog_entry

        entry_id = get_active_entry_id()
        entry = get_catalog_entry(entry_id)
        n_ctx = int(entry.get("n_ctx", 0) or 0)
        max_tokens = int(entry.get("max_tokens", 0) or 0)
        if n_ctx > 0:
            output_headroom = max(max_tokens or 2048, 1024)
            return max(1024, n_ctx - output_headroom - 256)
    except Exception:
        pass
    return None


def launch_ai_assist(
    parent,
    app_ref,
    config: AiAssistLaunchConfig,
    on_apply: Callable[[str], None],
) -> None:
    context_service = AiContextService(app_ref.services)
    api_key, base_url, model = _get_ai_params(
        app_ref,
        secondary=config.use_secondary_ai,
    )
    if api_key != LOCAL_MODEL_SENTINEL and (not api_key or not base_url or not model):
        QMessageBox.warning(
            parent,
            _("AI Assist"),
            _("Please configure an AI provider in Settings -> AI."),
        )
        return

    context_builder = _build_context_builder(app_ref, context_service, config)
    try:
        initial_context = context_builder()
    except Exception as exc:
        QMessageBox.critical(parent, _("AI Assist"), str(exc))
        return

    system_prompt = _system_prompt_for(config.period_type)
    initial_user_message = _initial_user_message(config, initial_context)
    token_budget = (
        get_local_chat_token_budget(app_ref.services)
        if api_key == LOCAL_MODEL_SENTINEL
        else None
    )

    session = AiChatSession(
        system_prompt,
        max_messages=20,
        token_budget=token_budget,
    )
    dialog = AiChatDialog(
        parent,
        app_ref,
        session,
        config.period_label,
        context_builder,
        on_apply,
        api_key,
        base_url,
        model,
        token_budget=token_budget,
        initial_user_message=initial_user_message,
        initial_display_message=_initial_display_message(config),
        apply_button_text=config.apply_button_text,
        mode=config.period_type,
        auto_start_initial=True,
    )
    dialog.exec()


def _build_context_builder(app_ref, context_service: AiContextService, config: AiAssistLaunchConfig):
    if config.period_type == "daily":
        return lambda **kwargs: context_service.build_daily_context(
            app_ref.selected,
            **kwargs,
        )
    if config.period_type == "weekly":
        return lambda **kwargs: context_service.build_weekly_context(
            app_ref.selected,
            **kwargs,
        )
    if config.period_type == "monthly":
        return lambda **kwargs: context_service.build_monthly_context(
            app_ref.selected.year,
            app_ref.selected.month,
            **kwargs,
        )
    if config.period_type == "analytics":
        return lambda **_kwargs: context_service.build_analytics_context(
            **config.analytics_kwargs,
        )
    raise ValueError("unsupported_ai_assist_period_type")


def _system_prompt_for(period_type: str) -> str:
    if period_type == "daily":
        return (
            "You are a careful WorkLogger daily-notes assistant. Generate or "
            "revise concise, factual daily notes from the provided context. "
            "Keep the user's language and do not invent facts."
        )
    if period_type in {"weekly", "monthly"}:
        return (
            "You are a careful WorkLogger report assistant. Generate or revise "
            "a structured Markdown work report from the provided context. Keep "
            "the user's language and do not invent facts."
        )
    if period_type == "analytics":
        return (
            "You are a careful WorkLogger analytics assistant. Write a concise "
            "PDF-ready narrative from the provided chart data. Mention only "
            "observable trends and do not invent reasons."
        )
    return (
        "You are a careful WorkLogger assistant. Use only the provided context "
        "and do not invent facts."
    )


def _initial_user_message(config: AiAssistLaunchConfig, context: str) -> str:
    lines = [
        f"# Request: {config.period_label}",
        "",
        "## WorkLogger Context",
        context.strip(),
    ]
    existing = config.existing_text.strip()
    if existing:
        lines.extend(["", "## Existing Draft", existing])
    hint = config.hint.strip()
    if hint:
        lines.extend(["", "## User Instructions", hint])
    lines.extend([
        "",
        "## Output Requirements",
        "- Use the same language as the existing draft or context.",
        "- Keep the result ready to apply without extra explanation.",
        "- Do not invent tasks, hours, causes, or external facts.",
    ])
    return "\n".join(lines).strip()


def _initial_display_message(config: AiAssistLaunchConfig) -> str:
    lines = [
        _("Request: {period}").format(period=config.period_label),
        (
            _("Source: existing draft and selected WorkLogger context")
            if config.existing_text.strip()
            else _("Source: selected WorkLogger context")
        ),
    ]
    hint = config.hint.strip()
    if hint:
        lines.extend(["", _("Extra instructions:"), hint])
    return "\n".join(lines).strip()
