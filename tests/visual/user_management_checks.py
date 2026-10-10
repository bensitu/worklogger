"""Opt-in rendering checks for account administration and update feedback."""

import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from tests.app.test_user_management_use_cases import MemoryAuthRepository
from tests.presentation.test_user_management_presentation import _view_model
from tests.presentation.test_settings_presentation import MemorySettingsRepository, _view_model as settings_model
from worklogger.infrastructure.i18n import _, available_languages, get_language, set_language
from worklogger.presentation.settings import SettingsPage
from worklogger.presentation.theme import configure_application_style, install_bundled_fonts
from worklogger.presentation.theme.theme_engine import ThemeEngine
from worklogger.presentation.user_management import UserManagementDialog
from worklogger.presentation.viewmodels.user_management import UserListItem, UserManagementState


class AccountLayoutChecks(unittest.TestCase):
    def test_account_groups_separate_personal_actions_from_administration(self):
        from PySide6.QtWidgets import QLabel
        from worklogger.domain.auth.models import User
        for language in available_languages():
            set_language(language)
            for dark in (False, True):
                self.apply_theme(dark)
                for is_admin in (False, True):
                    page = SettingsPage(settings_model(MemorySettingsRepository()))
                    page.refresh()
                    page.set_account(User(1, "login-id", is_admin=is_admin, display_name="Mary"))
                    page.category_nav.set_category("account")
                    page.resize(880, 680)
                    page.show()
                    self.app.processEvents()
                    account = page.category_stack.currentWidget()
                    titles = [label for label in account.findChildren(QLabel, "settings_section_title_label") if label.isVisible()]
                    expected = [_("Personal profile"), _("Sign-in and security")]
                    if is_admin:
                        expected.append(_("User administration"))
                    self.assertEqual([label.text() for label in titles], expected)
                    self.assertEqual(page.account_administration_frame.isHidden(), not is_admin)
                    self.assertEqual(page.manage_users_button.isEnabled(), is_admin)
                    for index, title in enumerate(titles):
                        frame = title.parentWidget()
                        self.assertLessEqual(frame.width(), account.viewport().width())
                        self.assertTrue(frame.rect().contains(title.geometry()))
                        account.ensureWidgetVisible(frame)
                        self.app.processEvents()
                        self.capture(page, f"{language}-account-{is_admin}-{dark}-group-{index}")
                    page.close()
                    page.deleteLater()

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        configure_application_style()
        install_bundled_fonts()

    def setUp(self):
        self.language, self.stylesheet, self.palette = get_language(), self.app.styleSheet(), self.app.palette()
        self.engine = ThemeEngine()

    def tearDown(self):
        set_language(self.language)
        self.app.setPalette(self.palette)
        self.app.setStyleSheet(self.stylesheet)

    def apply_theme(self, dark):
        self.app.setPalette(self.engine.qt_palette(dark=dark))
        self.app.setStyleSheet(self.engine.application_stylesheet(dark=dark))

    def test_user_operations_fit_compact_and_large_windows(self):
        for language in available_languages():
            set_language(language)
            for dark in (False, True):
                self.apply_theme(dark)
                dialog = UserManagementDialog(_view_model(MemoryAuthRepository(), 1))
                try:
                    dialog.set_state(UserManagementState((
                        UserListItem(1, "admin", True, False),
                        UserListItem(2, "alex.morgan", False, True),
                        UserListItem(3, "avery.long.account.name", False, False))))
                    dialog.show()
                    for width, height in ((860, 540), (1100, 660)):
                        dialog.resize(width, height)
                        self.app.processEvents()
                        self.assertEqual((dialog.width(), dialog.height()), (width, height))
                        self.assertEqual(dialog.user_table.horizontalScrollBar().maximum(), 0)
                        dialog.user_table.selectRow(1)
                        dialog._show_recovery_key("example-recovery-key-" + "x" * 48)
                        dialog.status_label.setText(_("User updated."))
                        for tab in (0, 1):
                            dialog.operation_tabs.setCurrentIndex(tab)
                            self.app.processEvents()
                            self.assertEqual((dialog.width(), dialog.height()), (width, height))
                            for widget in (dialog.user_table, dialog.close_button, dialog.new_user_button,
                                           dialog.selected_user_label, dialog.password_change_checkbox,
                                           dialog.reset_password_input, dialog.reset_confirm_input,
                                           dialog.reset_password_button, dialog.delete_user_button,
                                           dialog.username_input, dialog.create_password_input,
                                           dialog.create_confirm_input, dialog.create_user_button,
                                           dialog.recovery_key_label, dialog.credential_actions.copy_button,
                                           dialog.credential_actions.save_button, dialog.credential_done_button):
                                if widget.isVisible():
                                    rect = widget.rect().translated(widget.mapTo(dialog, QPoint()))
                                    self.assertTrue(dialog.rect().contains(rect), (language, width, tab, widget))
                                    self.assertTrue(widget.parentWidget().rect().contains(widget.geometry()),
                                                    (language, width, tab, widget))
                            if tab == 0 and dialog.reset_fields.isVisible():
                                self.assertLess(dialog.reset_password_input.geometry().bottom(),
                                                dialog.reset_confirm_input.geometry().top())
                            self.capture(dialog, f"{language}-users-{'dark' if dark else 'light'}-{width}-{tab}")
                finally:
                    dialog.hide()
                    dialog.deleteLater()

    def test_update_feedback_preserves_about_content_positions(self):
        from PySide6.QtWidgets import QLabel
        for language in available_languages():
            set_language(language)
            for dark in (False, True):
                self.apply_theme(dark)
                page = SettingsPage(settings_model(MemorySettingsRepository()))
                try:
                    page.refresh()
                    page.category_nav.set_category("about")
                    page.show()
                    about = page.category_stack.currentWidget()
                    self.assertFalse(about.findChildren(QLabel, "settings_section_title_label"))
                    icon = page.findChild(QLabel, "about_icon_label")
                    for width, height in ((880, 580), (1100, 700)):
                        page.resize(width, height)
                        self.app.processEvents()
                        widgets = (icon, page.about_name_label, page.about_version_label, page.about_author_label,
                                   page.about_license_label, page.about_url_label, page.check_updates_button)
                        positions = tuple(widget.mapTo(page, QPoint()) for widget in widgets)
                        icon_image = icon.grab().toImage()
                        for checking, message in ((True, _("Checking for updates...")), (False, _("You are using the latest version.")),
                                                  (False, _("Unable to check for updates.")), (False, "")):
                            page.set_busy("update", checking)
                            page.check_updates_button.setEnabled(not checking)
                            page.set_operation_status(message, "update")
                            self.app.processEvents()
                            self.assertTrue(icon.isEnabled())
                            self.assertEqual(icon.grab().toImage(), icon_image)
                            self.assertEqual(tuple(widget.mapTo(page, QPoint()) for widget in widgets), positions,
                                             (language, dark, width, message))
                            self.assertFalse(page.update_status_label.isHidden())
                            self.assertEqual(page.category_stack.currentWidget().horizontalScrollBar().maximum(), 0)
                        page.set_operation_status(_("You are using the latest version."), "update")
                        self.app.processEvents()
                        self.capture(page, f"{language}-about-feedback-{'dark' if dark else 'light'}-{width}")
                finally:
                    page.hide()
                    page.deleteLater()

    def capture(self, widget, name):
        directory = os.environ.get("WORKLOGGER_SCREENSHOTS")
        if directory:
            path = Path(directory)
            path.mkdir(parents=True, exist_ok=True)
            self.assertTrue(widget.grab().save(str(path / f"{name}.png")))
