"""Account-owned custom work-type catalog."""

from typing import Protocol, TypeVar
from worklogger.domain.worklog.models import CustomEntryType, CustomWorkMode

Definition = TypeVar("Definition", CustomEntryType, CustomWorkMode)


class ClassificationRepository(Protocol[Definition]):
    def list_types(self, user_id: int) -> tuple[Definition, ...]: ...
    def save_type(self, user_id: int, definition: Definition) -> Definition: ...
    def archive_type(self, user_id: int, definition: Definition) -> None: ...
