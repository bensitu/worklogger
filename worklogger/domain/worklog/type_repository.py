"""Account-owned custom work-type catalog."""

from typing import Protocol
from worklogger.domain.worklog.models import CustomEntryType


class EntryTypeRepository(Protocol):
    def list_types(self, user_id: int) -> tuple[CustomEntryType, ...]: ...
    def save_type(self, user_id: int, definition: CustomEntryType) -> CustomEntryType: ...
    def archive_type(self, user_id: int, definition: CustomEntryType) -> None: ...
