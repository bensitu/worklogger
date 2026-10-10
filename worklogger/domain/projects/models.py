"""Optional work context with stable identifiers and historical labels."""

from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID


def validate_identifier(value: str) -> None:
    try:
        if not isinstance(value, str) or UUID(value).hex != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ValueError("work_context_invalid") from None


def validate_text(value: str, maximum: int, *, required=False) -> None:
    if (not isinstance(value, str) or len(value) > maximum
            or (required and not value.strip()) or any(ord(char) < 32 for char in value)):
        raise ValueError("work_context_invalid")


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    code: str = ""
    revision: int = 0
    archived: bool = False

    def __post_init__(self):
        validate_identifier(self.id)
        validate_text(self.name, 120, required=True)
        validate_text(self.code, 40)
        if type(self.revision) is not int or self.revision < 0:
            raise ValueError("work_context_invalid")


@dataclass(frozen=True)
class WorkItem:
    id: str
    project_id: str
    title: str
    source_url: str = ""
    completed: bool = False
    revision: int = 0
    archived: bool = False

    def __post_init__(self):
        validate_identifier(self.id)
        validate_identifier(self.project_id)
        validate_text(self.title, 240, required=True)
        validate_text(self.source_url, 2048)
        if self.source_url:
            try:
                url = urlsplit(self.source_url)
                if url.scheme not in {"https", "http"} or not url.hostname or url.username or url.password:
                    raise ValueError
                url.port
            except ValueError:
                raise ValueError("work_item_url_invalid") from None
        if type(self.revision) is not int or self.revision < 0:
            raise ValueError("work_context_invalid")


@dataclass(frozen=True)
class WorkContext:
    project_id: str | None = None
    work_item_id: str | None = None
    project_label: str = ""
    work_item_label: str = ""

    def __post_init__(self):
        if self.project_id is not None:
            validate_identifier(self.project_id)
        if self.work_item_id is not None:
            validate_identifier(self.work_item_id)
            if self.project_id is None:
                raise ValueError("work_context_invalid")
        validate_text(self.project_label, 120)
        validate_text(self.work_item_label, 240)
        if self.work_item_label and not self.project_label:
            raise ValueError("work_context_invalid")

    @property
    def label(self) -> str:
        return " / ".join(value for value in (self.project_label, self.work_item_label) if value)
