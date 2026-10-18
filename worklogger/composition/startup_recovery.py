"""Database startup recovery composed independently of account sign-in."""

from PySide6.QtWidgets import QDialog

from worklogger.app.use_cases.startup_database import RecoverStartupDatabaseHandler
from worklogger.infrastructure.database.paths import default_database_path
from worklogger.infrastructure.database.startup_recovery import SQLiteStartupDatabase
from worklogger.infrastructure.language_preferences import LanguagePreferences, initialize_language
from worklogger.infrastructure.runtime_config import load_runtime_configuration
from worklogger.presentation.theme import ThemeEngine
from worklogger.presentation.widgets.database_startup import DatabaseStartupDialog


def recover_startup_database(error, args) -> bool:
    from worklogger.bootstrap import _application

    application = _application(list(args))
    initialize_language(LanguagePreferences())
    ThemeEngine().apply_to(application)
    path = default_database_path()
    handler = RecoverStartupDatabaseHandler(SQLiteStartupDatabase(path),
        allow_new_database=load_runtime_configuration().features.self_registration)
    dialog = DatabaseStartupDialog(path, error, handler)
    try:
        return dialog.exec() == QDialog.DialogCode.Accepted
    finally:
        dialog.deleteLater()
