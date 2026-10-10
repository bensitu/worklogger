from __future__ import annotations

import base64
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import tempfile
import sqlite3
import unittest

from worklogger.app.commands.auth_commands import (
    ChangePasswordCommand,
    LoginCommand,
    RegisterUserCommand,
    ResetPasswordCommand,
)
from worklogger.app.commands.quick_log_commands import AddQuickLogCommand, UpdateQuickLogCommand, DeleteQuickLogCommand
from worklogger.app.commands.report_commands import SaveReportCommand
from worklogger.app.commands.settings_commands import SetActiveLocalModelCommand
from worklogger.app.commands.work_log_commands import SaveWorkLogCommand
from worklogger.app.queries.analytics_queries import GetAnalyticsBundleQuery
from worklogger.app.queries.quick_log_queries import GetQuickLogsForRangeQuery
from worklogger.app.queries.report_queries import GetReportForPeriodQuery
from worklogger.app.use_cases.analytics import GetAnalyticsBundleHandler
from worklogger.app.use_cases.auth import (
    ChangePasswordHandler,
    LoginHandler,
    LoginWithRememberTokenHandler,
    RegisterUserHandler,
    ResetPasswordHandler,
)
from worklogger.app.use_cases.quick_logs import AddQuickLogHandler, GetQuickLogsForRangeHandler, UpdateQuickLogHandler, DeleteQuickLogHandler
from worklogger.app.use_cases.reports import GetReportForPeriodHandler, SaveReportHandler
from worklogger.app.use_cases.settings import SetActiveLocalModelHandler
from worklogger.app.use_cases.work_logs import SaveWorkLogHandler
from worklogger.config.constants import LOCAL_MODEL_ACTIVE_ID_SETTING_KEY
from worklogger.domain.auth.models import LinkedIdentity
from worklogger.domain.calendar.models import CalendarEvent
from worklogger.domain.worklog.models import WorkType
from worklogger.infrastructure.database import (
    MigrationRunner,
    SQLiteConnectionFactory,
    SQLiteUnitOfWork,
    default_database_path,
)
from worklogger.infrastructure.database.paths import prune_corrupt_backups
from worklogger.infrastructure.repositories import (
    ActivityEvent,
    SQLiteActivityRepository,
    SQLiteAuthRepository,
    SQLiteCalendarEventRepository,
    SQLiteIdentityRepository,
    SQLiteLoginFailureRepository,
    SQLiteQuickLogRepository,
    SQLiteReportRepository,
    SQLiteSettingsRepository,
    SQLiteWorkLogRepository,
)
from worklogger.infrastructure.security import (
    EncryptedSettingsKeyStore,
    FileRememberTokenSessionStore,
    FileMachineKeyProvider,
    HmacSecretBox,
    NoKeyringBackend,
    PBKDF2PasswordHasher,
)


class MemoryKeyringBackend:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, name: str) -> str | None:
        return self.values.get((service, name))

    def set_password(self, service: str, name: str, value: str) -> None:
        self.values[(service, name)] = value

    def delete_password(self, service: str, name: str) -> None:
        self.values.pop((service, name), None)


class SQLiteInfrastructureTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tempdir.cleanup)
        self.db_path = f"{self._tempdir.name}/worklog.db"
        self.factory = SQLiteConnectionFactory(self.db_path)
        self.assertEqual(MigrationRunner(self.factory).run_pending(), (1, 2, 3, 4, 5, 6, 7, 8, 9, 10))

    def auth_repository(self) -> SQLiteAuthRepository:
        return SQLiteAuthRepository(
            self.factory,
            password_hasher=PBKDF2PasswordHasher(
                iterations=1_000,
                legacy_iterations=(100,),
            ),
        )

    def test_collection_reads_preserve_valid_records_and_mutations_require_ownership(self) -> None:
        user = self.auth_repository().create_user("collection-user", "test-password", recovery_key=None, is_admin=False)
        day = date(2026, 5, 1)
        repository = SQLiteQuickLogRepository(self.factory)
        added = AddQuickLogHandler(repository).handle(AddQuickLogCommand(user.id, day, "Valid record"))
        record_id = added.value.id
        with self.factory.transaction(write=True) as connection:
            connection.execute("UPDATE quick_logs SET created_at='invalid' WHERE id=?", (record_id,))
            connection.execute("INSERT INTO worklog(user_id,d,\"break\",note,work_type) VALUES(?, '2026-05-15X', 0, '', 'normal')", (user.id,))
            connection.execute("INSERT INTO worklog(user_id,d,\"break\",note,work_type) VALUES(?, '2026-05-01', 0, '', 'normal')", (user.id,))
        with self.assertLogs("worklogger.infrastructure.repositories._mapping", level="WARNING"):
            records = SQLiteWorkLogRepository(self.factory).list_for_month(user.id, 2026, 5)
            quick_logs = repository.list_for_day(user.id, day)
        self.assertEqual(len(records), 1)
        self.assertEqual(len(quick_logs), 1)
        self.assertIsNone(quick_logs[0].created_at)
        self.assertFalse(UpdateQuickLogHandler(repository).handle(UpdateQuickLogCommand(user.id + 1, record_id, day, "Not owned")).ok)
        self.assertFalse(DeleteQuickLogHandler(repository).handle(DeleteQuickLogCommand(user.id + 1, record_id)).ok)
        self.assertTrue(DeleteQuickLogHandler(repository).handle(DeleteQuickLogCommand(user.id, record_id)).ok)
        self.assertFalse(DeleteQuickLogHandler(repository).handle(DeleteQuickLogCommand(user.id, record_id)).ok)
        with self.factory.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM worklog").fetchone()[0], 2)

    def test_password_hasher_verifies_legacy_iterations(self) -> None:
        hasher = PBKDF2PasswordHasher(iterations=1_000, legacy_iterations=(100,))
        salt_hex = "11" * 16
        legacy_hash = hasher.hash_with_salt("secret123", salt_hex, iterations=100)

        verification = hasher.verify("secret123", legacy_hash, salt_hex)

        self.assertTrue(verification.matched)
        self.assertTrue(verification.needs_upgrade)

    def test_migration_runner_is_idempotent_and_enables_foreign_keys(self) -> None:
        self.assertEqual(MigrationRunner(self.factory).run_pending(), ())
        with self.factory.connection() as connection:
            tables = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertIn("schema_migrations", tables)
            self.assertIn("users", tables)
            self.assertIn("worklog", tables)
            self.assertIn("activity_events", tables)
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)

        with SQLiteUnitOfWork(self.factory).transaction(write=False) as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0],
                10,
            )

    def test_database_path_rules_for_source_and_frozen_modes(self) -> None:
        source_root = Path(self._tempdir.name) / "worklogger"
        exe_path = Path(self._tempdir.name) / "dist" / "WorkLogger.exe"
        user_path = Path(self._tempdir.name) / "user-data"

        self.assertEqual(
            default_database_path(frozen=False, package_root_path=source_root),
            source_root / "worklog.db",
        )
        self.assertEqual(
            default_database_path(frozen=True, executable=str(exe_path), user_data_path=user_path),
            user_path / "worklog.db",
        )

    def test_corrupt_database_is_quarantined_and_recreated(self) -> None:
        corrupt_path = Path(self._tempdir.name) / "corrupt.db"
        corrupt_path.write_bytes(b"not a sqlite database")
        factory = SQLiteConnectionFactory(corrupt_path, recover_corrupt=True, corrupt_backup_retention=2)

        self.assertEqual(MigrationRunner(factory).run_pending(), (1, 2, 3, 4, 5, 6, 7, 8, 9, 10))

        backups = sorted(corrupt_path.parent.glob("corrupt.db.bak_*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b"not a sqlite database")
        with factory.connection() as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_corrupt_database_backups_are_pruned(self) -> None:
        database_path = Path(self._tempdir.name) / "retention.db"
        for index in range(4):
            backup = database_path.with_name(f"retention.db.bak_corrupt_{index}")
            backup.write_text(str(index), encoding="utf-8")

        prune_corrupt_backups(database_path, keep=2)

        self.assertEqual(len(list(database_path.parent.glob("retention.db.bak_*"))), 2)

    def test_database_access_failure_preserves_existing_data(self) -> None:
        path = Path(self._tempdir.name) / "locked.db"
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("CREATE TABLE records(value TEXT)")
            connection.execute("INSERT INTO records VALUES('retained')")
            connection.commit()
        reader = sqlite3.connect(path)
        self.addCleanup(reader.close)
        reader.execute("BEGIN")
        reader.execute("SELECT * FROM records").fetchall()
        factory = SQLiteConnectionFactory(path, busy_timeout_ms=10, recover_corrupt=True)
        with self.assertRaises(sqlite3.OperationalError):
            factory.open()
        self.assertFalse(list(path.parent.glob("locked.db.bak_*")))
        self.assertEqual(reader.execute("SELECT value FROM records").fetchone()[0], "retained")

    def test_unknown_schema_version_is_rejected_without_changes(self) -> None:
        with self.factory.transaction() as connection:
            connection.execute("INSERT INTO schema_migrations VALUES(9999, 'future_schema', '2026-01-01')")
        with self.assertRaisesRegex(ValueError, "database_version_unsupported"):
            MigrationRunner(self.factory).run_pending()
        with self.factory.connection() as connection:
            self.assertEqual(connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 9999)

    def test_auth_handlers_use_sqlite_repository_and_hashed_remember_tokens(self) -> None:
        auth = self.auth_repository()
        failures = SQLiteLoginFailureRepository(self.factory)
        registered = RegisterUserHandler(auth).handle(
            RegisterUserCommand("alice", "secret123")
        )
        self.assertTrue(registered.ok)
        assert registered.value is not None
        self.assertTrue(registered.value.user.is_admin)

        duplicate = RegisterUserHandler(auth).handle(
            RegisterUserCommand("alice", "secret456")
        )
        self.assertFalse(duplicate.ok)
        self.assertEqual(duplicate.error.code if duplicate.error else "", "username_exists")

        logged_in = LoginHandler(auth, failures).handle(
            LoginCommand("alice", "secret123", remember=True)
        )
        self.assertTrue(logged_in.ok)
        assert logged_in.value is not None
        self.assertTrue(logged_in.value.token)
        with self.factory.connection() as connection:
            row = connection.execute(
                "SELECT remember_token FROM users WHERE username='alice'"
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertNotEqual(row["remember_token"], logged_in.value.token)
        self.assertTrue(str(row["remember_token"]).startswith("sha256:"))

        remembered = LoginWithRememberTokenHandler(auth).handle(logged_in.value.token or "")
        self.assertTrue(remembered.ok)
        assert remembered.value is not None
        self.assertEqual(remembered.value.username, "alice")

        changed = ChangePasswordHandler(auth).handle(
            ChangePasswordCommand(registered.value.user.id, "secret123", "secret456")
        )
        self.assertTrue(changed.ok)
        self.assertFalse(LoginHandler(auth, failures).handle(LoginCommand("alice", "secret123")).ok)
        self.assertTrue(LoginHandler(auth, failures).handle(LoginCommand("alice", "secret456")).ok)

        reset = ResetPasswordHandler(auth).handle(
            ResetPasswordCommand("alice", changed.value or "", "secret789")
        )
        self.assertTrue(reset.ok)
        self.assertTrue(LoginHandler(auth, failures).handle(LoginCommand("alice", "secret789")).ok)

    def test_login_failures_lock_out_after_threshold(self) -> None:
        auth = self.auth_repository()
        failures = SQLiteLoginFailureRepository(self.factory)
        RegisterUserHandler(auth).handle(RegisterUserCommand("alice", "secret123"))

        for _ in range(5):
            self.assertFalse(
                LoginHandler(auth, failures).handle(LoginCommand("alice", "wrong")).ok
            )

        blocked = LoginHandler(auth, failures).handle(LoginCommand("alice", "secret123"))
        self.assertFalse(blocked.ok)
        self.assertEqual(blocked.error.code if blocked.error else "", "invalid_credentials")

    def test_worklog_quicklog_settings_report_and_analytics_repositories(self) -> None:
        auth = self.auth_repository()
        registered = RegisterUserHandler(auth).handle(RegisterUserCommand("alice", "secret123"))
        assert registered.value is not None
        user_id = registered.value.user.id

        work_logs = SQLiteWorkLogRepository(self.factory)
        saved_work_log = SaveWorkLogHandler(work_logs).handle(
            SaveWorkLogCommand(
                user_id=user_id,
                day=date(2026, 4, 20),
                start_time="2200",
                end_time="0900",
                break_hours=1.0,
                note="Night shift",
                work_type=WorkType.NORMAL.value,
            )
        )
        self.assertTrue(saved_work_log.ok)
        fetched = work_logs.get_for_day(user_id, date(2026, 4, 20))
        self.assertIsNotNone(fetched)
        assert fetched is not None
        self.assertTrue(fetched.overnight)
        self.assertEqual(fetched.worked_hours(), 10.0)

        SaveWorkLogHandler(work_logs).handle(
            SaveWorkLogCommand(
                user_id=user_id,
                day=date(2026, 4, 21),
                start_time=None,
                end_time=None,
                break_hours=0.0,
                note="Leave",
                work_type=WorkType.PAID_LEAVE.value,
            )
        )
        analytics = GetAnalyticsBundleHandler(work_logs).handle(
            GetAnalyticsBundleQuery(
                user_id=user_id,
                year=2026,
                month=4,
                metric="hours",
                include_leaves=True,
            )
        )
        self.assertTrue(analytics.ok)
        assert analytics.value is not None
        self.assertEqual(analytics.value.leave_line_data[3], 8.0)

        quick_logs = SQLiteQuickLogRepository(self.factory)
        added = AddQuickLogHandler(quick_logs).handle(
            AddQuickLogCommand(
                user_id=user_id,
                day=date(2026, 4, 20),
                description="Meeting",
                start_time="930",
                end_time="1000",
            )
        )
        self.assertTrue(added.ok)
        listed = GetQuickLogsForRangeHandler(quick_logs).handle(
            GetQuickLogsForRangeQuery(
                user_id=user_id,
                start_day=date(2026, 4, 1),
                end_day=date(2026, 4, 30),
            )
        )
        self.assertEqual(len(listed.value or ()), 1)

        settings = SQLiteSettingsRepository(self.factory)
        SetActiveLocalModelHandler(settings).handle(
            SetActiveLocalModelCommand(user_id=user_id, model_id="model-a")
        )
        self.assertEqual(settings.get(user_id, LOCAL_MODEL_ACTIVE_ID_SETTING_KEY), "model-a")

        reports = SQLiteReportRepository(self.factory)
        saved_report = SaveReportHandler(reports).handle(
            SaveReportCommand(
                user_id=user_id,
                report_type="weekly",
                period_start=date(2026, 4, 20),
                period_end=date(2026, 4, 26),
                content="weekly report",
            )
        )
        self.assertTrue(saved_report.ok)
        fetched_report = GetReportForPeriodHandler(reports).handle(
            GetReportForPeriodQuery(
                user_id=user_id,
                report_type="weekly",
                period_start=date(2026, 4, 20),
                period_end=date(2026, 4, 26),
            )
        )
        self.assertEqual(fetched_report.value, saved_report.value)

    def test_calendar_identity_and_activity_repositories(self) -> None:
        auth = self.auth_repository()
        registered = RegisterUserHandler(auth).handle(RegisterUserCommand("alice", "secret123"))
        assert registered.value is not None
        user_id = registered.value.user.id

        calendar = SQLiteCalendarEventRepository(self.factory)
        count = calendar.replace_all(
            user_id,
            (
                CalendarEvent(
                    id=None,
                    user_id=user_id,
                    day=date(2026, 4, 20),
                    summary="Planning",
                    start_time="09:00",
                    end_time="10:00",
                ),
            ),
        )
        self.assertEqual(count, 1)
        self.assertEqual(calendar.list_for_day(user_id, date(2026, 4, 20))[0].summary, "Planning")

        identities = SQLiteIdentityRepository(self.factory)
        identity = identities.add(
            LinkedIdentity(
                id=0,
                user_id=user_id,
                provider="google",
                subject="subject-1",
                email="alice@example.com",
            )
        )
        self.assertEqual(identities.list_for_user(user_id), (identity,))
        identities.remove(user_id, identity.id)
        self.assertEqual(identities.list_for_user(user_id), ())

        activity = SQLiteActivityRepository(self.factory)
        activity.record(ActivityEvent(user_id=user_id, event_type="login", details={"ok": True}))
        with self.factory.connection() as connection:
            row = connection.execute(
                "SELECT event_type, details FROM activity_events WHERE user_id=?",
                (user_id,),
            ).fetchone()
        self.assertEqual(row["event_type"], "login")
        self.assertIn('"ok": true', row["details"])

    def test_encrypted_key_store_uses_keyring_when_available(self) -> None:
        auth = self.auth_repository()
        registered = RegisterUserHandler(auth).handle(RegisterUserCommand("alice", "secret123"))
        assert registered.value is not None
        user_id = registered.value.user.id
        settings = SQLiteSettingsRepository(self.factory)
        keyring = MemoryKeyringBackend()
        store = EncryptedSettingsKeyStore(
            settings,
            user_id=user_id,
            keyring_backend=keyring,
        )

        result = store.set_secret("ai_api_key", "super-secret")

        self.assertTrue(result.ok)
        self.assertEqual(store.get_secret("ai_api_key").value, "super-secret")
        self.assertIsNone(settings.get(user_id, "secret:ai_api_key"))
        self.assertIn(("WorkLogger", "ai_api_key"), keyring.values)

    def test_encrypted_key_store_falls_back_to_encrypted_settings(self) -> None:
        auth = self.auth_repository()
        registered = RegisterUserHandler(auth).handle(RegisterUserCommand("alice", "secret123"))
        assert registered.value is not None
        user_id = registered.value.user.id
        settings = SQLiteSettingsRepository(self.factory)
        key_path = Path(self._tempdir.name) / "machine.key"
        secret_box = HmacSecretBox(FileMachineKeyProvider(key_path))
        store = EncryptedSettingsKeyStore(
            settings,
            user_id=user_id,
            keyring_backend=NoKeyringBackend(),
            secret_box=secret_box,
        )

        result = store.set_secret("ai_api_key", "super-secret")

        self.assertTrue(result.ok)
        stored = settings.get(user_id, "secret:ai_api_key")
        self.assertIsNotNone(stored)
        self.assertTrue(str(stored).startswith("enc2:"))
        self.assertNotIn("super-secret", str(stored))

        reopened = EncryptedSettingsKeyStore(
            settings,
            user_id=user_id,
            keyring_backend=NoKeyringBackend(),
            secret_box=HmacSecretBox(FileMachineKeyProvider(key_path)),
        )
        self.assertEqual(reopened.get_secret("ai_api_key").value, "super-secret")
        self.assertTrue(key_path.exists())

        deleted = reopened.delete_secret("ai_api_key")
        self.assertTrue(deleted.ok)
        self.assertIsNone(settings.get(user_id, "secret:ai_api_key"))

    def test_encrypted_key_store_rejects_tampered_ciphertext(self) -> None:
        auth = self.auth_repository()
        registered = RegisterUserHandler(auth).handle(RegisterUserCommand("alice", "secret123"))
        assert registered.value is not None
        user_id = registered.value.user.id
        settings = SQLiteSettingsRepository(self.factory)
        key_path = Path(self._tempdir.name) / "machine.key"
        store = EncryptedSettingsKeyStore(
            settings,
            user_id=user_id,
            keyring_backend=NoKeyringBackend(),
            secret_box=HmacSecretBox(FileMachineKeyProvider(key_path)),
        )
        self.assertTrue(store.set_secret("ai_api_key", "super-secret").ok)
        stored = settings.get(user_id, "secret:ai_api_key") or ""
        prefix = "enc2:"
        payload = bytearray(base64.urlsafe_b64decode(stored[len(prefix) :].encode("ascii")))
        payload[-1] ^= 0x01
        tampered = prefix + base64.urlsafe_b64encode(bytes(payload)).decode("ascii")
        settings.set(user_id, "secret:ai_api_key", tampered)

        result = store.get_secret("ai_api_key")

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code if result.error else "", "secret_authentication_failed")

    def test_file_remember_token_store_encrypts_loads_and_clears_token(self) -> None:
        token_path = Path(self._tempdir.name) / "remember_session.enc"
        key_path = Path(self._tempdir.name) / "machine.key"
        store = FileRememberTokenSessionStore(
            token_path,
            secret_box=HmacSecretBox(FileMachineKeyProvider(key_path)),
        )

        saved = store.save_token("plain-token")

        self.assertTrue(saved.ok, saved.error)
        self.assertTrue(token_path.exists())
        self.assertNotIn("plain-token", token_path.read_text(encoding="utf-8"))
        self.assertEqual(store.load_token().value, "plain-token")

        cleared = store.clear_token()

        self.assertTrue(cleared.ok, cleared.error)
        self.assertFalse(token_path.exists())
        self.assertIsNone(store.load_token().value)

    def test_credentials_upgrade_older_ciphertext_and_preserve_invalid_keys(self):
        key_path = Path(self._tempdir.name) / "machine.key"
        key_path.write_text(base64.urlsafe_b64encode(bytes(range(32))).decode("ascii"), encoding="ascii")
        token_path = Path(self._tempdir.name) / "remember_session.enc"
        token_path.write_text("enc1:AAECAwQFBgcICQoLDA0OD0LCQBoVPQkluofQClDWlMDl9dOH-TKP9wwrKnsFItAX_uPNOBW30ZL-aiEwkDt5qU2Lew==", encoding="ascii")
        store = FileRememberTokenSessionStore(token_path, secret_box=HmacSecretBox(FileMachineKeyProvider(key_path)))
        self.assertEqual(store.load_token().value, "compatibility-token")
        self.assertTrue(token_path.read_text().startswith("enc2:"))
        key_path.write_text("invalid key", encoding="ascii")
        self.assertFalse(store.load_token().ok)
        self.assertFalse(store.save_token("replacement").ok)
        self.assertEqual(key_path.read_text(), "invalid key")
        key_path.unlink()
        self.assertFalse(store.load_token().ok)
        self.assertFalse(key_path.exists())

    def test_login_failure_retention_and_successful_login_time(self):
        auth = self.auth_repository()
        user = auth.create_user("alice", "secret123", recovery_key=None, is_admin=True)
        now = datetime(2026, 5, 1, tzinfo=timezone.utc)
        failures = SQLiteLoginFailureRepository(self.factory, clock=lambda: now)
        self.assertEqual(failures.record_failure("unknown"), (0, None))
        for _ in range(4):
            failures.record_failure("alice")
        now += timedelta(days=2)
        self.assertEqual(failures.record_failure("alice"), (1, None))
        now += timedelta(days=8)
        failures.prune()
        with self.factory.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM login_attempts").fetchone()[0], 0)
        logged_in = auth.verify_user("alice", "secret123")
        self.assertIsNotNone(logged_in.last_login_at)
        self.assertEqual(auth.get_by_id(user.id).last_login_at, logged_in.last_login_at)


if __name__ == "__main__":
    unittest.main()
