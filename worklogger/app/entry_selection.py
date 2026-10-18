"""Resolve editable classifications and project associations through service ports."""

from dataclasses import dataclass

from worklogger.app.ports import EntryTypeOperations, ProjectOperations, WorkModeOperations
from worklogger.domain.projects.models import WorkContext
from worklogger.domain.worklog.models import (
    CustomEntryType, EntryType, WorkModeValue, decode_work_mode,
)


@dataclass(frozen=True)
class EntrySelectionResolver:
    entry_types: EntryTypeOperations | None = None
    work_modes: WorkModeOperations | None = None
    projects: ProjectOperations | None = None

    def resolve_entry_type(self, value: str, original: EntryType | CustomEntryType | None = None
                           ) -> EntryType | CustomEntryType:
        if self.entry_types is not None:
            return self.entry_types.resolve(value, original)
        if isinstance(original, CustomEntryType) and original.value == value:
            return original
        try:
            definition = EntryType(value)
        except (TypeError, ValueError):
            raise ValueError("entry_type_unavailable") from None
        if definition.is_legacy and definition != original:
            raise ValueError("entry_type_unavailable")
        return definition

    def resolve_work_mode(self, value: str | WorkModeValue | None,
                          original: WorkModeValue | None = None) -> WorkModeValue | None:
        if self.work_modes is not None:
            return self.work_modes.resolve(value, original)
        return decode_work_mode(value)

    def resolve_context(self, context: WorkContext, original: WorkContext | None = None) -> WorkContext:
        if not isinstance(context, WorkContext):
            raise ValueError("work_context_invalid")
        if self.projects is None:
            if context.project_id is not None:
                raise ValueError("project_unavailable")
            return context
        return self.projects.resolve(context, original)
