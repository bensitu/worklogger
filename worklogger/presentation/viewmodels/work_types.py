"""Presentation operations for account-owned work classifications."""

from worklogger.app.ports import WorkTypeOperations


class WorkTypeManagerViewModel:
    def __init__(self, operations: WorkTypeOperations):
        self._operations = operations

    def list_work_types(self):
        return self._operations.list_types()

    def save_work_type(self, label, category, previous=None):
        return self._operations.save(label, category, previous)

    def archive_work_type(self, definition):
        return self._operations.archive(definition)
