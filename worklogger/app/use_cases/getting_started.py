"""Account-scoped first-use guidance preferences."""

from worklogger.app.failures import storage_boundary
from worklogger.config.constants import GETTING_STARTED_PENDING_SETTING_KEY
from worklogger.domain.settings.repositories import SettingsRepository
from worklogger.domain.shared.result import Result


class GettingStartedService:
    def __init__(self, settings: SettingsRepository, *, user_id: int):
        self._settings = settings
        self._user_id = user_id

    @storage_boundary("settings_load_failed")
    def pending(self) -> Result[bool]:
        return Result.success(self._settings.get(self._user_id, GETTING_STARTED_PENDING_SETTING_KEY) == "1")

    @storage_boundary("settings_save_failed")
    def dismiss(self) -> Result[None]:
        self._settings.set(self._user_id, GETTING_STARTED_PENDING_SETTING_KEY, "0")
        return Result.success(None)
