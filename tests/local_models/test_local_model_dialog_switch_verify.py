import os
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_ROOT = os.path.join(PROJECT_ROOT, "worklogger")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from ui.dialogs.local_model_dialogs import LocalDownloadDialog


def _localize_field(entry: dict, field: str, lang: str) -> str:
    value = entry.get(field, "")
    if isinstance(value, dict):
        return str(value.get(lang, ""))
    return str(value)


class LocalModelDialogSwitchVerifyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._qt = QApplication.instance() or QApplication([])

    def test_switch_model_verify_failure_blocks_close(self):
        base = Path(PROJECT_ROOT) / "tests" / "_artifacts" / "switch_verify_cases"
        base.mkdir(parents=True, exist_ok=True)
        models_dir = base / "case_verify_fail"
        shutil.rmtree(models_dir, ignore_errors=True)
        models_dir.mkdir(parents=True, exist_ok=True)
        try:
            model_file = models_dir / "demo.gguf"
            model_file.write_bytes(b"broken")

            catalog = [
                {
                    "id": "demo",
                    "display_name": "Demo",
                    "description": {"en_US": ""},
                    "estimated_size_mb": 1,
                    "min_ram_gb": 1,
                    "filename": "demo.gguf",
                }
            ]
            manifest = [{"id": "demo", "filename": "demo.gguf", "active": True}]

            with patch.object(LocalDownloadDialog, "_refresh_card_states", lambda _self: None), \
                 patch("services.local_model_service.ensure_catalog", return_value=None), \
                 patch("services.local_model_service.load_catalog", return_value=catalog), \
                 patch("services.local_model_service.get_active_entry_id", return_value="demo"), \
                 patch("services.local_model_service.localize_field", side_effect=_localize_field), \
                 patch("services.local_model_service.get_models_dir", return_value=models_dir), \
                 patch("services.local_model_service.load_manifest", return_value=manifest), \
                 patch("services.local_model_service.get_entry", return_value={"id": "demo", "filename": "demo.gguf"}), \
                 patch("services.local_model_service.verify_model_file_with_reason", return_value=(False, "hash_mismatch")) as mock_verify, \
                 patch("services.local_model_service.verify_model_file", return_value=False), \
                 patch("services.local_model_service.set_active_entry") as mock_set_active, \
                 patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warning:
                dlg = LocalDownloadDialog(None, "en_US")
                dlg.show()
                dlg._on_select_next()
                QApplication.processEvents()

                self.assertEqual(dlg.result(), 0)
                self.assertTrue(mock_warning.called)
                mock_set_active.assert_not_called()
                self.assertGreaterEqual(mock_verify.call_count, 1)
                dlg.close()
        finally:
            shutil.rmtree(models_dir, ignore_errors=True)

    def test_download_button_disabled_for_downloaded_selected_model(self):
        base = Path(PROJECT_ROOT) / "tests" / "_artifacts" / "switch_verify_cases"
        base.mkdir(parents=True, exist_ok=True)
        models_dir = base / "case_downloaded_selected"
        shutil.rmtree(models_dir, ignore_errors=True)
        models_dir.mkdir(parents=True, exist_ok=True)
        try:
            (models_dir / "demo.gguf").write_bytes(b"model")
            catalog = [
                {
                    "id": "demo",
                    "display_name": "Demo",
                    "description": {"en_US": ""},
                    "estimated_size_mb": 1,
                    "min_ram_gb": 1,
                    "filename": "demo.gguf",
                },
                {
                    "id": "fresh",
                    "display_name": "Fresh",
                    "description": {"en_US": ""},
                    "estimated_size_mb": 1,
                    "min_ram_gb": 1,
                    "filename": "fresh.gguf",
                },
            ]
            manifest = [
                {"id": "demo", "filename": "demo.gguf", "active": True},
                {"id": "fresh", "filename": "fresh.gguf", "active": False},
            ]

            with patch("services.local_model_service.ensure_catalog", return_value=None), \
                 patch("services.local_model_service.load_catalog", return_value=catalog), \
                 patch("services.local_model_service.get_active_entry_id", return_value="demo"), \
                 patch("services.local_model_service.localize_field", side_effect=_localize_field), \
                 patch("services.local_model_service.get_models_dir", return_value=models_dir), \
                 patch("services.local_model_service.load_manifest", return_value=manifest), \
                 patch("services.local_model_service.get_entry", side_effect=lambda _m, eid, **_kwargs: next(e for e in manifest if e["id"] == eid)), \
                 patch("services.local_model_service.verify_model_file", return_value=True):
                dlg = LocalDownloadDialog(None, "en_US")
                dlg.show()
                QApplication.processEvents()

                self.assertEqual(dlg._selected_entry_id(), "demo")
                self.assertFalse(dlg._sel_next_btn.isEnabled())

                dlg._card_widgets["fresh"]["radio"].setChecked(True)
                QApplication.processEvents()
                self.assertTrue(dlg._sel_next_btn.isEnabled())

                dlg.close()
        finally:
            shutil.rmtree(models_dir, ignore_errors=True)

    def test_download_button_disabled_for_empty_catalog_but_import_available(self):
        base = Path(PROJECT_ROOT) / "tests" / "_artifacts" / "switch_verify_cases"
        base.mkdir(parents=True, exist_ok=True)
        models_dir = base / "case_empty_catalog"
        shutil.rmtree(models_dir, ignore_errors=True)
        models_dir.mkdir(parents=True, exist_ok=True)
        try:
            with patch("services.local_model_service.ensure_catalog", return_value=None), \
                 patch("services.local_model_service.get_active_entry_id", return_value=""), \
                 patch("services.local_model_service.get_models_dir", return_value=models_dir), \
                 patch("services.local_model_service.load_manifest", return_value=[]):
                dlg = LocalDownloadDialog(None, "en_US", catalog_override=[])
                dlg.show()
                QApplication.processEvents()

                self.assertFalse(dlg._card_widgets)
                self.assertFalse(dlg._sel_next_btn.isEnabled())
                self.assertTrue(dlg._sel_import_btn.isEnabled())

                dlg.close()
        finally:
            shutil.rmtree(models_dir, ignore_errors=True)

    def test_download_click_ignored_when_selected_model_is_downloaded(self):
        base = Path(PROJECT_ROOT) / "tests" / "_artifacts" / "switch_verify_cases"
        base.mkdir(parents=True, exist_ok=True)
        models_dir = base / "case_download_click"
        shutil.rmtree(models_dir, ignore_errors=True)
        models_dir.mkdir(parents=True, exist_ok=True)
        try:
            (models_dir / "demo.gguf").write_bytes(b"model")
            catalog = [
                {
                    "id": "demo",
                    "display_name": "Demo",
                    "description": {"en_US": ""},
                    "estimated_size_mb": 1,
                    "min_ram_gb": 1,
                    "filename": "demo.gguf",
                }
            ]
            manifest = [{"id": "demo", "filename": "demo.gguf", "active": True}]

            with patch("services.local_model_service.ensure_catalog", return_value=None), \
                 patch("services.local_model_service.load_catalog", return_value=catalog), \
                 patch("services.local_model_service.get_active_entry_id", return_value="demo"), \
                 patch("services.local_model_service.localize_field", side_effect=_localize_field), \
                 patch("services.local_model_service.get_models_dir", return_value=models_dir), \
                 patch("services.local_model_service.load_manifest", return_value=manifest), \
                 patch("services.local_model_service.get_entry", return_value=manifest[0]), \
                 patch("services.download_controller.DownloadController.get") as mock_controller:
                dlg = LocalDownloadDialog(None, "en_US")
                dlg.show()
                QApplication.processEvents()

                self.assertFalse(dlg._sel_next_btn.isEnabled())
                QTest.mouseClick(dlg._sel_next_btn, Qt.LeftButton)
                QApplication.processEvents()

                mock_controller.assert_not_called()
                self.assertEqual(dlg._stack.currentIndex(), dlg.PAGE_SELECT)
                dlg.close()
        finally:
            shutil.rmtree(models_dir, ignore_errors=True)

    def test_delete_pruned_local_model_removes_card_from_list(self):
        base = Path(PROJECT_ROOT) / "tests" / "_artifacts" / "switch_verify_cases"
        base.mkdir(parents=True, exist_ok=True)
        models_dir = base / "case_delete_pruned"
        shutil.rmtree(models_dir, ignore_errors=True)
        models_dir.mkdir(parents=True, exist_ok=True)
        try:
            (models_dir / "demo.gguf").write_bytes(b"model")
            catalog = [
                {
                    "id": "demo",
                    "display_name": "Demo",
                    "description": {"en_US": ""},
                    "estimated_size_mb": 1,
                    "min_ram_gb": 1,
                    "filename": "demo.gguf",
                    "status": "local",
                }
            ]
            manifest = [{"id": "demo", "filename": "demo.gguf", "active": True}]
            catalog_state = {"models": list(catalog)}

            def _delete_model(_entry_id, **_kwargs):
                catalog_state["models"] = []

            with patch("services.local_model_service.ensure_catalog", return_value=None), \
                 patch("services.local_model_service.load_catalog", side_effect=lambda *_args, **_kwargs: list(catalog_state["models"])), \
                 patch("services.local_model_service.get_active_entry_id", return_value="demo"), \
                 patch("services.local_model_service.localize_field", side_effect=_localize_field), \
                 patch("services.local_model_service.get_models_dir", return_value=models_dir), \
                 patch("services.local_model_service.load_manifest", return_value=manifest), \
                 patch("services.local_model_service.get_entry", return_value=manifest[0]), \
                 patch("services.local_model_service.verify_model_file", return_value=True), \
                 patch("services.local_model_service.list_users_using_model", return_value=[]), \
                 patch("services.local_model_service.clear_active_model_id_for_user"), \
                 patch("services.local_model_service.LocalModelService.get") as mock_service_get, \
                 patch("services.local_model_service.LocalModelService.reset"), \
                 patch("PySide6.QtWidgets.QMessageBox.question", return_value=QMessageBox.Yes):
                mock_service_get.return_value.delete_model.side_effect = _delete_model

                dlg = LocalDownloadDialog(None, "en_US")
                dlg.show()
                QApplication.processEvents()
                self.assertIn("demo", dlg._card_widgets)

                dlg._delete_model("demo")
                QApplication.processEvents()

                self.assertNotIn("demo", dlg._card_widgets)
                self.assertIsNone(dlg._selected_entry_id())
                self.assertFalse(dlg._sel_next_btn.isEnabled())
                dlg.close()
        finally:
            shutil.rmtree(models_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
