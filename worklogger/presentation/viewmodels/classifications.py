"""Presentation operations for account-owned work classifications."""


class ClassificationManagerViewModel:
    def __init__(self, operations):
        self._operations = operations

    def list_types(self):
        return self._operations.list_types()

    def save_type(self, label, category, previous=None):
        return self._operations.save(label, category, previous)

    def archive_type(self, definition):
        return self._operations.archive(definition)
