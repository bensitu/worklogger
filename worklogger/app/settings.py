"""Named preference reads with optional batching and consistent defaults."""

from collections.abc import Mapping
from typing import Protocol

from worklogger.app.queries.settings_queries import GetSettingQuery
from worklogger.app.failures import infrastructure_failure
from worklogger.domain.shared.result import Result


class SettingsReader(Protocol):
    def handle(self, query: GetSettingQuery) -> Result[str | None]: ...


def read_setting_values(reader: SettingsReader, user_id: int,
                        defaults: Mapping[str, str | None], *,
                        error_code: str = "settings_load_failed") -> Result[dict[str, str | None]]:
    if not defaults:
        return Result.success({})
    try:
        batch_reader = getattr(reader, "get_many", None)
        batch = batch_reader(user_id, tuple(defaults)) if callable(batch_reader) else None
        if isinstance(batch, Result):
            if not batch.ok:
                return Result.failure(batch.error)
            if batch.value is not None:
                return Result.success({key: batch.value.get(key) if batch.value.get(key) is not None else default
                                       for key, default in defaults.items()})
        values = {}
        for key, default in defaults.items():
            result = reader.handle(GetSettingQuery(user_id, key, default))
            if not result.ok:
                return Result.failure(result.error)
            values[key] = result.value if result.value is not None else default
        return Result.success(values)
    except Exception as error:
        return Result.failure(infrastructure_failure(error_code, error, logger_name=__name__))
