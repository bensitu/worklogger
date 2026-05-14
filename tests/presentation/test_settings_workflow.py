from __future__ import annotations

from pathlib import Path
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QWidget

from worklogger.app.use_cases.settings import GetSettingHandler, SetSettingHandler
from worklogger.app.use_cases.updates import UpdateCheckResult
from worklogger.domain.auth.models import User
from worklogger.domain.shared.result import Result
from worklogger.presentation.auth import ChangePasswordDialog
from worklogger.presentation.settings import SettingsWorkflowController
from worklogger.presentation.viewmodels import (
    DataManagementActionState,
    SettingsViewModel,
)


def _app() -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        return existing
    return QApplication([])


class MemorySettingsRepository:
    def __init__(self) -> None:
        self.values: dict[tuple[int, str], str] = {}

    def get(self, user_id: int, key: str, default: str | None = None) -> str | None:
        return self.values.get((user_id, key), default)

    def set(self, user_id: int, key: str, value: str) -> None:
        self.values[(user_id, key)] = value

    def delete(self, user_id: int, key: str) -> None:
        self.values.pop((user_id, key), None)


class FakeAuthViewModel:
    def __init__(self) -> None:
        self.changes: list[tuple[int, str, str, str]] = []

    def change_password(
        self,
        *,
        user_id: int,
        current_password: str,
        new_password: str,
        password_confirm: str,
    ) -> Result[str]:
        self.changes.append(
            (user_id, current_password, new_password, password_confirm)
        )
        return Result.success("RECOVERY-KEY")


class FakeRememberStore:
    def __init__(self) -> None:
        self.cleared = 0

    def load_token(self) -> Result[str | None]:
        return Result.success(None)

    def save_token(self, token: str) -> Result[None]:
        return Result.success(None)

    def clear_token(self) -> Result[None]:
        self.cleared += 1
        return Result.success(None)


class FakeDataManagementViewModel:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Path]] = []
        self.existing_calendar_events = 0

    def backup_database(self, destination: Path) -> Result[DataManagementActionState]:
        self.calls.append(("backup", Path(destination)))
        return Result.success(
            DataManagementActionState(
                action="backup",
                path=Path(destination),
                message="backup_saved",
            )
        )

    def validate_restore_database(self, source: Path) -> Result[DataManagementActionState]:
        self.calls.append(("validate", Path(source)))
        return Result.success(
            DataManagementActionState(
                action="restore_validate",
                path=Path(source),
                message="restore_valid",
            )
        )

    def restore_database(self, source: Path) -> Result[DataManagementActionState]:
        self.calls.append(("restore", Path(source)))
        return Result.success(
            DataManagementActionState(
                action="restore",
                path=Path(source),
                message="restore_complete",
            )
        )

    def export_csv(self, destination: Path) -> Result[DataManagementActionState]:
        self.calls.append(("csv", Path(destination)))
        return Result.success(
            DataManagementActionState(
                action="export_csv",
                path=Path(destination),
                record_count=2,
                message="csv_exported",
            )
        )

    def import_csv(self, source: Path) -> Result[DataManagementActionState]:
        self.calls.append(("csv_import", Path(source)))
        return Result.success(
            DataManagementActionState(
                action="import_csv",
                path=Path(source),
                record_count=4,
                message="csv_imported",
            )
        )

    def export_ics(self, destination: Path) -> Result[DataManagementActionState]:
        self.calls.append(("ics", Path(destination)))
        return Result.success(
            DataManagementActionState(
                action="export_ics",
                path=Path(destination),
                record_count=1,
                message="ics_exported",
            )
        )

    def calendar_event_count(self) -> Result[int]:
        return Result.success(self.existing_calendar_events)

    def import_ics(
        self,
        source: Path,
        *,
        replace_existing: bool,
    ) -> Result[DataManagementActionState]:
        action = "ics_import_replace" if replace_existing else "ics_import_append"
        self.calls.append((action, Path(source)))
        return Result.success(
            DataManagementActionState(
                action="import_ics",
                path=Path(source),
                record_count=3,
                message="ics_imported",
            )
        )


class FakeUpdateCheckHandler:
    def __init__(self, latest: str | None = "4.0.1") -> None:
        self.latest = latest
        self.queries: list[object] = []

    def handle(self, query) -> Result[UpdateCheckResult]:
        self.queries.append(query)
        return Result.success(
            UpdateCheckResult(
                current_version=query.current_version,
                latest_version=self.latest,
                update_available=self.latest is not None,
            )
        )


class ScriptedChangePasswordDialog(ChangePasswordDialog):
    def exec(self) -> int:
        self.current_password_input.setText("oldsecret123")
        self.password_input.setText("newsecret123")
        self.confirm_input.setText("newsecret123")
        self.change_button.click()
        self.change_button.click()
        return int(QDialog.DialogCode.Accepted)


def _settings_view_model(repository: MemorySettingsRepository) -> SettingsViewModel:
    return SettingsViewModel(
        user_id=1,
        get_handler=GetSettingHandler(repository),
        set_handler=SetSettingHandler(repository),
    )


class SettingsWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = _app()

    def test_settings_workflow_handles_change_password_and_clears_session(self) -> None:
        auth = FakeAuthViewModel()
        remember_store = FakeRememberStore()
        notifications: list[tuple[str, str]] = []
        controller = SettingsWorkflowController(
            settings_view_model=_settings_view_model(MemorySettingsRepository()),
            auth_view_model=auth,
            user=User(id=1, username="alice", is_admin=True),
            data_management_view_model=FakeDataManagementViewModel(),
            remember_session_store=remember_store,
            change_password_dialog_factory=ScriptedChangePasswordDialog,
            notify_success=lambda _parent, title, message: notifications.append((title, message)),
            notify_error=lambda _parent, title, message: notifications.append((title, message)),
        )
        dialog = controller.create_dialog()

        dialog.change_password_button.click()

        self.assertEqual(
            auth.changes,
            [(1, "oldsecret123", "newsecret123", "newsecret123")],
        )
        self.assertEqual(remember_store.cleared, 1)
        self.assertEqual(
            notifications,
            [("Change password", "Password changed successfully.")],
        )

    def test_settings_workflow_runs_data_actions_with_paths_and_restore_reload(self) -> None:
        data = FakeDataManagementViewModel()
        updates = FakeUpdateCheckHandler()
        notifications: list[tuple[str, str]] = []
        reloads: list[bool] = []
        controller = SettingsWorkflowController(
            settings_view_model=_settings_view_model(MemorySettingsRepository()),
            auth_view_model=FakeAuthViewModel(),
            user=User(id=1, username="alice", is_admin=True),
            data_management_view_model=data,
            update_check_handler=updates,
            backup_destination_provider=lambda _parent: Path("backup.db"),
            restore_source_provider=lambda _parent: Path("backup.db"),
            csv_destination_provider=lambda _parent: Path("worklog.csv"),
            csv_source_provider=lambda _parent: Path("import.csv"),
            ics_source_provider=lambda _parent: Path("calendar.ics"),
            ics_destination_provider=lambda _parent: Path("worklog.ics"),
            restore_confirmation=lambda _parent: True,
            notify_success=lambda _parent, title, message: notifications.append((title, message)),
            notify_error=lambda _parent, title, message: notifications.append((title, message)),
            reload_after_restore=lambda: reloads.append(True),
        )
        dialog = controller.create_dialog()

        dialog.backup_button.click()
        dialog.export_csv_button.click()
        dialog.import_csv_button.click()
        dialog.import_ics_button.click()
        dialog.export_ics_button.click()
        dialog.check_updates_button.click()
        dialog.restore_button.click()

        self.assertEqual(
            data.calls,
            [
                ("backup", Path("backup.db")),
                ("csv", Path("worklog.csv")),
                ("csv_import", Path("import.csv")),
                ("ics_import_append", Path("calendar.ics")),
                ("ics", Path("worklog.ics")),
                ("validate", Path("backup.db")),
                ("restore", Path("backup.db")),
            ],
        )
        self.assertEqual(reloads, [True])
        self.assertEqual(
            notifications,
            [
                ("Backup Data", "Backup saved: backup.db"),
                ("Export CSV", "Exported 2 records."),
                ("Import CSV", "Imported 4 records."),
                ("Import .ics", "Imported 3 calendar events."),
                ("Export .ics", "Exported 1 events."),
                ("Check for updates", "Update available: 4.0.1"),
                ("Restore Data", "Data restored successfully."),
            ],
        )
        self.assertEqual(dialog.status_label.text(), "Data restored successfully.")

    def test_settings_workflow_cancels_restore_before_adapter_call(self) -> None:
        data = FakeDataManagementViewModel()
        controller = SettingsWorkflowController(
            settings_view_model=_settings_view_model(MemorySettingsRepository()),
            auth_view_model=FakeAuthViewModel(),
            user=User(id=1, username="alice", is_admin=True),
            data_management_view_model=data,
            restore_source_provider=lambda _parent: Path("backup.db"),
            restore_confirmation=lambda _parent: False,
            notify_success=lambda _parent, _title, _message: None,
            notify_error=lambda _parent, _title, _message: None,
        )
        dialog = controller.create_dialog()

        dialog.restore_button.click()

        self.assertEqual(data.calls, [("validate", Path("backup.db"))])
        self.assertEqual(dialog.status_label.text(), "Restore cancelled")

    def test_settings_workflow_import_ics_replace_or_cancel(self) -> None:
        data = FakeDataManagementViewModel()
        data.existing_calendar_events = 2
        notifications: list[tuple[str, str]] = []
        controller = SettingsWorkflowController(
            settings_view_model=_settings_view_model(MemorySettingsRepository()),
            auth_view_model=FakeAuthViewModel(),
            user=User(id=1, username="alice", is_admin=True),
            data_management_view_model=data,
            ics_source_provider=lambda _parent: Path("calendar.ics"),
            ics_import_mode_provider=lambda _parent: True,
            notify_success=lambda _parent, title, message: notifications.append((title, message)),
            notify_error=lambda _parent, title, message: notifications.append((title, message)),
        )
        dialog = controller.create_dialog()

        dialog.import_ics_button.click()

        self.assertEqual(data.calls, [("ics_import_replace", Path("calendar.ics"))])
        self.assertEqual(notifications, [("Import .ics", "Imported 3 calendar events.")])

        cancelled = FakeDataManagementViewModel()
        cancelled.existing_calendar_events = 2
        controller = SettingsWorkflowController(
            settings_view_model=_settings_view_model(MemorySettingsRepository()),
            auth_view_model=FakeAuthViewModel(),
            user=User(id=1, username="alice", is_admin=True),
            data_management_view_model=cancelled,
            ics_source_provider=lambda _parent: Path("calendar.ics"),
            ics_import_mode_provider=lambda _parent: None,
            notify_success=lambda _parent, _title, _message: None,
            notify_error=lambda _parent, _title, _message: None,
        )
        dialog = controller.create_dialog()

        dialog.import_ics_button.click()

        self.assertEqual(cancelled.calls, [])
        self.assertEqual(dialog.status_label.text(), "Import cancelled")


if __name__ == "__main__":
    unittest.main()
