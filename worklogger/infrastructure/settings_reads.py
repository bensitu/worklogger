"""Read only the named preferences needed by a runtime adapter."""

from collections.abc import Mapping


def selected_settings(repository, user_id, keys):
    reader = getattr(repository, "get_many", None)
    values = reader(user_id, keys) if reader is not None else None
    if not isinstance(values, Mapping):
        values = repository.get_all(user_id)
    return {key: values[key] for key in keys if key in values}
