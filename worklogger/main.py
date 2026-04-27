"""WorkLogger — entry point."""

import sys

# Windows needs the AppUserModelID before QApplication for the taskbar icon.
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "dev.worklogger.app.v1")
    except Exception:
        pass

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from config.constants import FORCE_PASSWORD_CHANGE_SETTING_KEY
from services.app_services import AppServices
from services.session_store import (
    clear_remember_token,
    load_remember_session,
    save_remember_token,
)
from services.language_manager import get_language_manager
from utils.icon import make_icon
from utils.logging_config import configure_logging
from ui.main_window import App
from ui.dialogs import (
    ChangePasswordDialog,
    LoginDialog,
    RegisterDialog,
    ResetPasswordDialog,
)
from utils.i18n import _, get_language


def _bootstrap() -> None:
    """Run one-time setup tasks before the Qt app starts.

    Called once at process start, before ``QApplication`` is created.
    Errors are silently swallowed — bootstrap failures must never prevent
    the app from launching.
    """
    try:
        configure_logging()
    except Exception:
        pass
    try:
        # Ensure catalog.json is present in the user's models directory.
        # On a frozen (PyInstaller) first run the file lives only inside
        # sys._MEIPASS and must be copied out to the persistent location.
        from services.local_model_service import ensure_catalog
        ensure_catalog()
    except Exception:
        pass


def main():
    _bootstrap()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    get_language_manager().apply(get_language())
    icon = make_icon()
    app.setWindowIcon(icon)
    services = AppServices()

    if authenticate(services) is None:
        sys.exit(0)
    if not _force_password_change_if_needed(services):
        sys.exit(0)

    initial_lang = services.resolve_initial_language()
    get_language_manager().apply(initial_lang)
    w = App(services=services, initial_lang=initial_lang)
    w.setWindowIcon(icon)
    w.show()
    sys.exit(app.exec())


def authenticate(services: AppServices | None = None) -> int | None:
    services = services or AppServices()
    remember_session = load_remember_session()
    if remember_session and remember_session.token:
        user_id = services.auth.login_with_token(remember_session.token)
        if user_id is not None:
            services.set_current_user(user_id)
            if (
                not remember_session.username
                and services.current_username
                and remember_session.token
            ):
                try:
                    save_remember_token(
                        services.current_username,
                        remember_session.token,
                    )
                except Exception:
                    pass
            return user_id
        clear_remember_token(remember_session.username or None)

    if services.db.user_count() == 0:
        QMessageBox.information(
            None,
            _("Register"),
            _("No accounts found. Please create an administrator account."),
        )
        register = RegisterDialog(services.auth)
        if register.exec() != QDialog.Accepted:
            return None

    login = LoginDialog(services)

    def _open_register() -> None:
        dlg = RegisterDialog(services.auth, login)
        if dlg.exec() == QDialog.Accepted and dlg.username:
            login.set_username(dlg.username)

    def _open_change_password() -> None:
        dlg = ChangePasswordDialog(
            services.auth,
            username=login.current_username(),
            parent=login,
        )
        dlg.exec()

    def _open_reset_password() -> None:
        dlg = ResetPasswordDialog(
            services.auth,
            username=login.current_username(),
            parent=login,
        )
        dlg.exec()

    login.register_requested.connect(_open_register)
    login.change_password_requested.connect(_open_change_password)
    login.reset_password_requested.connect(_open_reset_password)
    if login.exec() != QDialog.Accepted or login.user_id is None:
        return None
    services.set_current_user(login.user_id, login.username)
    return login.user_id


def _force_password_change_if_needed(services: AppServices) -> bool:
    if services.get_setting(FORCE_PASSWORD_CHANGE_SETTING_KEY, "0") != "1":
        return True
    QMessageBox.information(
        None,
        _("Change Password"),
        _("The default administrator password must be changed before continuing."),
    )
    dlg = ChangePasswordDialog(
        services.auth,
        current_user_id=services.current_user_id,
    )
    return dlg.exec() == QDialog.Accepted


if __name__ == "__main__":
    main()
