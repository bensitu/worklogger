"""Account-owned custom work-type catalog."""

from typing import Protocol
from worklogger.domain.worklog.models import CustomWorkType


class WorkTypeRepository(Protocol):
    def list_types(self, user_id: int) -> tuple[CustomWorkType, ...]: ...
    def save_type(self, user_id: int, definition: CustomWorkType) -> CustomWorkType: ...
    def archive_type(self, user_id: int, definition: CustomWorkType) -> None: ...
