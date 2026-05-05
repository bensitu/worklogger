import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date
from unittest.mock import patch


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_ROOT = os.path.join(PROJECT_ROOT, "worklogger")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from config.constants import (
    DEFAULT_BREAK_SETTING_KEY,
    MONTHLY_TARGET_SETTING_KEY,
    WORK_HOURS_SETTING_KEY,
)
from data.db import DB
from services.app_services import AppServices
from services.analytics_service import monthly_chart_data_v3


class EdgeCaseResilienceTests(unittest.TestCase):
    def _services(self) -> AppServices:
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        db = DB(path)
        self.addCleanup(db.conn.close)
        services = AppServices(db=db)
        user_id = services.auth.register("admin", "secret123", "adminkey12345678")
        services.set_current_user(user_id)
        return services

    def test_login_empty_username_or_password_is_rejected(self):
        services = self._services()

        with self.assertRaises(ValueError):
            services.auth.login("", "secret123")
        with self.assertRaises(ValueError):
            services.auth.login("admin", "")

    def test_register_existing_username_is_rejected(self):
        services = self._services()

        with self.assertRaises(ValueError):
            services.auth.register("admin", "secret123", "anotherkey123456")

    def test_wrong_recovery_key_does_not_reset_password(self):
        services = self._services()

        changed = services.auth.reset_password_with_recovery(
            "admin",
            "wrongkey",
            "secret456",
        )

        self.assertFalse(changed)
        self.assertEqual(services.auth.login("admin", "secret123"), services.current_user_id)

    def test_missing_recovery_key_is_rejected_cleanly(self):
        services = self._services()

        with self.assertRaises(ValueError):
            services.auth.reset_password_with_recovery(
                "admin",
                None,
                "secret456",
            )

    def test_worklog_note_sql_injection_payload_is_stored_as_data(self):
        services = self._services()
        payload = "x'); DROP TABLE worklog; --"

        services.save_record("2026-04-30", None, None, 1.0, payload)

        self.assertEqual(services.get_record("2026-04-30").note, payload)
        count = services.db.conn.execute(
            "SELECT COUNT(*) FROM worklog WHERE user_id=?",
            (services.current_user_id,),
        ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_very_long_note_round_trips(self):
        services = self._services()
        note = "x" * 100_000

        services.save_record("2099-12-31", "09:00", "18:00", 1.0, note)

        self.assertEqual(services.get_record("2099-12-31").note, note)

    def test_empty_chart_data_returns_empty_bundle(self):
        bundle = monthly_chart_data_v3(
            date(2026, 4, 30),
            date(2026, 4, 1),
            "hours",
            True,
            record_getter=lambda _day: None,
        )

        self.assertEqual(bundle.bar_data, [])
        self.assertEqual(bundle.line_data, [])
        self.assertEqual(bundle.leave_indices, set())
        self.assertEqual(bundle.leave_line_data, [])

    def test_restore_invalid_path_raises_file_not_found(self):
        services = self._services()

        with self.assertRaises(FileNotFoundError):
            services.validate_restore_database(
                os.path.join(tempfile.gettempdir(), "missing-worklogger.db")
            )

    def test_failed_backup_does_not_update_last_backup_timestamp(self):
        services = self._services()
        dest = os.path.join(tempfile.gettempdir(), "worklogger-failed-backup.db")

        with patch("services.app_services.shutil.copy2", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                services.backup_database(dest)

        self.assertEqual(services.get_setting("last_backup_timestamp", ""), "")

    def test_load_settings_tolerates_corrupt_float_values(self):
        services = self._services()
        services.set_setting(WORK_HOURS_SETTING_KEY, "not-a-number")
        services.set_setting(DEFAULT_BREAK_SETTING_KEY, "")
        services.set_setting(MONTHLY_TARGET_SETTING_KEY, "nan-hours")

        state = services.load_settings()

        self.assertEqual(state.work_hours, 8.0)
        self.assertEqual(state.default_break, 1.0)
        self.assertEqual(state.monthly_target, 168.0)

    def test_restore_database_copy_failure_keeps_original_database(self):
        services = self._services()
        original_path = services.db.path
        original_user_id = services.current_user_id
        fd, restore_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        restore_db = DB(restore_path)
        def _cleanup_restore_db() -> None:
            try:
                restore_db.conn.close()
            except Exception:
                pass
            for candidate in (restore_path, restore_path + "-wal", restore_path + "-shm"):
                try:
                    if os.path.exists(candidate):
                        os.remove(candidate)
                except OSError:
                    pass
        self.addCleanup(_cleanup_restore_db)
        restore_db.create_user(
            "admin",
            "restored123",
            recovery_key="restorekey123456",
            is_admin=True,
        )
        restore_db.conn.close()

        with patch("services.app_services.shutil.copy2", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                services.restore_database(restore_path)

        self.assertEqual(services.db.path, original_path)
        self.assertEqual(services.auth.login("admin", "secret123"), original_user_id)
        self.assertFalse(os.path.exists(original_path + ".tmp_restore"))

    def test_restore_database_activation_failure_reopens_original_database(self):
        services = self._services()
        self.addCleanup(lambda: services.db.conn.close())
        original_path = services.db.path
        original_user_id = services.current_user_id
        fd, restore_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        restore_db = DB(restore_path)

        def _cleanup_restore_db() -> None:
            try:
                restore_db.conn.close()
            except Exception:
                pass
            for candidate in (restore_path, restore_path + "-wal", restore_path + "-shm"):
                try:
                    if os.path.exists(candidate):
                        os.remove(candidate)
                except OSError:
                    pass

        self.addCleanup(_cleanup_restore_db)
        restore_db.create_user(
            "admin",
            "restored123",
            recovery_key="restorekey123456",
            is_admin=True,
        )
        restore_db.conn.close()

        real_db = DB
        calls = []

        def _flaky_db(path: str):
            calls.append(path)
            if len(calls) == 1:
                raise sqlite3.DatabaseError("activation failed")
            return real_db(path)

        with patch("services.app_services.DB", side_effect=_flaky_db):
            with self.assertLogs("services.app_services", level="ERROR"):
                with self.assertRaises(sqlite3.DatabaseError):
                    services.restore_database(restore_path)

        self.assertEqual(services.db.path, original_path)
        self.assertEqual(services.current_user_id, original_user_id)
        self.assertEqual(services.auth.login("admin", "secret123"), original_user_id)
        self.assertFalse(os.path.exists(original_path + ".tmp_restore"))
        self.assertFalse(os.path.exists(original_path + ".pre_restore"))


if __name__ == "__main__":
    unittest.main()

