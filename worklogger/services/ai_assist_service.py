"""AI assist request construction and prompt policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable

from services.ai_chat_session import AiChatSession
from services.ai_context_service import AiContextService
from services.local_model_service import LOCAL_MODEL_SENTINEL
from utils.i18n import _, LANG_NAMES


@dataclass(frozen=True)
class AiAssistLaunchConfig:
    period_type: str
    period_label: str
    existing_text: str = ""
    hint: str = ""
    apply_button_text: str | None = None
    use_secondary_ai: bool = False
    analytics_kwargs: dict = field(default_factory=dict)


@dataclass(frozen=True)
class AiAssistRequest:
    session: AiChatSession
    context_builder: Callable[..., str]
    api_key: str
    base_url: str
    model: str
    token_budget: int | None
    initial_user_message: str
    initial_display_message: str
    target_language: str
    external_provider_required: bool


def build_ai_assist_request(
    services,
    *,
    lang: str,
    selected_date: date,
    current_year: int,
    current_month: int,
    config: AiAssistLaunchConfig,
) -> AiAssistRequest:
    """Build the complete non-UI request model for an AI assist dialog."""
    context_service = AiContextService(services)
    api_key, base_url, model = services.resolve_ai_params(
        secondary=config.use_secondary_ai,
    )
    context_builder = build_context_builder(
        context_service,
        selected_date=selected_date,
        current_year=current_year,
        current_month=current_month,
        config=config,
    )
    initial_context = context_builder()
    target_language = target_output_language(lang, services)
    token_budget = (
        get_local_chat_token_budget(services)
        if api_key == LOCAL_MODEL_SENTINEL
        else None
    )
    session = AiChatSession(
        system_prompt_for(config.period_type, target_language),
        max_messages=20,
        token_budget=token_budget,
    )
    return AiAssistRequest(
        session=session,
        context_builder=context_builder,
        api_key=api_key,
        base_url=base_url,
        model=model,
        token_budget=token_budget,
        initial_user_message=initial_user_message(
            config,
            initial_context,
            target_language,
        ),
        initial_display_message=initial_display_message(config),
        target_language=target_language,
        external_provider_required=(
            api_key != LOCAL_MODEL_SENTINEL
            and (not api_key or not base_url or not model)
        ),
    )


def get_local_chat_token_budget(services) -> int | None:
    """Return a conservative local-model prompt budget when catalog data exists."""
    try:
        from services.local_model_service import (
            get_active_entry_id,
            get_catalog_entry,
            runtime_context_length_for_entry,
            runtime_max_output_tokens_for_entry,
        )

        entry_id = get_active_entry_id(services=services)
        entry = get_catalog_entry(entry_id)
        n_ctx = runtime_context_length_for_entry(entry)
        max_tokens = runtime_max_output_tokens_for_entry(entry)
        if n_ctx > 0:
            output_headroom = max(max_tokens or 2048, 1024)
            return max(1024, n_ctx - output_headroom - 256)
    except Exception:
        pass
    return None


def target_output_language(lang: str, services=None) -> str:
    code = str(lang or "").strip()
    if not code and services is not None:
        try:
            code = str(services.get_setting("lang", "en_US") or "en_US")
        except Exception:
            code = "en_US"
    return LANG_NAMES.get(code, code or "English")


def build_context_builder(
    context_service: AiContextService,
    *,
    selected_date: date,
    current_year: int,
    current_month: int,
    config: AiAssistLaunchConfig,
):
    if config.period_type == "daily":
        return lambda **kwargs: context_service.build_daily_context(
            selected_date,
            **kwargs,
        )
    if config.period_type == "weekly":
        return lambda **kwargs: context_service.build_weekly_context(
            selected_date,
            **kwargs,
        )
    if config.period_type == "monthly":
        return lambda **kwargs: context_service.build_monthly_context(
            current_year,
            current_month,
            **kwargs,
        )
    if config.period_type == "analytics":
        return lambda **_kwargs: context_service.build_analytics_context(
            **config.analytics_kwargs,
        )
    raise ValueError("unsupported_ai_assist_period_type")


def system_prompt_for(period_type: str, target_language: str) -> str:
    if period_type == "daily":
        return (
            "You are a WorkLogger daily-notes assistant. Generate or polish a "
            "single day's work note so it is concise, factual, and ready to "
            "save in the app. Prefer short paragraphs or compact bullets over "
            "a formal report. Preserve useful wording from an existing draft, "
            f"write the final result in {target_language}, and do not invent "
            "tasks, hours, causes, or external facts."
        )
    if period_type == "weekly":
        return (
            "You are a WorkLogger weekly-report assistant. Generate or polish "
            "a structured Markdown weekly work report from the provided records, "
            "quick logs, and allowed calendar context. Emphasize progress, "
            "notable outcomes, blockers, follow-ups, and next-week actions. "
            f"Write the final result in {target_language}; do not invent "
            "unrecorded work, reasons, hours, or commitments."
        )
    if period_type == "monthly":
        return (
            "You are a WorkLogger monthly-report assistant. Generate or polish "
            "a structured Markdown monthly work report that summarizes major "
            "themes, deliverables, workload patterns, leave/overtime signals "
            "when present, risks, and next-month focus. Keep it executive-ready "
            f"but grounded in the data. Write the final result in {target_language}; "
            "do not invent missing projects, causes, hours, or business context."
        )
    if period_type == "analytics":
        return (
            "You are a WorkLogger analytics PDF assistant. Write a concise, "
            "PDF-ready narrative from the provided chart data. Explain observable "
            "trends, workload changes, target gaps, leave signals, and sparse-data "
            "limitations when they are present. The output must fit into a report "
            f"PDF and be written in {target_language}. Do not invent causes, "
            "business reasons, or data points."
        )
    return (
        "You are a careful WorkLogger assistant. Use only the provided context, "
        f"write the final result in {target_language}, and do not invent facts."
    )


def initial_user_message(
    config: AiAssistLaunchConfig,
    context: str,
    target_language: str,
) -> str:
    lines = [
        f"# Request: {config.period_label}",
        "",
        "## Target Output Language",
        target_language,
        "",
        "## WorkLogger Context",
        context.strip(),
    ]
    existing = config.existing_text.strip()
    if existing:
        lines.extend(["", "## Existing Draft To Polish", existing])
    hint = config.hint.strip()
    if hint:
        lines.extend(["", "## User Instructions", hint])
    lines.extend(["", "## Output Requirements"])
    lines.extend(output_requirements_for(config.period_type, target_language))
    return "\n".join(lines).strip()


def output_requirements_for(period_type: str, target_language: str) -> list[str]:
    common = [
        f"- Write the final result in {target_language}, matching the software's selected language.",
        "- Return only the content to apply; no preface, no code fence, no explanation of your process.",
        "- Use only the provided WorkLogger context and existing draft.",
        "- Do not invent tasks, hours, causes, meetings, decisions, or external facts.",
    ]
    if period_type == "daily":
        return [
            *common,
            "- Produce a polished daily note, not a weekly or monthly report.",
            "- Keep it concise and readable for a work diary.",
            "- Merge quick logs into the note when they add useful detail.",
            "- If an existing draft is provided, improve clarity and structure without changing facts.",
        ]
    if period_type == "weekly":
        return [
            *common,
            "- Produce a Markdown weekly report with practical section headings.",
            "- Summarize progress across the week, then list blockers, follow-ups, and next actions when supported by data.",
            "- Avoid day-by-day repetition unless it improves traceability.",
        ]
    if period_type == "monthly":
        return [
            *common,
            "- Produce a Markdown monthly report with an executive summary and practical section headings.",
            "- Aggregate recurring work into themes and mention workload, leave, or overtime patterns only when present in the data.",
            "- Close with next-month focus items only when they are supported by the context or draft.",
        ]
    if period_type == "analytics":
        return [
            *common,
            "- Produce PDF-ready analytics narrative with concise headings and bullets.",
            "- Mention visible trends, target gaps, leave signals, and sparse-data limitations only when supported by chart data.",
            "- Keep it short enough to fit inside an exported analytics PDF.",
        ]
    return common


def initial_display_message(config: AiAssistLaunchConfig) -> str:
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


def build_followup_payload(context: str, user_text: str) -> str:
    return (
        f"{context}\n\n"
        f"## Follow-up request\n{user_text}\n\n"
        "Revise or answer using the current WorkLogger context and prior conversation."
    )
