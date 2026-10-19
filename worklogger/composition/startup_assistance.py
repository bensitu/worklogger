"""Compose startup guidance independently of the database and account session."""

from PySide6.QtWidgets import QDialog

from worklogger.infrastructure.database.paths import default_database_path
from worklogger.infrastructure.language_preferences import LanguagePreferences, initialize_language
from worklogger.infrastructure.logging import log_file_path
from worklogger.infrastructure.runtime_config import configuration_path
from worklogger.presentation.theme import ThemeEngine
from worklogger.presentation.widgets.startup_error import StartupErrorDialog


def offer_startup_retry(error, args) -> bool:
    from worklogger.bootstrap import _application

    application = _application(list(args))
    initialize_language(LanguagePreferences())
    ThemeEngine().apply_to(application)
    dialog = StartupErrorDialog(error, database_path=default_database_path(), log_path=log_file_path(),
                                configuration_path=configuration_path())
    try:
        return dialog.exec() == QDialog.DialogCode.Accepted
    finally:
        dialog.deleteLater()
