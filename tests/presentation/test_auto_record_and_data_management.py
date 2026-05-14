from __future__ import annotations

from datetime import date, datetime
import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from worklogger.app.use_cases.settings import GetSettingHandler, SetSettingHandler
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkLog, WorkType
from PySide6.QtWidgets import QApplication

from worklogger.app.use_cases.data_portability import WorkLogCsvImportResult
from worklogger.presentation.shell import (
    QtResidencyController,
    ResidencyViewModel,
    residency_setting_key,
)
from worklogger.presentation.viewmodels import (
    AutoRecordViewModel,
    DataManagementViewModel,
)


class StaticRowsHandler:
    def __init__(self, rows: tuple[WorkLog, ...]) -> None:
        self.rows = rows
        self.queries: list[object] = []

    def handle(self, query):
        self.queries.append(query)
        return Result.success(self.rows)


class FakeBackupService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Path]] = []

    def backup_database(self, destination: Path) -> Result[Path]:
        self.calls.append(("backup", Path(destination)))
        return Result.success(Path(destination))

    def validate_restore_database(self, source: Path) -> Result[None]:
        self.calls.append(("validate", Path(source)))
        return Result.success(None)

    def restore_database(self, source: Path) -> Result[None]:
        self.calls.append(("restore", Path(source)))
        return Result.success(None)


class FakeCsvExporter:
    def __init__(self) -> None:
        self.rows: tuple[WorkLog, ...] = ()

    def export_work_logs(self, destination: Path, rows) -> Result[Path]:
        self.rows = tuple(rows)
        return Result.success(Path(destination))


class FakeCsvImporter:
    def __init__(self) -> None:
        self.source: Path | None = None

    def handle(self, command) -> Result[WorkLogCsvImportResult]:
        self.source = Path(command.source_path)
        return Result.success(WorkLogCsvImportResult(imported_count=3))


class FakeIcsExporter:
    def __init__(self) -> None:
        self.rows: tuple[WorkLog, ...] = ()

    def write_work_logs(self, destination: Path, rows) -> Result[Path]:
        self.rows = tuple(rows)
        return Result.success(Path(destination))


class MemorySettingsRepository:
    def __init__(self) -> None:
        self.values: dict[tuple[int, str], str] = {}

    def get(self, user_id: int, key: str, default: str | None = None) -> str | None:
        return self.values.get((user_id, key), default)

    def set(self, user_id: int, key: str, value: str) -> None:
        self.values[(user_id, key)] = value

    def delete(self, user_id: int, key: str) -> None:
        self.values.pop((user_id, key), None)


class AutoRecordDataManagementPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_auto_record_tracks_start_break_finish_and_draft(self) -> None:
        view_model = AutoRecordViewModel(default_break_hours=1.0)

        started = view_model.start(
            datetime(2026, 4, 20, 9, 0),
            note="Focused work",
            work_type=WorkType.REMOTE.value,
        )
        self.assertTrue(started.ok, started.error)
        assert started.value is not None
        self.assertEqual(started.value.start_time, "09:00")
        self.assertEqual(started.value.break_hours, 1.0)

        break_started = view_model.restart_break(datetime(2026, 4, 20, 12, 0))
        self.assertTrue(break_started.ok, break_started.error)
        assert break_started.value is not None
        self.assertTrue(break_started.value.break_active)

        break_ended = view_model.end_break(datetime(2026, 4, 20, 12, 31))
        self.assertTrue(break_ended.ok, break_ended.error)
        assert break_ended.value is not None
        self.assertEqual(break_ended.value.break_hours, 0.5)

        finished = view_model.finish(datetime(2026, 4, 20, 18, 0))

        self.assertTrue(finished.ok, finished.error)
        assert finished.value is not None
        self.assertEqual(finished.value.day, date(2026, 4, 20))
        self.assertEqual(finished.value.start_time, "09:00")
        self.assertEqual(finished.value.end_time, "18:00")
        self.assertEqual(finished.value.break_hours, 0.5)
        self.assertEqual(finished.value.note, "Focused work")
        self.assertEqual(finished.value.work_type, WorkType.REMOTE.value)

    def test_auto_record_can_continue_existing_break_and_add_quick_break(self) -> None:
        view_model = AutoRecordViewModel(default_break_hours=0.0)
        loaded = view_model.load_existing(
            day=date(2026, 4, 20),
            start_time="09:00",
            end_time=None,
            break_hours=0.5,
            note="",
            work_type=WorkType.NORMAL.value,
        )
        self.assertTrue(loaded.ok, loaded.error)

        continued = view_model.continue_break(datetime(2026, 4, 20, 13, 0))
        self.assertTrue(continued.ok, continued.error)
        ended = view_model.end_break(datetime(2026, 4, 20, 13, 30))
        self.assertTrue(ended.ok, ended.error)
        assert ended.value is not None
        self.assertEqual(ended.value.break_hours, 1.0)

        quick = view_model.add_quick_break(15)

        self.assertTrue(quick.ok, quick.error)
        assert quick.value is not None
        self.assertEqual(quick.value.break_hours, 1.25)

    def test_data_management_viewmodel_delegates_backup_restore_and_exports(self) -> None:
        row = WorkLog(
            user_id=1,
            day=date(2026, 4, 20),
            start_time="09:00",
            end_time="18:00",
            break_hours=1.0,
            note="Focused work",
            work_type=WorkType.NORMAL,
        )
        rows = StaticRowsHandler((row,))
        backup = FakeBackupService()
        csv_exporter = FakeCsvExporter()
        csv_importer = FakeCsvImporter()
        ics_exporter = FakeIcsExporter()
        view_model = DataManagementViewModel(
            user_id=1,
            work_logs_handler=rows,
            backup_service=backup,
            csv_exporter=csv_exporter,
            ics_exporter=ics_exporter,
            csv_import_handler=csv_importer,
        )

        backed_up = view_model.backup_database(Path("backup.db"))
        validated = view_model.validate_restore_database(Path("backup.db"))
        restored = view_model.restore_database(Path("backup.db"))
        csv = view_model.export_csv(Path("worklog.csv"))
        imported_csv = view_model.import_csv(Path("import.csv"))
        ics = view_model.export_ics(Path("worklog.ics"))

        self.assertTrue(backed_up.ok, backed_up.error)
        self.assertTrue(validated.ok, validated.error)
        self.assertTrue(restored.ok, restored.error)
        self.assertTrue(csv.ok, csv.error)
        self.assertTrue(imported_csv.ok, imported_csv.error)
        self.assertTrue(ics.ok, ics.error)
        assert csv.value is not None
        assert ics.value is not None
        self.assertEqual(csv.value.record_count, 1)
        assert imported_csv.value is not None
        self.assertEqual(imported_csv.value.record_count, 3)
        self.assertEqual(ics.value.record_count, 1)
        self.assertEqual(csv_exporter.rows, (row,))
        self.assertEqual(csv_importer.source, Path("import.csv"))
        self.assertEqual(ics_exporter.rows, (row,))
        self.assertEqual(
            backup.calls,
            [
                ("backup", Path("backup.db")),
                ("validate", Path("backup.db")),
                ("restore", Path("backup.db")),
            ],
        )

    def test_residency_viewmodel_uses_platform_specific_setting(self) -> None:
        repository = MemorySettingsRepository()
        view_model = ResidencyViewModel(
            user_id=1,
            get_handler=GetSettingHandler(repository),
            set_handler=SetSettingHandler(repository),
            platform="win32",
            availability_probe=lambda: True,
        )

        loaded = view_model.load()
        self.assertTrue(loaded.ok, loaded.error)
        assert loaded.value is not None
        self.assertEqual(loaded.value.setting_key, "enable_tray")
        self.assertFalse(loaded.value.keep_resident)

        updated = view_model.set_enabled(True)

        self.assertTrue(updated.ok, updated.error)
        assert updated.value is not None
        self.assertTrue(updated.value.keep_resident)
        self.assertEqual(repository.values[(1, "enable_tray")], "1")
        self.assertEqual(residency_setting_key("darwin"), "enable_menu_bar")
        self.assertIsNone(residency_setting_key("linux"))

    def test_qt_residency_controller_tracks_platform_availability(self) -> None:
        repository = MemorySettingsRepository()
        repository.set(1, "enable_tray", "1")
        view_model = ResidencyViewModel(
            user_id=1,
            get_handler=GetSettingHandler(repository),
            set_handler=SetSettingHandler(repository),
            platform="win32",
            availability_probe=lambda: True,
        )
        controller = QtResidencyController(
            view_model,
            application=self._app,
            tray_available=lambda: True,
        )

        state = controller.refresh()

        self.assertIsNotNone(state)
        self.assertTrue(controller.should_keep_resident())
        controller.request_quit()
        self.assertTrue(controller.quit_requested)


if __name__ == "__main__":
    unittest.main()
