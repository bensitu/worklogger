"""AI gateway routing helpers."""

from __future__ import annotations

from worklogger.app.ports import AIGateway, AIRequest, AIResponse
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result


class RoutingAIGateway:
    def __init__(
        self,
        *,
        primary: AIGateway,
        secondary: AIGateway | None = None,
        secondary_falls_back_to_primary: bool = True,
    ) -> None:
        self._primary = primary
        self._secondary = secondary
        self._secondary_falls_back_to_primary = secondary_falls_back_to_primary

    def generate(self, request: AIRequest) -> Result[AIResponse]:
        route, model = _route_and_model(request.model)
        routed_request = AIRequest(
            messages=request.messages,
            model=model,
            timeout_seconds=request.timeout_seconds,
        )
        if route == "secondary":
            if self._secondary is not None:
                return self._secondary.generate(routed_request)
            if not self._secondary_falls_back_to_primary:
                return Result.failure(
                    InfrastructureError(
                        "ai_secondary_not_configured",
                        "ai_secondary_not_configured",
                    )
                )
        return self._primary.generate(routed_request)


def _route_and_model(model: str) -> tuple[str, str]:
    text = str(model or "").strip()
    if text.startswith("secondary:"):
        routed = text.split(":", 1)[1].strip()
        return "secondary", routed or text
    if text.startswith("primary:"):
        routed = text.split(":", 1)[1].strip()
        return "primary", routed or text
    return "primary", text
