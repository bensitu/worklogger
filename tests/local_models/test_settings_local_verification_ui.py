import os
import shutil
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QTabWidget


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_ROOT = os.path.join(PROJECT_ROOT, "worklogger")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from ui.dialogs.settings_dialog import SettingsDialog
from utils.i18n import set_language


class _FakeServices:
    def __init__(self):
        self._settings = {
            "local_model_enabled": "1",
            "ai_base_url": "",
            "ai_model": "",
            "show_holidays": "1",
            "show_note_markers": "1",
            "show_overnight_indicator": "1",
            "week_start_monday": "0",
        }
        self._secrets = {"ai_api_key": ""}

    def get_setting(self, key: str, default=None):
        return self._settings.get(key, default)

    def set_setting(self, key: str, value) -> None:
        self._settings[key] = str(value)

    def get_secret(self, key: str) -> str:
        return self._secrets.get(key, "")

    def set_secret(self, key: str, value: str) -> None:
        self._secrets[key] = value

    def _build_update_ssl_context(self):
        return "ssl-context"


class _FakeApp:
    def __init__(self):
        self.lang = "en_US"
        self.theme = "blue"
        self.dark = False
        self.work_hours = 8.0
        self.services = _FakeServices()

    def _safe_float_setting(self, _key: str, default: float) -> float:
        return default


class SettingsLocalVerificationUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._qt = QApplication.instance() or QApplication([])

    def setUp(self):
        set_language("en_US")
        SettingsDialog._session_local_verify_done = False
        SettingsDialog._session_local_verify_cache = {}
        self._models_dir = (
            Path(PROJECT_ROOT)
            / "tests"
            / "_artifacts"
            / "settings_local_models"
            / f"case_{uuid4().hex}"
        )
        self._models_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self._models_dir, ignore_errors=True)
        for filename in ("catalog.json", "manifest.json"):
            root_artifact = Path(PROJECT_ROOT) / filename
            if root_artifact.exists():
                root_artifact.unlink()

    @staticmethod
    def _switch_to_ai_tab(dlg: SettingsDialog) -> None:
        for tabs in dlg.findChildren(QTabWidget):
            for i in range(tabs.count()):
                if tabs.tabText(i) == "AI":
                    tabs.setCurrentIndex(i)
                    return
            if tabs.count() > 2:
                tabs.setCurrentIndex(2)
                return

    def test_download_disabled_with_inactive_local_model_and_no_file(self):
        app_ref = _FakeApp()
        app_ref.services.set_setting("local_model_enabled", "0")
        with patch("services.local_model_service.verify_model_file_with_reason", return_value=(False, "missing")) as mock_verify, \
             patch("services.local_model_service.get_active_entry_id", return_value="demo"), \
             patch("services.local_model_service.load_catalog", return_value=[]), \
             patch("services.local_model_service.get_models_dir", return_value=self._models_dir), \
             patch("services.local_model_service.localize_field", return_value=""), \
             patch("services.local_model_service.LocalModelService") as mock_local_service:
            mock_local_service.get.return_value.is_model_present.return_value = False
            dlg = SettingsDialog(app_ref)
            dlg.show()
            self._switch_to_ai_tab(dlg)
            QTest.qWait(220)
            QApplication.processEvents()
            self.assertFalse(dlg._local_dl_btn.isEnabled())
            self.assertIn("Local model is inactive", dlg._local_dl_btn.toolTip())
            mock_verify.assert_not_called()
            dlg.close()

    def test_select_change_disabled_with_inactive_switch_even_when_model_exists(self):
        app_ref = _FakeApp()
        app_ref.services.set_setting("local_model_enabled", "0")
        with patch("services.local_model_service.verify_model_file_with_reason", return_value=(True, "ok")) as mock_verify, \
             patch("services.local_model_service.get_active_entry_id", return_value="demo"), \
             patch("services.local_model_service.load_catalog", return_value=[{"id": "demo", "label": "Demo"}]), \
             patch("services.local_model_service.get_models_dir", return_value=self._models_dir), \
             patch("services.local_model_service.localize_field", return_value="Demo"), \
             patch("services.local_model_service.LocalModelService") as mock_local_service:
            mock_local_service.get.return_value.is_model_present.return_value = True
            dlg = SettingsDialog(app_ref)
            dlg.show()
            self._switch_to_ai_tab(dlg)
            QTest.qWait(220)
            QApplication.processEvents()
            self.assertNotEqual(dlg._local_dl_btn.text(), "Download")
            self.assertFalse(dlg._local_dl_btn.isEnabled())
            self.assertIn("Local model is inactive", dlg._local_dl_btn.toolTip())
            mock_verify.assert_not_called()
            dlg.close()

    def test_first_open_only_verifies_once_when_enabled(self):
        app_ref = _FakeApp()
        with patch("services.local_model_service.verify_model_file_with_reason", return_value=(True, "ok")) as mock_verify, \
             patch("services.local_model_service.get_active_entry_id", return_value="demo"), \
             patch("services.local_model_service.load_catalog", return_value=[{"id": "demo", "label": "Demo"}]), \
             patch("services.local_model_service.get_models_dir", return_value=self._models_dir), \
             patch("services.local_model_service.localize_field", return_value="Demo"), \
             patch("services.local_model_service.LocalModelService") as mock_local_service:
            mock_local_service.get.return_value.is_model_present.return_value = True
            dlg1 = SettingsDialog(app_ref)
            dlg1.show()
            self._switch_to_ai_tab(dlg1)
            QTest.qWait(260)
            QApplication.processEvents()
            dlg1.close()

            dlg2 = SettingsDialog(app_ref)
            dlg2.show()
            self._switch_to_ai_tab(dlg2)
            QTest.qWait(260)
            QApplication.processEvents()
            dlg2.close()

            self.assertEqual(mock_verify.call_count, 1)

    def test_ready_status_syncs_active_inactive_with_toggle(self):
        app_ref = _FakeApp()
        with patch("services.local_model_service.verify_model_file_with_reason", return_value=(True, "ok")) as mock_verify, \
             patch("services.local_model_service.get_active_entry_id", return_value="demo"), \
             patch("services.local_model_service.load_manifest", return_value=[{"id": "demo", "file": "demo.gguf", "sha256": "abc", "active": True}]), \
             patch("services.local_model_service.get_entry", return_value={"id": "demo", "file": "demo.gguf", "sha256": "abc", "active": True}), \
             patch("services.local_model_service.load_catalog", return_value=[{"id": "demo", "label": "Demo"}]), \
             patch("services.local_model_service.get_models_dir", return_value=self._models_dir), \
             patch("services.local_model_service.localize_field", return_value="Demo"), \
             patch("services.local_model_service.LocalModelService") as mock_local_service:
            mock_local_service.get.return_value.is_model_present.return_value = True
            dlg = SettingsDialog(app_ref)
            dlg.show()
            self._switch_to_ai_tab(dlg)
            QTest.qWait(280)
            QApplication.processEvents()

            self.assertIn("Ready", dlg._local_status_lbl.text())
            self.assertIn("Active", dlg._local_status_lbl.text())
            self.assertTrue(dlg._local_dl_btn.isEnabled())

            dlg._local_enabled_sw.setChecked(False)
            QTest.qWait(120)
            QApplication.processEvents()
            self.assertIn("Ready", dlg._local_status_lbl.text())
            self.assertIn("Inactive", dlg._local_status_lbl.text())
            self.assertFalse(dlg._local_dl_btn.isEnabled())

            dlg._local_enabled_sw.setChecked(True)
            QTest.qWait(120)
            QApplication.processEvents()
            self.assertIn("Ready", dlg._local_status_lbl.text())
            self.assertIn("Active", dlg._local_status_lbl.text())
            self.assertTrue(dlg._local_dl_btn.isEnabled())
            self.assertEqual(mock_verify.call_count, 1)
            dlg.close()

    def test_ready_status_labels_localized_for_supported_languages(self):
        expected_by_lang = {
            "en_US": ("Ready", "Active", "Inactive"),
            "zh_CN": ("已就绪", "已激活", "未激活"),
            "zh_TW": ("已就緒", "已啟用", "未啟用"),
            "ja_JP": ("準備完了", "有効", "無効"),
            "ko_KR": ("준비 완료", "활성", "비활성"),
        }
        with patch("services.local_model_service.verify_model_file_with_reason", return_value=(True, "ok")), \
             patch("services.local_model_service.get_active_entry_id", return_value="demo"), \
             patch("services.local_model_service.load_manifest", return_value=[{"id": "demo", "file": "demo.gguf", "sha256": "abc", "active": True}]), \
             patch("services.local_model_service.get_entry", return_value={"id": "demo", "file": "demo.gguf", "sha256": "abc", "active": True}), \
             patch("services.local_model_service.load_catalog", return_value=[{"id": "demo", "label": "Demo"}]), \
             patch("services.local_model_service.get_models_dir", return_value=self._models_dir), \
             patch("services.local_model_service.localize_field", return_value="Demo"), \
             patch("services.local_model_service.LocalModelService") as mock_local_service:
            mock_local_service.get.return_value.is_model_present.return_value = True
            for lang, (ready_text, active_text, inactive_text) in expected_by_lang.items():
                set_language(lang)
                SettingsDialog._session_local_verify_done = False
                SettingsDialog._session_local_verify_cache = {}
                app_ref = _FakeApp()
                app_ref.lang = lang
                dlg = SettingsDialog(app_ref)
                dlg.show()
                self._switch_to_ai_tab(dlg)
                QTest.qWait(280)
                QApplication.processEvents()
                self.assertIn(ready_text, dlg._local_status_lbl.text())
                self.assertIn(active_text, dlg._local_status_lbl.text())
                dlg._local_enabled_sw.setChecked(False)
                QTest.qWait(120)
                QApplication.processEvents()
                self.assertIn(ready_text, dlg._local_status_lbl.text())
                self.assertIn(inactive_text, dlg._local_status_lbl.text())
                dlg.close()

    def test_delete_model_updates_status_to_not_downloaded_within_500ms(self):
        app_ref = _FakeApp()
        state = {"present": True, "sha": "abc"}

        class _FakeMgmtDialog:
            def __init__(self, *_args, on_model_changed=None, **_kwargs):
                self._on_model_changed = on_model_changed

            def exec(self):
                state["present"] = False
                state["sha"] = ""
                if callable(self._on_model_changed):
                    self._on_model_changed("deleted", "demo")
                return QDialog.Rejected

        def _manifest_entry(_manifest: list, _entry_id: str):
            return {"id": "demo", "file": "demo.gguf", "sha256": state["sha"], "active": True}

        with patch("services.local_model_service.verify_model_file_with_reason", return_value=(True, "ok")), \
             patch("services.local_model_service.get_active_entry_id", return_value="demo"), \
             patch("services.local_model_service.load_manifest", return_value=[{"id": "demo", "file": "demo.gguf", "sha256": "abc", "active": True}]), \
             patch("services.local_model_service.get_entry", side_effect=_manifest_entry), \
             patch("services.local_model_service.load_catalog", return_value=[{"id": "demo", "label": "Demo"}]), \
             patch("services.local_model_service.get_models_dir", return_value=self._models_dir), \
             patch("services.local_model_service.localize_field", return_value="Demo"), \
             patch("services.local_model_service.refresh_catalog_from_remote", return_value=[{"id": "demo", "label": "Demo"}]), \
             patch("services.local_model_service.LocalModelService") as mock_local_service, \
             patch("ui.dialogs.local_model_dialogs.LocalDownloadDialog", new=_FakeMgmtDialog), \
             patch("services.download_controller.DownloadController.reset", return_value=None):
            mock_local_service.get.return_value.is_model_present.side_effect = lambda: state["present"]
            dlg = SettingsDialog(app_ref)
            dlg.show()
            self._switch_to_ai_tab(dlg)
            QTest.qWait(260)
            QApplication.processEvents()
            self.assertIn("Ready", dlg._local_status_lbl.text())
            self.assertTrue(dlg._local_dl_btn.isEnabled())

            started = time.perf_counter()
            dlg._local_dl_btn.click()
            deadline = started + 0.5
            synced = False
            while time.perf_counter() < deadline:
                QApplication.processEvents()
                if "Not downloaded" in dlg._local_status_lbl.text():
                    synced = True
                    break
                QTest.qWait(20)
            self.assertTrue(synced)
            self.assertIn("Not downloaded", dlg._local_status_lbl.text())
            self.assertNotIn("Ready", dlg._local_status_lbl.text())
            dlg.close()

    def test_catalog_refresh_failure_opens_cached_catalog_when_available(self):
        app_ref = _FakeApp()
        launched = {}
        cached_catalog = [{"id": "cached", "display_name": "Cached"}]

        class _FakeMgmtDialog:
            def __init__(self, *_args, catalog_override=None, **_kwargs):
                launched["catalog_override"] = catalog_override
                launched["created"] = True

            def exec(self):
                return QDialog.Rejected

        with patch("services.local_model_service.verify_model_file_with_reason", return_value=(False, "missing")), \
             patch("services.local_model_service.get_active_entry_id", return_value=""), \
             patch("services.local_model_service.load_catalog", return_value=[]), \
             patch("services.local_model_service.load_cached_catalog", return_value=cached_catalog), \
             patch("services.local_model_service.get_models_dir", return_value=self._models_dir), \
             patch("services.local_model_service.localize_field", return_value=""), \
             patch("services.local_model_service.refresh_catalog_from_remote", side_effect=OSError("network")), \
             patch("services.local_model_service.LocalModelService") as mock_local_service, \
             patch("ui.dialogs.local_model_dialogs.LocalDownloadDialog", new=_FakeMgmtDialog), \
             patch("PySide6.QtWidgets.QMessageBox.warning"):
            mock_local_service.get.return_value.is_model_present.return_value = False
            dlg = SettingsDialog(app_ref)
            dlg.show()
            self._switch_to_ai_tab(dlg)
            QTest.qWait(260)
            QApplication.processEvents()
            self.assertTrue(dlg._local_dl_btn.isEnabled())

            dlg._local_dl_btn.click()
            deadline = time.perf_counter() + 1.0
            while time.perf_counter() < deadline and not launched.get("created"):
                QApplication.processEvents()
                QTest.qWait(20)

            self.assertTrue(launched.get("created"))
            self.assertEqual(launched.get("catalog_override"), cached_catalog)
            dlg.close()

    def test_timeout_recovers_ui_within_10_seconds(self):
        app_ref = _FakeApp()
        with patch("services.local_model_service.verify_model_file_with_reason", return_value=(False, "timeout")), \
             patch("services.local_model_service.get_active_entry_id", return_value="demo"), \
             patch("services.local_model_service.load_catalog", return_value=[]), \
             patch("services.local_model_service.get_models_dir", return_value=self._models_dir), \
             patch("services.local_model_service.localize_field", return_value=""), \
             patch("services.local_model_service.LocalModelService") as mock_local_service:
            mock_local_service.get.return_value.is_model_present.return_value = True
            dlg = SettingsDialog(app_ref)
            dlg.show()
            self._switch_to_ai_tab(dlg)
            deadline = time.time() + 10.0
            while time.time() < deadline:
                QApplication.processEvents()
                if dlg._local_dl_btn.isEnabled():
                    break
                QTest.qWait(50)
            self.assertTrue(dlg._local_dl_btn.isEnabled())
            self.assertIn("timed out", dlg._local_status_lbl.text().lower())
            dlg.close()

    def test_cancel_verification_updates_progress_and_unblocks_button(self):
        app_ref = _FakeApp()

        def _slow_verify(*_args, progress_cb=None, cancel_event=None, **_kwargs):
            for pct in (10, 30, 55):
                if progress_cb is not None:
                    progress_cb(pct)
                time.sleep(0.04)
                if cancel_event is not None and cancel_event.is_set():
                    return False, "cancelled"
            while cancel_event is not None and not cancel_event.is_set():
                time.sleep(0.02)
            return False, "cancelled"

        with patch("services.local_model_service.verify_model_file_with_reason", side_effect=_slow_verify), \
             patch("services.local_model_service.get_active_entry_id", return_value="demo"), \
             patch("services.local_model_service.load_catalog", return_value=[]), \
             patch("services.local_model_service.get_models_dir", return_value=self._models_dir), \
             patch("services.local_model_service.localize_field", return_value=""), \
             patch("services.local_model_service.LocalModelService") as mock_local_service:
            mock_local_service.get.return_value.is_model_present.return_value = True
            dlg = SettingsDialog(app_ref)
            dlg.show()
            self._switch_to_ai_tab(dlg)
            QTest.qWait(120)
            QApplication.processEvents()
            self.assertGreaterEqual(dlg._local_verify_bar.value(), 10)
            dlg._local_verify_cancel_btn.click()
            deadline = time.time() + 5.0
            while time.time() < deadline:
                QApplication.processEvents()
                if dlg._local_dl_btn.isEnabled():
                    break
                QTest.qWait(40)
            self.assertTrue(dlg._local_dl_btn.isEnabled())
            self.assertIn("cancel", dlg._local_status_lbl.text().lower())
            dlg.close()


if __name__ == "__main__":
    unittest.main()
