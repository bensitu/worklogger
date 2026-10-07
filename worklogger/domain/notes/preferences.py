"""Per-date sharing choices and storage identifiers for daily notes."""

from dataclasses import dataclass
from datetime import date
import json


@dataclass(frozen=True)
class NoteSharing:
    reports: bool = False
    ai: bool = False

    def encode(self) -> str:
        return json.dumps({"reports": self.reports, "ai": self.ai})

    @classmethod
    def decode(cls, value: str | None):
        try:
            data = json.loads(value or "{}")
            return cls(data.get("reports") is True, data.get("ai") is True)
        except (ValueError, TypeError, AttributeError):
            return cls()


def note_sharing_key(day: date) -> str:
    return f"daily_note_sharing:{day.isoformat()}"


def note_draft_key(day: date) -> str:
    return f"daily_note_draft:{day.isoformat()}"
