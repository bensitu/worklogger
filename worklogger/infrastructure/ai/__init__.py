"""AI infrastructure adapters."""

from worklogger.infrastructure.ai.external import OpenAICompatibleGateway
from worklogger.infrastructure.ai.local import LocalModelGateway, strip_thinking

__all__ = [
    "LocalModelGateway",
    "OpenAICompatibleGateway",
    "strip_thinking",
]
