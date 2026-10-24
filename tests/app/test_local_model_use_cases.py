from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from worklogger.app.commands.local_model_commands import (
    DeleteLocalModelCommand,
    DownloadLocalModelCommand,
    ImportLocalModelCommand,
    SelectLocalModelCommand,
    VerifyLocalModelCommand,
)
from worklogger.app.job_runner import CancellationToken
from worklogger.app.queries.local_model_queries import ListLocalModelsQuery
from worklogger.app.use_cases.local_models import (
    DeleteLocalModelHandler,
    DownloadLocalModelHandler,
    ImportLocalModelHandler,
    ListLocalModelsHandler,
    SelectLocalModelHandler,
    VerifyLocalModelHandler,
)
from worklogger.config.constants import (
    LOCAL_MODEL_ACTIVE_ID_SETTING_KEY,
)
from worklogger.domain.local_model.models import LocalModelEntry, LocalModelFileStatus
from worklogger.domain.shared.errors import CancellationError
from worklogger.domain.shared.result import Result


class MemorySettings:
    def __init__(self) -> None:
        self.values: dict[tuple[int, str], str] = {}

    def get(self, user_id: int, key: str, default: str | None = None) -> str | None:
        return self.values.get((user_id, key), default)

    def set(self, user_id: int, key: str, value: str) -> None:
        self.values[(user_id, key)] = value

    def delete(self, user_id: int, key: str) -> None:
        self.values.pop((user_id, key), None)

    def list_user_ids_for_key_value(self, key: str, value: str) -> tuple[int, ...]:
        return tuple(
            user_id
            for (user_id, stored_key), stored_value in self.values.items()
            if stored_key == key and stored_value == value
        )


class MemoryStore:
    def __init__(self) -> None:
        self.entries = [
            LocalModelEntry(
                id="model-a",
                display_name="Model A",
                filename="model-a.gguf",
                sha256="",
            )
        ]
        self.deleted: list[str] = []

    def list_models(self) -> Result[tuple[LocalModelEntry, ...]]:
        return Result.success(tuple(self.entries))

    def refresh_catalog(self) -> Result[tuple[LocalModelEntry, ...]]:
        return Result.success(tuple(self.entries))

    def import_model(self, _source: Path) -> Result[LocalModelEntry]:
        entry = LocalModelEntry(
            id="local-imported",
            display_name="Imported",
            filename="imported.gguf",
            sha256="",
        )
        self.entries.append(entry)
        return Result.success(entry)

    def download_model(self, model_id: str) -> Result[LocalModelEntry]:
        return Result.success(self.entries[0])

    def verify_model(self, model_id: str) -> Result[LocalModelFileStatus]:
        return Result.success(
            LocalModelFileStatus(
                model_id=model_id,
                available=True,
                verified=True,
            )
        )

    def delete_model(self, model_id: str) -> Result[None]:
        self.deleted.append(model_id)
        self.entries = [entry for entry in self.entries if entry.id != model_id]
        return Result.success(None)


class LocalModelUseCaseTests(unittest.TestCase):
    def test_cancelled_verification_stops_inventory_and_keeps_selection(self) -> None:
        for operation in ("list", "download", "verify", "select"):
            with self.subTest(operation=operation):
                token = CancellationToken()
                settings, store = MemorySettings(), MemoryStore()
                settings.set(1, LOCAL_MODEL_ACTIVE_ID_SETTING_KEY, "previous-model")

                def verify(model_id, *, is_cancelled):
                    token.cancel()
                    self.assertTrue(is_cancelled())
                    return Result.failure(CancellationError("job_cancelled", "job_cancelled"))

                with patch.object(store, "verify_model", side_effect=verify) as verification, \
                     patch.object(store, "download_model", return_value=Result.success(store.entries[0])):
                    if operation == "list":
                        result = ListLocalModelsHandler(store=store, settings=settings).handle(ListLocalModelsQuery(1, token))
                    elif operation == "download":
                        result = DownloadLocalModelHandler(store=store, settings=settings).handle(DownloadLocalModelCommand(1, "model-a", token))
                    elif operation == "verify":
                        result = VerifyLocalModelHandler(store).handle(VerifyLocalModelCommand(1, "model-a", token))
                    else:
                        result = SelectLocalModelHandler(store=store, settings=settings).handle(SelectLocalModelCommand(1, "model-a", token))
                self.assertIsInstance(result.error, CancellationError)
                verification.assert_called_once()
                self.assertEqual(settings.get(1, LOCAL_MODEL_ACTIVE_ID_SETTING_KEY), "previous-model")

    def test_import_selects_model_for_current_user(self) -> None:
        settings = MemorySettings()
        store = MemoryStore()

        result = ImportLocalModelHandler(store=store, settings=settings).handle(
            ImportLocalModelCommand(1, "imported.gguf")
        )

        self.assertTrue(result.ok)
        self.assertEqual(
            settings.get(1, LOCAL_MODEL_ACTIVE_ID_SETTING_KEY),
            "local-imported",
        )

    def test_list_marks_active_verified_model(self) -> None:
        settings = MemorySettings()
        store = MemoryStore()
        settings.set(1, LOCAL_MODEL_ACTIVE_ID_SETTING_KEY, "model-a")

        result = ListLocalModelsHandler(store=store, settings=settings).handle(
            ListLocalModelsQuery(1)
        )

        self.assertTrue(result.ok)
        assert result.value is not None
        self.assertTrue(result.value.items[0].active)
        self.assertTrue(result.value.items[0].verified)

    def test_delete_blocks_model_used_by_another_user(self) -> None:
        settings = MemorySettings()
        store = MemoryStore()
        settings.set(2, LOCAL_MODEL_ACTIVE_ID_SETTING_KEY, "model-a")

        result = DeleteLocalModelHandler(
            store=store,
            settings=settings,
            usage_reader=settings,
        ).handle(DeleteLocalModelCommand(1, "model-a"))

        self.assertFalse(result.ok)
        self.assertEqual(store.deleted, [])

    def test_select_requires_verified_file(self) -> None:
        settings = MemorySettings()
        store = MemoryStore()

        result = SelectLocalModelHandler(store=store, settings=settings).handle(
            SelectLocalModelCommand(1, "model-a")
        )

        self.assertTrue(result.ok)
        self.assertEqual(settings.get(1, LOCAL_MODEL_ACTIVE_ID_SETTING_KEY), "model-a")

        with patch.object(store, "verify_model", return_value=Result.success(
                LocalModelFileStatus("model-a", available=True, verified=False))):
            rejected = SelectLocalModelHandler(store=store, settings=settings).handle(SelectLocalModelCommand(2, "model-a"))
        self.assertFalse(rejected.ok)
        self.assertIsNone(settings.get(2, LOCAL_MODEL_ACTIVE_ID_SETTING_KEY))


if __name__ == "__main__":
    unittest.main()
