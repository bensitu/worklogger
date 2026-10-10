"""Background import and preferences without exposing a desktop entry point."""

from typing import Protocol

from worklogger.domain.settings.background import (
    BackgroundImage,
    BackgroundRepository,
    BackgroundState,
    validate_opacity,
)
from worklogger.domain.shared.errors import InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result


class BackgroundImageLoader(Protocol):
    def load(self, source: str) -> Result[BackgroundImage]: ...


class BackgroundService:
    """Synchronous operations intended to be called by a background job runner."""

    def __init__(self, user_id: int, repository: BackgroundRepository, loader: BackgroundImageLoader):
        self._user_id = user_id
        self._repository = repository
        self._loader = loader

    def load(self) -> Result[BackgroundState]:
        return self._run(lambda: self._repository.load(self._user_id))

    def import_image(self, source: str) -> Result[BackgroundState]:
        loaded = self._loader.load(source)
        if not loaded.ok:
            return Result.failure(loaded.error)
        return self._run(lambda: self._repository.replace_image(self._user_id, loaded.value))

    def set_options(self, *, enabled: bool, opacity: int) -> Result[BackgroundState]:
        try:
            validate_opacity(opacity)
            if type(enabled) is not bool:
                raise ValueError("background_enabled_invalid")
        except ValueError as error:
            return Result.failure(ValidationError(str(error), str(error)))
        return self._run(lambda: self._repository.set_options(self._user_id, enabled=enabled, opacity=opacity))

    def clear(self) -> Result[BackgroundState]:
        return self._run(lambda: self._repository.clear(self._user_id))

    @staticmethod
    def _run(operation):
        try:
            return Result.success(operation())
        except ValueError as error:
            return Result.failure(ValidationError(str(error), str(error)))
        except Exception:  # noqa: BLE001 - Storage adapters have backend-specific failures.
            return Result.failure(InfrastructureError("background_storage_failed", "background_storage_failed"))
