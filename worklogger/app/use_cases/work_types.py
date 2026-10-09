"""Custom work classifications whose accounting snapshots survive catalog changes."""

from uuid import uuid4
from worklogger.domain.worklog.models import CustomWorkType, WorkType
from worklogger.domain.shared.result import Result
from worklogger.domain.shared.errors import ValidationError, InfrastructureError


class WorkTypeService:
    def __init__(self, user_id, repository):
        self.user_id, self.repository = user_id, repository

    def list_types(self):
        try:
            return Result.success(self.repository.list_types(self.user_id))
        except Exception:
            return Result.failure(InfrastructureError("work_types_load_failed", "work_types_load_failed"))

    def save(self, label, category, previous=None):
        try:
            definition = CustomWorkType(previous.value if previous else "custom:" + uuid4().hex,
                label.strip(), category, previous.revision if previous else 0)
            return Result.success(self.repository.save_type(self.user_id, definition))
        except ValueError as error:
            return Result.failure(ValidationError(str(error), str(error)))
        except Exception:
            return Result.failure(InfrastructureError("work_types_save_failed", "work_types_save_failed"))

    def archive(self, definition):
        try:
            self.repository.archive_type(self.user_id, definition)
            return Result.success(None)
        except ValueError as error:
            return Result.failure(ValidationError(str(error), str(error)))
        except Exception:
            return Result.failure(InfrastructureError("work_types_save_failed", "work_types_save_failed"))

    def resolve(self, value, original=None):
        if isinstance(original, CustomWorkType) and original.value == value:
            return original
        if not value.startswith("custom:"):
            return WorkType(value)
        result = self.list_types()
        if not result.ok:
            raise ValueError("work_types_load_failed")
        for definition in result.value:
            if definition.value == value and not definition.archived:
                return CustomWorkType(definition.value, definition.label, definition.category)
        raise ValueError("work_type_unavailable")
