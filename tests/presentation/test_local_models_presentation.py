from __future__ import annotations

import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

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
from worklogger.domain.local_model.models import (
    LocalModelEntry,
    LocalModelFileStatus,
    LocalModelListItem,
)
from worklogger.domain.shared.result import Result
from worklogger.presentation.local_models import LocalModelsDialog
from worklogger.presentation.viewmodels import LocalModelManagerViewModel


def _app() -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        return existing
    return QApplication([])


class FakeLocalModelHandlers:
    def __init__(self) -> None:
        self.entry = LocalModelEntry(
            id="model-a",
            display_name="Model A",
            filename="model-a.gguf",
        )
        self.selected: list[str | None] = []
        self.imported: list[Path | str] = []

    def handle(self, command: object) -> object:
        if isinstance(command, ListLocalModelsQuery):
            return Result.success(
                LocalModelInventory(
                    items=(
                        LocalModelListItem(
                            entry=self.entry,
                            active=bool(self.selected),
                            available=True,
                            verified=True,
                        ),
                    ),
                    active_model_id=self.selected[-1] if self.selected else None,
                )
            )
        if isinstance(command, RefreshLocalModelCatalogCommand):
            return Result.success((self.entry,))
        if isinstance(command, ImportLocalModelCommand):
            self.imported.append(command.source_path)
            return Result.success(self.entry)
        if isinstance(command, DownloadLocalModelCommand):
            return Result.success(self.entry)
        if isinstance(command, VerifyLocalModelCommand):
            return Result.success(
                LocalModelFileStatus(command.model_id, available=True, verified=True)
            )
        if isinstance(command, SelectLocalModelCommand):
            self.selected.append(command.model_id)
            return Result.success(None)
        if isinstance(command, DeleteLocalModelCommand):
            return Result.success(None)
        raise AssertionError(f"Unexpected command: {command!r}")


class LocalModelsPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = _app()

    def test_dialog_import_select_and_verify(self) -> None:
        handlers = FakeLocalModelHandlers()
        view_model = LocalModelManagerViewModel(
            user_id=1,
            list_handler=handlers,
            refresh_handler=handlers,
            import_handler=handlers,
            download_handler=handlers,
            verify_handler=handlers,
            select_handler=handlers,
            delete_handler=handlers,
        )
        dialog = LocalModelsDialog(view_model)

        self.assertTrue(dialog.refresh())
        dialog.model_list.setCurrentRow(0)
        self.assertTrue(dialog.verify_selected())
        self.assertTrue(dialog.select_current())
        self.assertTrue(dialog.import_model("demo.gguf"))

        self.assertEqual(handlers.selected, ["model-a"])
        self.assertEqual(handlers.imported, ["demo.gguf"])
        self.assertIn("Model imported.", dialog.status_label.text())


if __name__ == "__main__":
    unittest.main()
