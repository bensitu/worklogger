import os
import sys
import unittest
import locale
import tempfile


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_ROOT = os.path.join(PROJECT_ROOT, "worklogger")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from PySide6.QtWidgets import QApplication

from config.constants import SHOW_HOLIDAYS_SETTING_KEY
from data.db import DB
from services.app_services import AppServices
from ui.main_window import App
from utils.formatters import format_quick_logs
from utils.i18n import LANG_NAMES, LOCALE_CODE_MAP, get_translator, set_language


class LanguageTraversalCITests(unittest.TestCase):
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
        user_id = db.create_user("lang", "password")
        services.set_current_user(user_id)
        services.set_setting(SHOW_HOLIDAYS_SETTING_KEY, "0")
        return services

    def test_supported_languages_render_localized_ui_and_formatters(self):
        app = App(services=self._services())
        app.show()
        QApplication.processEvents()

        logs = [
            {"date": "2026-04-08", "time": "09:00", "description": "Task A"},
            {"date": "2026-04-08", "time": "10:00", "description": "Task B"},
            {"date": "2026-04-08", "time": "11:00", "description": "Task C"},
        ]

        for lang in LANG_NAMES:
            set_language(lang)
            app.lang = lang
            app.apply_lang()
            app.render()
            QApplication.processEvents()

            tr = get_translator(lang)
            self.assertEqual(app.lbl_wt.text(), tr.gettext("Work type"))

            options = [app.wt_combo.itemText(i) for i in range(app.wt_combo.count())]
            expected = [
                tr.gettext("Normal"),
                tr.gettext("Remote work"),
                tr.gettext("Business trip"),
                tr.gettext("Paid leave"),
                tr.gettext("Comp leave"),
                tr.gettext("Sick leave"),
            ]
            self.assertEqual(options, expected)

            text = format_quick_logs(logs, lang=lang, mode="summary")
            self.assertIn("2026-04-08", text)
            if lang == "en_US":
                self.assertIn("and", text)
            elif lang == "ja_JP":
                self.assertIn("対応", text)
            elif lang == "ko_KR":
                self.assertIn("작업", text)
            elif lang == "zh_CN":
                self.assertIn("主要处理了", text)
            elif lang == "zh_TW":
                self.assertIn("主要處理了", text)

            saved_locale = locale.setlocale(locale.LC_COLLATE)
            try:
                locale.setlocale(locale.LC_COLLATE, f"{LOCALE_CODE_MAP[lang]}.UTF-8")
            except locale.Error:
                pass
            words = ["beta", "alpha", "gamma"]
            sorted_words = sorted(words, key=locale.strxfrm)
            self.assertEqual(sorted_words[0], "alpha")
            locale.setlocale(locale.LC_COLLATE, saved_locale)

        app.close()
        app.deleteLater()
        QApplication.processEvents()


if __name__ == "__main__":
    unittest.main()

