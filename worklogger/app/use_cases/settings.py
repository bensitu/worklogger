"""Settings use cases."""

from __future__ import annotations

from worklogger.app.use_cases._errors import infrastructure_failure

from collections.abc import Callable
from typing import Protocol

from worklogger.app.commands.settings_commands import SetSettingCommand
from worklogger.app.event_bus import EventBus, SettingsChanged
from worklogger.app.ports import KeyStore
from worklogger.app.queries.settings_queries import GetSettingQuery
from worklogger.config.constants import (
    HOLIDAY_REGION_SETTING_KEY,
    NETWORK_PROXY_PASSWORD_SETTING_KEY,
)
from worklogger.domain.settings.repositories import SettingsRepository
from worklogger.domain.settings.validation import normalize_setting
from worklogger.domain.shared.errors import InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result


class SecretBox(Protocol):
    def encrypt(self, value: str) -> str: ...
    def decrypt(self, stored: str) -> str: ...


class ProxyPasswordSettings:
    """Migrate a legacy password only after secure storage has succeeded."""

    def __init__(self, repository: SettingsRepository, credentials: KeyStore, *, user_id: int, secret_box: SecretBox) -> None:
        self._repository = repository
        self._credentials = credentials
        self._user_id = user_id
        self._name = f"proxy_password:{user_id}"
        self._secret_box = secret_box

    def load(self) -> Result[str | None]:
        try:
            return self._load()
        except Exception as error:
            return Result.failure(infrastructure_failure('credential_storage_unavailable', error, logger_name=__name__))

    def _load(self) -> Result[str | None]:
        legacy = self._repository.get(self._user_id, NETWORK_PROXY_PASSWORD_SETTING_KEY)
        if legacy and not legacy.startswith(("enc1:", "enc2:")):
            try:
                encrypted = self._secret_box.encrypt(legacy)
            except ValueError:
                return Result.failure(InfrastructureError("credential_reentry_required", "credential_reentry_required"))
            self._repository.set(self._user_id, NETWORK_PROXY_PASSWORD_SETTING_KEY, encrypted)
            legacy = encrypted
        stored = self._credentials.get_secret(self._name)
        if not stored.ok:
            return stored
        if legacy is not None:
            if legacy and stored.value is None:
                try:
                    password = self._secret_box.decrypt(legacy)
                except ValueError:
                    return Result.failure(InfrastructureError("credential_reentry_required", "credential_reentry_required"))
                saved = self._credentials.set_secret(self._name, password)
                if not saved.ok:
                    return Result.failure(saved.error)
                stored = Result.success(password)
            self._repository.delete(self._user_id, NETWORK_PROXY_PASSWORD_SETTING_KEY)
        return stored

    def save(self, password: str) -> Result[None]:
        try:
            result = self._credentials.set_secret(self._name, password)
            if result.ok:
                self._repository.delete(self._user_id, NETWORK_PROXY_PASSWORD_SETTING_KEY)
            return result
        except Exception as error:
            return Result.failure(infrastructure_failure('credential_storage_unavailable', error, logger_name=__name__))


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
        *,
        holiday_region_validator: Callable[[str], str] | None = None,
    ) -> None:
        self._repository = repository
        self._event_bus = event_bus
        self._holiday_region_validator = holiday_region_validator

    def handle(self, command: SetSettingCommand) -> Result[None]:
        try:
            key = _normalize_key(command.key)
            value = normalize_setting(key, command.value)
            if key == HOLIDAY_REGION_SETTING_KEY:
                if not value.strip():
                    value = ""
                elif self._holiday_region_validator is None:
                    raise ValueError("holiday_region_invalid")
                else:
                    value = self._holiday_region_validator(value)
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        try:
            self._repository.set(command.user_id, key, value)
        except Exception as error:
            return Result.failure(infrastructure_failure('settings_save_failed', error, logger_name=__name__))
        if self._event_bus is not None:
            self._event_bus.publish(
                SettingsChanged(user_id=command.user_id, key=key, value=value)
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
        try:
            return Result.success(self._repository.get(query.user_id, key, query.default))
        except Exception as error:
            return Result.failure(infrastructure_failure('settings_load_failed', error, logger_name=__name__))

    def get_all(self, user_id: int) -> Result[dict[str, str | None] | None]:
        reader = getattr(self._repository, "get_all", None)
        if reader is None:
            return Result.success(None)
        try:
            return Result.success(reader(user_id))
        except Exception as error:
            return Result.failure(infrastructure_failure('settings_load_failed', error, logger_name=__name__))

    def get_many(self, user_id: int, keys) -> Result[dict[str, str | None] | None]:
        reader = getattr(self._repository, "get_many", None)
        if reader is None:
            return Result.success(None)
        try:
            return Result.success(reader(user_id, keys))
        except Exception as error:
            return Result.failure(infrastructure_failure('settings_load_failed', error, logger_name=__name__))
