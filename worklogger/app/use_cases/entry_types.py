"""Custom work classifications whose accounting snapshots survive catalog changes."""

from uuid import uuid4
from worklogger.domain.worklog.models import CustomEntryType, EntryType
from worklogger.domain.shared.result import Result
from worklogger.domain.shared.errors import ValidationError
from worklogger.app.failures import infrastructure_failure
from typing import Generic
from worklogger.domain.worklog.type_repository import ClassificationRepository, Definition


class ClassificationService(Generic[Definition]):
    error_prefix: str
    collection_prefix: str

    def __init__(self, user_id: int, repository: ClassificationRepository[Definition]):
        self.user_id, self.repository = user_id, repository

    def list_types(self) -> Result[tuple[Definition, ...]]:
        try:
            return Result.success(self.repository.list_types(self.user_id))
        except Exception as error:
            code = self.collection_prefix + "_load_failed"
            return Result.failure(infrastructure_failure(code, error, logger_name=__name__))

    def save(self, label: str, category: str, previous: Definition | None = None) -> Result[Definition]:
        try:
            if previous is not None and previous.archived:
                raise ValueError(self.error_prefix + "_unavailable")
            definition = self._definition(previous.value if previous else "custom:" + uuid4().hex,
                label.strip(), category, previous.revision if previous else 0)
            return Result.success(self.repository.save_type(self.user_id, definition))
        except ValueError as error:
            return Result.failure(ValidationError(str(error), str(error)))
        except Exception as error:
            code = self.collection_prefix + "_save_failed"
            return Result.failure(infrastructure_failure(code, error, logger_name=__name__))

    def archive(self, definition: Definition) -> Result[None]:
        try:
            self.repository.archive_type(self.user_id, definition)
            return Result.success(None)
        except ValueError as error:
            return Result.failure(ValidationError(str(error), str(error)))
        except Exception as error:
            code = self.collection_prefix + "_save_failed"
            return Result.failure(infrastructure_failure(code, error, logger_name=__name__))


class EntryTypeService(ClassificationService[CustomEntryType]):
    error_prefix = "entry_type"
    collection_prefix = "entry_types"

    @staticmethod
    def _definition(value, label, category, revision):
        return CustomEntryType(value, label, category, revision)

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
