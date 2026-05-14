"""Local model presentation ViewModel."""

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
from worklogger.app.use_cases.local_models import LocalModelInventory
from worklogger.domain.local_model.models import LocalModelEntry, LocalModelFileStatus
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result


class LocalModelsListHandler(Protocol):
    def handle(self, query: ListLocalModelsQuery) -> Result[LocalModelInventory]:
        ...


class LocalModelRefreshHandler(Protocol):
    def handle(
        self,
        command: RefreshLocalModelCatalogCommand,
    ) -> Result[tuple[LocalModelEntry, ...]]:
        ...


class LocalModelImportHandler(Protocol):
    def handle(self, command: ImportLocalModelCommand) -> Result[LocalModelEntry]:
        ...


class LocalModelDownloadHandler(Protocol):
    def handle(self, command: DownloadLocalModelCommand) -> Result[LocalModelEntry]:
        ...


class LocalModelVerifyHandler(Protocol):
    def handle(self, command: VerifyLocalModelCommand) -> Result[LocalModelFileStatus]:
        ...


class LocalModelSelectHandler(Protocol):
    def handle(self, command: SelectLocalModelCommand) -> Result[None]:
        ...


class LocalModelDeleteHandler(Protocol):
    def handle(self, command: DeleteLocalModelCommand) -> Result[None]:
        ...


@dataclass(frozen=True)
class LocalModelManagerState:
    inventory: LocalModelInventory
    message: str = ""


class LocalModelManagerViewModel:
    def __init__(
        self,
        *,
        user_id: int,
        list_handler: LocalModelsListHandler,
        refresh_handler: LocalModelRefreshHandler,
        import_handler: LocalModelImportHandler,
        download_handler: LocalModelDownloadHandler,
        verify_handler: LocalModelVerifyHandler,
        select_handler: LocalModelSelectHandler,
        delete_handler: LocalModelDeleteHandler,
    ) -> None:
        self._user_id = user_id
        self._list_handler = list_handler
        self._refresh_handler = refresh_handler
        self._import_handler = import_handler
        self._download_handler = download_handler
        self._verify_handler = verify_handler
        self._select_handler = select_handler
        self._delete_handler = delete_handler

    def load(self) -> Result[LocalModelManagerState]:
        inventory = self._list_handler.handle(ListLocalModelsQuery(self._user_id))
        if not inventory.ok or inventory.value is None:
            return Result.failure(
                inventory.error or ValidationError("local_models_load_failed", "local_models_load_failed")
            )
        return Result.success(LocalModelManagerState(inventory.value))

    def refresh_catalog(self) -> Result[LocalModelManagerState]:
        refreshed = self._refresh_handler.handle(
            RefreshLocalModelCatalogCommand(self._user_id)
        )
        if not refreshed.ok:
            return Result.failure(
                refreshed.error or ValidationError("local_model_refresh_failed", "local_model_refresh_failed")
            )
        return _with_message(self.load(), "Catalog refreshed.")

    def import_model(self, source: Path | str) -> Result[LocalModelManagerState]:
        imported = self._import_handler.handle(
            ImportLocalModelCommand(self._user_id, source)
        )
        if not imported.ok:
            return Result.failure(
                imported.error or ValidationError("local_model_import_failed", "local_model_import_failed")
            )
        return _with_message(self.load(), "Model imported.")

    def download_model(self, model_id: str) -> Result[LocalModelManagerState]:
        downloaded = self._download_handler.handle(
            DownloadLocalModelCommand(self._user_id, model_id)
        )
        if not downloaded.ok:
            return Result.failure(
                downloaded.error or ValidationError("local_model_download_failed", "local_model_download_failed")
            )
        return _with_message(self.load(), "Model downloaded.")

    def verify_model(self, model_id: str) -> Result[LocalModelFileStatus]:
        return self._verify_handler.handle(
            VerifyLocalModelCommand(self._user_id, model_id)
        )

    def select_model(self, model_id: str | None) -> Result[LocalModelManagerState]:
        selected = self._select_handler.handle(
            SelectLocalModelCommand(self._user_id, model_id)
        )
        if not selected.ok:
            return Result.failure(
                selected.error or ValidationError("local_model_select_failed", "local_model_select_failed")
            )
        return _with_message(self.load(), "Active model updated.")

    def delete_model(self, model_id: str) -> Result[LocalModelManagerState]:
        deleted = self._delete_handler.handle(
            DeleteLocalModelCommand(self._user_id, model_id)
        )
        if not deleted.ok:
            return Result.failure(
                deleted.error or ValidationError("local_model_delete_failed", "local_model_delete_failed")
            )
        return _with_message(self.load(), "Model deleted.")


def _with_message(
    result: Result[LocalModelManagerState],
    message: str,
) -> Result[LocalModelManagerState]:
    if not result.ok or result.value is None:
        return result
    return Result.success(
        LocalModelManagerState(
            inventory=result.value.inventory,
            message=message,
        )
    )
