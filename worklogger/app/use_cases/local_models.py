"""Local model use cases."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from worklogger.app.commands.local_model_commands import (
    DeleteLocalModelCommand,
    DownloadLocalModelCommand,
    ImportLocalModelCommand,
    RefreshLocalModelCatalogCommand,
    SelectLocalModelCommand,
    VerifyLocalModelCommand,
)
from worklogger.app.queries.local_model_queries import ListLocalModelsQuery
from worklogger.config.constants import LOCAL_MODEL_ACTIVE_ID_SETTING_KEY
from worklogger.config.constants import LOCAL_MODEL_ENABLED_SETTING_KEY
from worklogger.domain.local_model.models import (
    LocalModelEntry,
    LocalModelFileStatus,
    LocalModelListItem,
)
from worklogger.domain.settings.repositories import SettingsRepository
from worklogger.domain.shared.errors import InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result


class LocalModelStore(Protocol):
    def list_models(self) -> Result[tuple[LocalModelEntry, ...]]:
        ...

    def refresh_catalog(self) -> Result[tuple[LocalModelEntry, ...]]:
        ...

    def import_model(self, source: Path) -> Result[LocalModelEntry]:
        ...

    def download_model(self, model_id: str) -> Result[LocalModelEntry]:
        ...

    def verify_model(self, model_id: str) -> Result[LocalModelFileStatus]:
        ...

    def delete_model(self, model_id: str) -> Result[None]:
        ...


class LocalModelUsageReader(Protocol):
    def list_user_ids_for_key_value(self, key: str, value: str) -> tuple[int, ...]:
        ...


@dataclass(frozen=True)
class LocalModelInventory:
    items: tuple[LocalModelListItem, ...]
    active_model_id: str | None = None


@dataclass(frozen=True)
class LocalModelRuntimeStatus:
    enabled: bool
    ready: bool
    active_model_id: str | None = None
    reason: str = ""


class GetLocalModelRuntimeStatusHandler:
    def __init__(
        self,
        *,
        store: LocalModelStore,
        settings: SettingsRepository,
    ) -> None:
        self._store = store
        self._settings = settings

    def handle(self, query: ListLocalModelsQuery) -> Result[LocalModelRuntimeStatus]:
        enabled = str(
            self._settings.get(query.user_id, LOCAL_MODEL_ENABLED_SETTING_KEY, "1")
            or ""
        ).strip().lower() in {"1", "true", "yes", "on"}
        active_model_id = _active_model_id(self._settings, query.user_id)
        if not enabled:
            return Result.success(
                LocalModelRuntimeStatus(
                    enabled=False,
                    ready=False,
                    active_model_id=active_model_id,
                    reason="local_model_disabled",
                )
            )
        if not active_model_id:
            return Result.success(
                LocalModelRuntimeStatus(
                    enabled=True,
                    ready=False,
                    reason="local_model_not_selected",
                )
            )
        status = self._store.verify_model(active_model_id)
        if not status.ok or status.value is None:
            return Result.failure(
                status.error or InfrastructureError("local_model_verify_failed", "local_model_verify_failed")
            )
        return Result.success(
            LocalModelRuntimeStatus(
                enabled=True,
                ready=status.value.verified,
                active_model_id=active_model_id,
                reason=status.value.reason,
            )
        )


class ListLocalModelsHandler:
    def __init__(
        self,
        *,
        store: LocalModelStore,
        settings: SettingsRepository,
    ) -> None:
        self._store = store
        self._settings = settings

    def handle(self, query: ListLocalModelsQuery) -> Result[LocalModelInventory]:
        entries = self._store.list_models()
        if not entries.ok or entries.value is None:
            return Result.failure(
                entries.error or InfrastructureError("local_model_list_failed", "local_model_list_failed")
            )
        active_model_id = _active_model_id(self._settings, query.user_id)
        items: list[LocalModelListItem] = []
        for entry in entries.value:
            status = self._store.verify_model(entry.id)
            if status.ok and status.value is not None:
                file_status = status.value
            else:
                file_status = LocalModelFileStatus(
                    model_id=entry.id,
                    available=False,
                    verified=False,
                    reason=status.error.message if status.error else "local_model_verify_failed",
                )
            items.append(
                LocalModelListItem(
                    entry=entry,
                    active=entry.id == active_model_id,
                    available=file_status.available,
                    verified=file_status.verified,
                    reason=file_status.reason,
                )
            )
        return Result.success(
            LocalModelInventory(
                items=tuple(items),
                active_model_id=active_model_id,
            )
        )


class RefreshLocalModelCatalogHandler:
    def __init__(self, store: LocalModelStore) -> None:
        self._store = store

    def handle(
        self,
        _command: RefreshLocalModelCatalogCommand,
    ) -> Result[tuple[LocalModelEntry, ...]]:
        return self._store.refresh_catalog()


class ImportLocalModelHandler:
    def __init__(
        self,
        *,
        store: LocalModelStore,
        settings: SettingsRepository,
    ) -> None:
        self._store = store
        self._settings = settings

    def handle(self, command: ImportLocalModelCommand) -> Result[LocalModelEntry]:
        imported = self._store.import_model(Path(command.source_path))
        if not imported.ok or imported.value is None:
            return Result.failure(
                imported.error or InfrastructureError("local_model_import_failed", "local_model_import_failed")
            )
        self._settings.set(
            command.user_id,
            LOCAL_MODEL_ACTIVE_ID_SETTING_KEY,
            imported.value.id,
        )
        return imported


class DownloadLocalModelHandler:
    def __init__(
        self,
        *,
        store: LocalModelStore,
        settings: SettingsRepository,
    ) -> None:
        self._store = store
        self._settings = settings

    def handle(self, command: DownloadLocalModelCommand) -> Result[LocalModelEntry]:
        model_id = _required_model_id(command.model_id)
        if not model_id.ok or model_id.value is None:
            return Result.failure(model_id.error or _model_id_required_error())
        downloaded = self._store.download_model(model_id.value)
        if not downloaded.ok or downloaded.value is None:
            return Result.failure(
                downloaded.error
                or InfrastructureError(
                    "local_model_download_failed",
                    "local_model_download_failed",
                )
            )
        self._settings.set(
            command.user_id,
            LOCAL_MODEL_ACTIVE_ID_SETTING_KEY,
            downloaded.value.id,
        )
        return downloaded


class VerifyLocalModelHandler:
    def __init__(self, store: LocalModelStore) -> None:
        self._store = store

    def handle(
        self,
        command: VerifyLocalModelCommand,
    ) -> Result[LocalModelFileStatus]:
        model_id = _required_model_id(command.model_id)
        if not model_id.ok or model_id.value is None:
            return Result.failure(model_id.error or _model_id_required_error())
        return self._store.verify_model(model_id.value)


class SelectLocalModelHandler:
    def __init__(
        self,
        *,
        store: LocalModelStore,
        settings: SettingsRepository,
    ) -> None:
        self._store = store
        self._settings = settings

    def handle(self, command: SelectLocalModelCommand) -> Result[None]:
        model_id = str(command.model_id or "").strip()
        if not model_id:
            self._settings.delete(command.user_id, LOCAL_MODEL_ACTIVE_ID_SETTING_KEY)
            return Result.success(None)
        status = self._store.verify_model(model_id)
        if not status.ok or status.value is None:
            return Result.failure(
                status.error
                or InfrastructureError(
                    "local_model_verify_failed",
                    "local_model_verify_failed",
                )
            )
        if not status.value.verified:
            reason = status.value.reason or "local_model_not_ready"
            return Result.failure(
                ValidationError(reason, reason)
            )
        self._settings.set(command.user_id, LOCAL_MODEL_ACTIVE_ID_SETTING_KEY, model_id)
        return Result.success(None)


class DeleteLocalModelHandler:
    def __init__(
        self,
        *,
        store: LocalModelStore,
        settings: SettingsRepository,
        usage_reader: LocalModelUsageReader | None = None,
    ) -> None:
        self._store = store
        self._settings = settings
        self._usage_reader = usage_reader

    def handle(self, command: DeleteLocalModelCommand) -> Result[None]:
        model_id = _required_model_id(command.model_id)
        if not model_id.ok or model_id.value is None:
            return Result.failure(model_id.error or _model_id_required_error())
        users = (
            self._usage_reader.list_user_ids_for_key_value(
                LOCAL_MODEL_ACTIVE_ID_SETTING_KEY,
                model_id.value,
            )
            if self._usage_reader is not None
            else ()
        )
        other_users = tuple(user_id for user_id in users if user_id != command.user_id)
        if other_users:
            return Result.failure(
                ValidationError(
                    "local_model_used_by_another_user",
                    "local_model_used_by_another_user",
                )
            )
        deleted = self._store.delete_model(model_id.value)
        if not deleted.ok:
            return deleted
        if _active_model_id(self._settings, command.user_id) == model_id.value:
            self._settings.delete(command.user_id, LOCAL_MODEL_ACTIVE_ID_SETTING_KEY)
        return Result.success(None)


def _active_model_id(settings: SettingsRepository, user_id: int) -> str | None:
    value = settings.get(user_id, LOCAL_MODEL_ACTIVE_ID_SETTING_KEY, None)
    cleaned = str(value or "").strip()
    return cleaned or None


def _required_model_id(model_id: str) -> Result[str]:
    cleaned = str(model_id or "").strip()
    if not cleaned:
        return Result.failure(_model_id_required_error())
    return Result.success(cleaned)


def _model_id_required_error() -> ValidationError:
    return ValidationError("local_model_id_required", "local_model_id_required")
