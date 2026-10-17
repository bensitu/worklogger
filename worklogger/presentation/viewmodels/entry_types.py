"""Presentation operations for account-owned work classifications."""

from worklogger.app.ports import EntryTypeOperations


class EntryTypeManagerViewModel:
    def __init__(self, operations: EntryTypeOperations):
        self._operations = operations

    def list_entry_types(self):
        return self._operations.list_types()

    def save_entry_type(self, label, category, previous=None):
        return self._operations.save(label, category, previous)

    def archive_entry_type(self, definition):
        return self._operations.archive(definition)
