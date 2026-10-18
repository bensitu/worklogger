"""Account-owned work arrangements with immutable historical labels."""

from worklogger.app.use_cases.entry_types import ClassificationService
from worklogger.domain.worklog.models import CustomWorkMode, decode_work_mode


class WorkModeService(ClassificationService[CustomWorkMode]):
    error_prefix = "work_mode"
    collection_prefix = "work_modes"

    @staticmethod
    def _definition(value, label, category, revision):
        if category != "work":
            raise ValueError("work_mode_invalid")
        return CustomWorkMode(value, label, revision)

    def resolve(self, value, original=None):
        if value is None:
            return None
        key = getattr(value, "value", value)
        if isinstance(original, CustomWorkMode) and original.value == key:
            return original
        if not isinstance(key, str) or not key.startswith("custom:"):
            return decode_work_mode(key)
        result = self.list_types()
        if not result.ok:
            raise ValueError("work_modes_load_failed")
        for definition in result.value:
            if definition.value == key and not definition.archived:
                return CustomWorkMode(definition.value, definition.label)
        raise ValueError("work_mode_unavailable")
