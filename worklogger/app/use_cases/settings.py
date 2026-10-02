"""Settings use cases."""

from __future__ import annotations

from typing import Protocol

from worklogger.app.commands.settings_commands import (
    SetActiveLocalModelCommand,
    SetSettingCommand,
)
from worklogger.app.event_bus import EventBus, SettingsChanged
from worklogger.app.queries.settings_queries import GetSettingQuery
from worklogger.config.constants import LOCAL_MODEL_ACTIVE_ID_SETTING_KEY, NETWORK_PROXY_PASSWORD_SETTING_KEY
from worklogger.domain.settings.repositories import SettingsRepository
from worklogger.domain.shared.errors import InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result


class CredentialStore(Protocol):
    def get_secret(self, name: str) -> Result[str | None]: ...
    def set_secret(self, name: str, value: str) -> Result[None]: ...


class ProxyPasswordSettings:
    """Migrate a legacy password only after secure storage has succeeded."""

    def __init__(self, repository: SettingsRepository, credentials: CredentialStore, *, user_id: int) -> None:
        self._repository = repository
        self._credentials = credentials
        self._user_id = user_id
        self._name = f"proxy_password:{user_id}"

    def load(self) -> Result[str | None]:
        try:
            return self._load()
        except Exception:
            return Result.failure(InfrastructureError("credential_storage_unavailable", "credential_storage_unavailable"))

    def _load(self) -> Result[str | None]:
        stored = self._credentials.get_secret(self._name)
        if not stored.ok:
            return stored
        legacy = self._repository.get(self._user_id, NETWORK_PROXY_PASSWORD_SETTING_KEY)
        if legacy is not None:
            if legacy and stored.value is None:
                saved = self._credentials.set_secret(self._name, legacy)
                if not saved.ok:
                    return Result.failure(saved.error)
                stored = Result.success(legacy)
            self._repository.delete(self._user_id, NETWORK_PROXY_PASSWORD_SETTING_KEY)
        return stored

    def save(self, password: str) -> Result[None]:
        try:
            result = self._credentials.set_secret(self._name, password)
            if result.ok:
                self._repository.delete(self._user_id, NETWORK_PROXY_PASSWORD_SETTING_KEY)
            return result
        except Exception:
            return Result.failure(InfrastructureError("credential_storage_unavailable", "credential_storage_unavailable"))


def _normalize_key(key: str) -> str:
    if not isinstance(key, str):
        raise TypeError("setting_key_must_be_string")
    cleaned = key.strip()
    if not cleaned:
        raise ValueError("setting_key_required")
    return cleaned


class SetSettingHandler:
    def __init__(
        self,
        repository: SettingsRepository,
        event_bus: EventBus | None = None,
    ) -> None:
        self._repository = repository
        self._event_bus = event_bus

    def handle(self, command: SetSettingCommand) -> Result[None]:
        try:
            key = _normalize_key(command.key)
            value = str(command.value)
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        self._repository.set(command.user_id, key, value)
        if self._event_bus is not None:
            self._event_bus.publish(
                SettingsChanged(user_id=command.user_id, key=key, value=value)
            )
        return Result.success(None)


class SetActiveLocalModelHandler:
    def __init__(
        self,
        repository: SettingsRepository,
        event_bus: EventBus | None = None,
    ) -> None:
        self._repository = repository
        self._event_bus = event_bus

    def handle(self, command: SetActiveLocalModelCommand) -> Result[None]:
        model_id = command.model_id.strip() if isinstance(command.model_id, str) else None
        if model_id:
            self._repository.set(command.user_id, LOCAL_MODEL_ACTIVE_ID_SETTING_KEY, model_id)
            value: str | None = model_id
        else:
            self._repository.delete(command.user_id, LOCAL_MODEL_ACTIVE_ID_SETTING_KEY)
            value = None
        if self._event_bus is not None:
            self._event_bus.publish(
                SettingsChanged(
                    user_id=command.user_id,
                    key=LOCAL_MODEL_ACTIVE_ID_SETTING_KEY,
                    value=value,
                )
            )
        return Result.success(None)


class GetSettingHandler:
    def __init__(self, repository: SettingsRepository) -> None:
        self._repository = repository

    def handle(self, query: GetSettingQuery) -> Result[str | None]:
        try:
            key = _normalize_key(query.key)
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        return Result.success(self._repository.get(query.user_id, key, query.default))
