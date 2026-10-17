"""Custom work classifications whose accounting snapshots survive catalog changes."""

from uuid import uuid4
from worklogger.domain.worklog.models import CustomEntryType, EntryType
from worklogger.domain.shared.result import Result
from worklogger.domain.shared.errors import ValidationError, InfrastructureError
from worklogger.domain.worklog.type_repository import EntryTypeRepository


class EntryTypeService:
    def __init__(self, user_id: int, repository: EntryTypeRepository):
        self.user_id, self.repository = user_id, repository

    def list_types(self) -> Result[tuple[CustomEntryType, ...]]:
        try:
            return Result.success(self.repository.list_types(self.user_id))
        except Exception:
            return Result.failure(InfrastructureError("entry_types_load_failed", "entry_types_load_failed"))

    def save(self, label: str, category: str, previous: CustomEntryType | None = None) -> Result[CustomEntryType]:
        try:
            if previous is not None and previous.archived:
                raise ValueError("entry_type_unavailable")
            definition = CustomEntryType(previous.value if previous else "custom:" + uuid4().hex,
                label.strip(), category, previous.revision if previous else 0)
            return Result.success(self.repository.save_type(self.user_id, definition))
        except ValueError as error:
            return Result.failure(ValidationError(str(error), str(error)))
        except Exception:
            return Result.failure(InfrastructureError("entry_types_save_failed", "entry_types_save_failed"))

    def archive(self, definition: CustomEntryType) -> Result[None]:
        try:
            self.repository.archive_type(self.user_id, definition)
            return Result.success(None)
        except ValueError as error:
            return Result.failure(ValidationError(str(error), str(error)))
        except Exception:
            return Result.failure(InfrastructureError("entry_types_save_failed", "entry_types_save_failed"))

    def resolve(self, value: str, original: EntryType | CustomEntryType | None = None) -> EntryType | CustomEntryType:
        if isinstance(original, CustomEntryType) and original.value == value:
            return original
        if not value.startswith("custom:"):
            try:
                definition = EntryType(value)
            except ValueError:
                raise ValueError("entry_type_unavailable") from None
            if definition.is_legacy and definition != original:
                raise ValueError("entry_type_unavailable")
            return definition
        result = self.list_types()
        if not result.ok:
            raise ValueError("entry_types_load_failed")
        for definition in result.value:
            if definition.value == value and not definition.archived:
                return CustomEntryType(definition.value, definition.label, definition.category)
        raise ValueError("entry_type_unavailable")
