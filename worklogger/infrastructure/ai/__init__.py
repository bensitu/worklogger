"""AI infrastructure adapters."""

from worklogger.infrastructure.ai.external import OpenAICompatibleGateway
from worklogger.infrastructure.ai.local import LocalModelGateway, strip_thinking
from worklogger.infrastructure.ai.router import RoutingAIGateway

__all__ = [
    "LocalModelGateway",
    "OpenAICompatibleGateway",
    "RoutingAIGateway",
    "strip_thinking",
]
