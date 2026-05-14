"""AI command DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class RewriteTextCommand:
    user_id: int
    content: str
    context: str = "note"
    language: str = "en_US"


@dataclass(frozen=True)
class SendAiChatMessageCommand:
    user_id: int
    message: str
    history: tuple[Mapping[str, str], ...] = ()
    context: str = ""
    language: str = "en_US"
