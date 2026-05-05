import os
import sys
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_ROOT = os.path.join(PROJECT_ROOT, "worklogger")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from PySide6.QtWidgets import QApplication

from ui.dialogs.login_dialog import LoginDialog


class _FakeServices:
    auth = object()


class LoginDialogFocusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._qt = QApplication.instance() or QApplication([])

    def test_username_gets_initial_focus_and_login_is_default_button(self):
        dlg = LoginDialog(_FakeServices())
        dlg.show()
        QApplication.processEvents()

        self.assertIs(dlg.focusWidget(), dlg._username)
        self.assertTrue(dlg._login_btn.isDefault())
        self.assertFalse(dlg._register_btn.autoDefault())
        self.assertFalse(dlg._change_btn.autoDefault())
        self.assertFalse(dlg._reset_btn.autoDefault())


if __name__ == "__main__":
    unittest.main()

