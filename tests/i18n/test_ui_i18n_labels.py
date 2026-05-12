import os
import sys
import tempfile
import unittest
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_ROOT = os.path.join(PROJECT_ROOT, "worklogger")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from PySide6.QtWidgets import QApplication, QGroupBox, QLabel

from config.constants import SHOW_HOLIDAYS_SETTING_KEY
from data.db import DB
from services.app_services import AppServices
from ui.main_window import App
from ui.dialogs.settings_dialog import SettingsDialog
from utils.i18n import get_translator


class UILabelI18nTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._qt = QApplication.instance() or QApplication([])

    def _services(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        db = DB(path)
        self.addCleanup(db.conn.close)
        services = AppServices(db=db)
        user_id = db.create_user("ui", "password")
        services.set_current_user(user_id)
        services.set_setting(SHOW_HOLIDAYS_SETTING_KEY, "0")
        return services

    def test_main_window_work_type_label_and_options_are_localized(self):
        english_options = {
            "Normal",
            "Remote work",
            "Business trip",
            "Paid leave",
            "Comp leave",
            "Sick leave",
        }
        app = App(services=self._services())
        app.show()
        QApplication.processEvents()
        for lang in ("ja_JP", "ko_KR", "zh_TW"):
            app.lang = lang
            app.apply_lang()
            QApplication.processEvents()
            self.assertNotEqual(app.lbl_wt.text(), "Work type")
            options = {app.wt_combo.itemText(i) for i in range(app.wt_combo.count())}
            self.assertTrue(options)
            self.assertTrue(options.isdisjoint(english_options))
        app.close()
        app.deleteLater()
        QApplication.processEvents()

    def test_settings_about_update_text_is_localized(self):
        app = App(services=self._services())
        app.show()
        QApplication.processEvents()
        for lang in ("ja_JP", "ko_KR", "zh_TW"):
            app.lang = lang
            app.apply_lang()
            dlg = SettingsDialog(app)
            QApplication.processEvents()
            self.assertNotEqual(dlg._check_upd_btn.text(), "Check for Updates")
            dlg.close()
        app.close()
        app.deleteLater()
        QApplication.processEvents()

    def test_settings_about_check_update_uses_current_language_translator(self):
        app = App(services=self._services())
        app.show()
        QApplication.processEvents()

        app.lang = "en_US"
        app.apply_lang()
        dlg = SettingsDialog(app)
        with patch.object(app.services, "check_update_async") as mocked:
            dlg._check_update()
            translator = mocked.call_args.args[0]
            self.assertEqual(
                translator("You are on the latest version"),
                get_translator("en_US").gettext("You are on the latest version"),
            )
        dlg.close()

        app.lang = "ja_JP"
        app.apply_lang()
        dlg2 = SettingsDialog(app)
        with patch.object(app.services, "check_update_async") as mocked2:
            dlg2._check_update()
            translator2 = mocked2.call_args.args[0]
            self.assertEqual(
                translator2("You are on the latest version"),
                get_translator("ja_JP").gettext("You are on the latest version"),
            )
        dlg2.close()
        app.close()
        app.deleteLater()
        QApplication.processEvents()

    def test_settings_data_backup_copy_is_localized(self):
        app = App(services=self._services())
        app.show()
        QApplication.processEvents()

        for lang in ("ja_JP", "ko_KR", "zh_CN", "zh_TW"):
            app.lang = lang
            app.apply_lang()
            dlg = SettingsDialog(app)
            QApplication.processEvents()

            group_titles = {grp.title() for grp in dlg.findChildren(QGroupBox)}
            label_texts = {lbl.text() for lbl in dlg.findChildren(QLabel)}
            self.assertNotIn("Database Backup", group_titles)
            self.assertNotEqual(dlg._backup_db_btn.text(), "Backup Data")
            self.assertNotEqual(dlg._restore_db_btn.text(), "Restore Data")
            self.assertNotIn(
                "Back up your database regularly to protect your local work logs, reports, settings, and account data.",
                label_texts,
            )
            dlg.close()

        app.close()
        app.deleteLater()
        QApplication.processEvents()


if __name__ == "__main__":
    unittest.main()

