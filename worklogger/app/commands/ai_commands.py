"""AI command DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class RewriteTextCommand:
    user_id: int
    content: str
    context: str = "note"
    # Interface locale, independent of the source or requested output language.
    language: str = "en_US"
    instructions: str = ""
    output_language: str = ""


@dataclass(frozen=True)
class SendAiChatMessageCommand:
    user_id: int
    message: str
    history: tuple[Mapping[str, str], ...] = ()
    context: str = ""
    # Interface locale, independent of the source or requested output language.
    language: str = "en_US"
    output_language: str = ""
