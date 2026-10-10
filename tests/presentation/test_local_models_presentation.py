from __future__ import annotations

import os
from pathlib import Path
import unittest
import threading
import time
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

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
    DownloadProgress,
)
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import set_language
from worklogger.presentation.job_runner import ImmediateJobRunner, QtJobRunner
from worklogger.presentation.local_models import LocalModelsDialog
from worklogger.presentation.local_models.controller import LocalModelsWorkflowController
from worklogger.app.job_runner import JobHandle
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
        self.deleted: list[str] = []

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
            self.deleted.append(command.model_id)
            return Result.success(None)
        raise AssertionError(f"Unexpected command: {command!r}")


class LocalModelsPresentationTests(unittest.TestCase):
    def test_download_progress_distinguishes_transfer_verification_and_completion(self):
        class Runner:
            def submit(self, name, job, *, on_complete):
                self.job, self.complete = job, on_complete
                return JobHandle("model-download", lambda: None)
        handlers = FakeLocalModelHandlers()
        model = LocalModelManagerViewModel(user_id=1, list_handler=handlers, refresh_handler=handlers,
            import_handler=handlers, download_handler=handlers, verify_handler=handlers,
            select_handler=handlers, delete_handler=handlers)
        dialog = LocalModelsDialog(model, job_runner=ImmediateJobRunner())
        self.addCleanup(dialog.deleteLater)
        dialog.refresh()
        runner = Runner()
        dialog._job_runner = runner
        self.assertTrue(dialog.download_selected())
        dialog.download_progress.emit(DownloadProgress(25, 100))
        self._app.processEvents()
        self.assertEqual(dialog.progress_bar.value(), 25)
        dialog.download_progress.emit(DownloadProgress(100, 100))
        self._app.processEvents()
        self.assertEqual(dialog.progress_bar.value(), 99)
        dialog.download_progress.emit(DownloadProgress(100, None))
        self._app.processEvents()
        self.assertEqual(dialog.progress_bar.maximum(), 0)
        dialog.download_progress.emit(DownloadProgress(100, 100, "verification"))
        self._app.processEvents()
        self.assertEqual(dialog.progress_bar.maximum(), 0)
        from worklogger.domain.shared.errors import CancellationError
        runner.complete(Result.failure(CancellationError("job_cancelled", "job_cancelled")))
        self.assertTrue(dialog.progress_bar.isHidden())
        self.assertFalse(dialog._busy)
        self.assertTrue(dialog.download_selected())
        runner.complete(model.load())
        self.assertEqual(dialog.progress_bar.value(), 100)

    def tearDown(self):
        set_language("en_US")

    def test_model_inventory_load_runs_off_ui_thread(self):
        handlers = FakeLocalModelHandlers()
        model = LocalModelManagerViewModel(
            user_id=1, list_handler=handlers, refresh_handler=handlers, import_handler=handlers,
            download_handler=handlers, verify_handler=handlers, select_handler=handlers, delete_handler=handlers,
        )
        original = model.load
        threads = []

        def load():
            threads.append(threading.get_ident())
            return original()

        model.load = load
        dialog = LocalModelsDialog(model, job_runner=QtJobRunner())
        self.assertTrue(dialog.refresh())
        self.assertFalse(dialog.select_button.isEnabled())
        deadline = time.monotonic() + 3
        while dialog._pending_handle is not None and time.monotonic() < deadline:
            self._app.processEvents()
            time.sleep(0.01)
        self.assertIsNone(dialog._pending_handle)
        self.assertIsNotNone(dialog.state)
        self.assertEqual(dialog.model_name_label.text(), "Model A")
        self.assertFalse(dialog.download_button.isEnabled())
        self.assertTrue(dialog.select_button.isEnabled())
        self.assertTrue(threads)
        self.assertNotEqual(threads[0], threading.get_ident())
        dialog.close()

    def test_workflow_loads_inventory_and_opens_model_manager(self):
        handlers = FakeLocalModelHandlers()
        model = LocalModelManagerViewModel(
            user_id=1, list_handler=handlers, refresh_handler=handlers, import_handler=handlers,
            download_handler=handlers, verify_handler=handlers, select_handler=handlers, delete_handler=handlers,
        )
        calls = []
        dialogs = []

        class ActionDialog(LocalModelsDialog):
            def refresh(self):
                from PySide6.QtCore import QTimer
                calls.append("load")
                QTimer.singleShot(0, self, self.accept)
                return super().refresh()

        def create(view_model, parent):
            dialog = ActionDialog(view_model, parent, job_runner=ImmediateJobRunner())
            dialogs.append(dialog)
            return dialog

        workflow = LocalModelsWorkflowController(model, dialog_factory=create)
        workflow.open()
        self.assertEqual(calls, ["load"])
        for dialog in dialogs:
            dialog.deleteLater()

    def test_pending_model_job_blocks_close_until_completion(self):
        handlers = FakeLocalModelHandlers()
        model = LocalModelManagerViewModel(
            user_id=1, list_handler=handlers, refresh_handler=handlers, import_handler=handlers,
            download_handler=handlers, verify_handler=handlers, select_handler=handlers, delete_handler=handlers,
        )
        dialog = LocalModelsDialog(model, job_runner=ImmediateJobRunner())
        dialog.show()
        self._app.processEvents()
        cancellations = []
        dialog._pending_handle = JobHandle(job_id="pending", cancel=lambda: cancellations.append(True))
        dialog._set_busy(True)
        self.assertTrue(dialog.close_button.isEnabled())
        dialog.close()
        self.assertTrue(dialog.isVisible())
        self.assertEqual(cancellations, [True])
        dialog._pending_handle = None
        dialog._set_busy(False)
        dialog.close()
        self.assertFalse(dialog.isVisible())

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
        dialog = LocalModelsDialog(view_model, job_runner=ImmediateJobRunner())

        self.assertTrue(dialog.refresh())
        dialog.model_list.setCurrentRow(0)
        self.assertTrue(dialog.verify_selected())
        self.assertTrue(dialog.select_current())
        self.assertEqual(dialog._selected_model_id(), "model-a")
        self.assertFalse(dialog.select_button.isEnabled())
        self.assertTrue(dialog.import_model("demo.gguf"))

        self.assertEqual(handlers.selected, ["model-a"])
        self.assertEqual(handlers.imported, ["demo.gguf"])
        self.assertIn("Model imported.", dialog.status_label.text())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.assertFalse(dialog.delete_selected())
        self.assertEqual(handlers.deleted, [])
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.assertTrue(dialog.delete_selected())
        self.assertEqual(handlers.deleted, ["model-a"])

        from dataclasses import replace
        handlers.entry = replace(handlers.entry, description="English description", license="MIT", min_ram_gb=8,
                                 description_translations={"zh_CN": "中文描述", "ja_JP": "日本語の説明"})
        for language, expected in (("en_US", "English description"), ("zh_CN", "中文描述"), ("ja_JP", "日本語の説明")):
            set_language(language)
            self.assertTrue(dialog.refresh())
            tooltip = dialog.model_list.item(0).toolTip()
            self.assertIn(expected, tooltip)
            self.assertEqual(dialog.description_label.text(), expected)
            self.assertIn("8192", tooltip)
            self.assertIn("MIT", tooltip)
            if language != "en_US":
                self.assertNotIn("Estimated RAM", tooltip)

    def test_dialog_can_run_long_actions_through_job_runner(self) -> None:
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
        dialog = LocalModelsDialog(view_model, job_runner=ImmediateJobRunner())

        self.assertTrue(dialog.refresh())
        dialog.model_list.setCurrentRow(0)
        self.assertTrue(dialog.refresh_catalog())
        self.assertIn(str(handlers.entry.context_length), dialog.context_label.text())
        self.assertIn(str(handlers.entry.max_output_tokens), dialog.output_label.text())
        dialog.model_list.setCurrentRow(0)
        self.assertTrue(dialog.download_selected())
        dialog.model_list.setCurrentRow(0)
        self.assertTrue(dialog.verify_selected())

        self.assertIn("Model verified.", dialog.status_label.text())


if __name__ == "__main__":
    unittest.main()
